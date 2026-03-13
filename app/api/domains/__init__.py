import re
from flask import request, jsonify, abort
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import dns_service
from app.services import audit_service
from app.services.credential_service import get_account_labels
from app.services.plan_service import get_current_plan
from app.services.project_service import (
    get_user_project_ids,
    get_user_project_role,
    assert_domain_accessible,
)
from app.utils.decorators import admin_required
from app import db
from app.models.domain import Domain, DNSRecord
from datetime import datetime, timedelta

# RFC-1123 hostname: labels separated by dots, each 1–63 chars [a-z0-9-]
_DOMAIN_RE = re.compile(
    r'^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$'
)


def _zone_label(zone_id):
    """Return the credential label to use for a given zone_id.

    Resolution order:
    1. Local domain record (most authoritative — set when a domain is imported).
    2. The in-memory cache populated by list_zones_all_accounts() — covers zones
       that are visible in the selector but not yet imported locally.
    3. First available Cloudflare account label — safe fallback when neither of
       the above is populated (e.g. direct API calls before any zone listing).
    """
    domain = Domain.query.filter_by(cloudflare_zone_id=zone_id).first()
    if domain:
        return domain.credential_label

    cached = dns_service._zone_account_cache.get(zone_id)
    if cached:
        return cached

    labels = get_account_labels('cloudflare')
    return labels[0] if labels else 'default'


def _assert_zone_accessible(zone_id, write=False):
    """Abort 403 if the current user cannot access this Cloudflare zone.

    Admins: always allowed.
    Auditors: read-only access to all zones (no checkout required).
    Operators / project_admin / white_team: only if the zone maps to a domain
    checked out to one of their projects.

    write=True: additionally requires project_role in ('project_admin', 'operator')
                (blocks white_team and auditors).
    """
    if current_user.is_admin:
        return
    if current_user.is_auditor:
        if write:
            abort(403)
        return
    domain = Domain.query.filter_by(cloudflare_zone_id=zone_id).first()
    if not domain or domain.checkout_project_id is None:
        abort(403)
    if domain.checkout_project_id not in get_user_project_ids(current_user):
        abort(403)
    if write:
        role = get_user_project_role(current_user.id, domain.checkout_project_id)
        if role not in ('project_admin', 'operator'):
            abort(403)


# ---------------------------------------------------------------------------
# Local Domain Management
# ---------------------------------------------------------------------------

@api_bp.route('/domains', methods=['GET'])
@login_required
def list_local_domains():
    """List locally tracked domains.

    Admin:
      - Returns all domains by default.
      - ?pool=true  → only available (un-checked-out) domains.
      - ?project_id=<id> → only domains checked out to that project.
    Operator / white_team:
      - Returns only domains checked out to their projects.
      - ?project_id=<id> further narrows to a single project they belong to.
    """
    pool_only = request.args.get('pool') == 'true'

    if current_user.is_admin or current_user.is_project_admin:
        project_filter = request.args.get('project_id', type=int)

        if pool_only:
            domains = Domain.query.filter_by(
                checkout_project_id=None
            ).order_by(Domain.name).all()
        elif project_filter:
            domains = Domain.query.filter_by(
                checkout_project_id=project_filter
            ).order_by(Domain.name).all()
        else:
            domains = Domain.query.order_by(Domain.name).all()
    elif pool_only:
        # Any authenticated user may browse the available pool
        domains = Domain.query.filter_by(
            checkout_project_id=None
        ).order_by(Domain.name).all()
    else:
        project_ids = get_user_project_ids(current_user)
        if not project_ids:
            return jsonify({'domains': []})

        project_filter = request.args.get('project_id', type=int)
        if project_filter:
            if project_filter not in project_ids:
                return jsonify({'error': 'Not a member of this project'}), 403
            domains = Domain.query.filter_by(
                checkout_project_id=project_filter
            ).order_by(Domain.name).all()
        else:
            domains = Domain.query.filter(
                Domain.checkout_project_id.in_(project_ids)
            ).order_by(Domain.name).all()

    return jsonify({'domains': [d.to_dict() for d in domains]})


@api_bp.route('/domains', methods=['POST'])
@login_required
@admin_required
def create_local_domain():
    """Track a new domain locally (admin only — adds a domain to the pool)."""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Domain name is required'}), 400

    name = data['name'].strip().lower()

    if len(name) > 253:
        return jsonify({'error': 'Domain name too long (max 253 characters)'}), 400
    if not _DOMAIN_RE.match(name):
        return jsonify({'error': 'Invalid domain name format'}), 400

    # Enforce plan domain limit
    plan = get_current_plan()
    current_count = Domain.query.count()
    if plan.at_domain_limit(current_count):
        limit_str = str(plan.max_domains)
        return jsonify({
            'error': f'Domain limit reached ({limit_str} domains on {plan.display_name} plan). Upgrade your plan to add more domains.',
            'code': 'PLAN_LIMIT_EXCEEDED',
            'upgrade_required': True,
        }), 402

    existing = Domain.query.filter_by(name=name).first()
    if existing:
        return jsonify({'error': 'Domain already tracked', 'domain': existing.to_dict()}), 409

    domain = Domain(
        name=name,
        cloudflare_zone_id=data.get('cloudflare_zone_id'),
        registrar=data.get('registrar'),
        status=data.get('status', 'active'),
        purpose=data.get('purpose'),
        notes=data.get('notes'),
        mailgun_region=data.get('mailgun_region'),
        provider=data.get('provider', 'cloudflare').strip() or 'cloudflare',
        credential_label=data.get('credential_label', 'default') or 'default',
    )
    db.session.add(domain)
    db.session.commit()
    return jsonify({'domain': domain.to_dict()}), 201


@api_bp.route('/domains/<int:domain_id>', methods=['GET'])
@login_required
def get_local_domain(domain_id):
    """Get a locally tracked domain with its DNS records."""
    domain = Domain.query.get_or_404(domain_id)
    assert_domain_accessible(domain, current_user)
    result = domain.to_dict()
    result['dns_records'] = [r.to_dict() for r in domain.dns_records]
    return jsonify({'domain': result})


@api_bp.route('/domains/<int:domain_id>', methods=['PUT'])
@login_required
@admin_required
def update_local_domain(domain_id):
    """Update a locally tracked domain (admin only — pool management)."""
    domain = Domain.query.get_or_404(domain_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    for field in ('registrar', 'status', 'purpose', 'notes', 'mailgun_region',
                  'cloudflare_zone_id', 'credential_label'):
        if field in data:
            setattr(domain, field, data[field])

    db.session.commit()
    return jsonify({'domain': domain.to_dict()})


@api_bp.route('/domains/<int:domain_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_local_domain(domain_id):
    """Remove a domain from local tracking (admin only).

    Blocked if the domain is currently checked out to a project.
    """
    domain = Domain.query.get_or_404(domain_id)

    if domain.checkout_project_id is not None:
        from app.models.project import Project
        project = Project.query.get(domain.checkout_project_id)
        code = project.code if project else str(domain.checkout_project_id)
        return jsonify({
            'error': f'Cannot delete domain while checked out to project {code}. '
                     'Release the domain first.',
            'checkout_project_id': domain.checkout_project_id,
        }), 409

    db.session.delete(domain)
    db.session.commit()
    return jsonify({'deleted': True})


@api_bp.route('/domains/<int:domain_id>/sync', methods=['POST'])
@login_required
def sync_domain(domain_id):
    """Sync a domain's DNS records from Cloudflare into the local database.

    Admin: any domain.
    Operator: only their checked-out domains (not white_team — read-only).
    """
    domain = Domain.query.get_or_404(domain_id)

    if not current_user.is_admin:
        # assert_domain_accessible checks checkout and project membership
        assert_domain_accessible(domain, current_user)
        # Additionally block white_team from triggering syncs
        if domain.checkout_project_id:
            role = get_user_project_role(current_user.id, domain.checkout_project_id)
            if role not in ('project_admin', 'operator'):
                return jsonify({'error': 'Operator access required to sync domain'}), 403

    if not domain.cloudflare_zone_id:
        return jsonify({'error': 'Domain has no Cloudflare zone ID linked'}), 400

    try:
        records = dns_service.list_dns_records(
            domain.cloudflare_zone_id, label=domain.credential_label
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    existing = {r.cloudflare_record_id: r for r in domain.dns_records}
    seen_ids = set()

    for rec in records:
        cf_id = rec['id']
        seen_ids.add(cf_id)

        if cf_id in existing:
            db_rec = existing[cf_id]
            db_rec.record_type = rec['type']
            db_rec.name = rec['name']
            db_rec.content = rec['content']
            db_rec.ttl = rec.get('ttl', 1)
            db_rec.proxied = rec.get('proxied', False)
            db_rec.priority = rec.get('priority')
            db_rec.provider = domain.provider or 'cloudflare'
        else:
            db_rec = DNSRecord(
                domain_id=domain.id,
                cloudflare_record_id=cf_id,
                record_type=rec['type'],
                name=rec['name'],
                content=rec['content'],
                ttl=rec.get('ttl', 1),
                proxied=rec.get('proxied', False),
                priority=rec.get('priority'),
                provider=domain.provider or 'cloudflare',
            )
            db.session.add(db_rec)

    for cf_id, db_rec in existing.items():
        if cf_id not in seen_ids:
            db.session.delete(db_rec)

    domain.last_synced_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'synced': len(records), 'domain': domain.to_dict()})


# ---------------------------------------------------------------------------
# Cloudflare Zones  (admin only — zone enumeration is not for operators)
# ---------------------------------------------------------------------------

@api_bp.route('/domains/zones', methods=['GET'])
@login_required
def list_zones():
    # Admins and project_admins: full list from Cloudflare across all accounts
    if current_user.is_admin or current_user.is_project_admin:
        try:
            zones = dns_service.list_zones_all_accounts()
            name_filter = request.args.get('name', '').lower()
            if name_filter:
                zones = [z for z in zones if name_filter in z.get('name', '').lower()]
            return jsonify({'zones': zones, 'page_info': {'total_count': len(zones)}})
        except Exception as e:
            return jsonify({'error': str(e)}), 400

    # Operators / white_team with ?pool=true: return all available (un-checked-out) CF zones
    # so operators can browse what's available to check out for their project.
    pool_only = request.args.get('pool') == 'true'
    if pool_only:
        try:
            all_zones = dns_service.list_zones_all_accounts()
        except Exception as e:
            return jsonify({'error': str(e)}), 400

        # Build set of zone_ids already checked out to any project
        taken_zone_ids = {
            d.cloudflare_zone_id
            for d in Domain.query.filter(
                Domain.checkout_project_id.isnot(None),
                Domain.cloudflare_zone_id.isnot(None),
            ).with_entities(Domain.cloudflare_zone_id).all()
        }
        zones = [z for z in all_zones if z.get('id') not in taken_zone_ids]
        return jsonify({'zones': zones, 'page_info': {'total_count': len(zones)}})

    # Operators / white_team (no pool flag): return only zones for the active project
    from app.services.project_service import get_active_project
    active_project = get_active_project(current_user)
    if active_project is None:
        return jsonify({'zones': [], 'page_info': {'total_count': 0}})

    checked_out = Domain.query.filter(
        Domain.checkout_project_id == active_project.id,
        Domain.cloudflare_zone_id.isnot(None),
    ).order_by(Domain.name).all()

    zones = [
        {
            'id': d.cloudflare_zone_id,
            'name': d.name,
            'status': d.status or 'active',
            'account_label': d.credential_label,
        }
        for d in checked_out
    ]
    return jsonify({'zones': zones, 'page_info': {'total_count': len(zones)}})


@api_bp.route('/domains/zones/<zone_id>', methods=['GET'])
@login_required
@admin_required
def get_zone(zone_id):
    try:
        zone = dns_service.get_zone(zone_id, label=_zone_label(zone_id))
        return jsonify({'zone': zone})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ---------------------------------------------------------------------------
# DNS Records (Cloudflare)
# Admin: unrestricted.
# Operator: only zones belonging to their checked-out domains.
# White team: read-only access to their checked-out domain zones.
# ---------------------------------------------------------------------------

@api_bp.route('/domains/zones/<zone_id>/records', methods=['GET'])
@login_required
def list_dns_records(zone_id):
    _assert_zone_accessible(zone_id, write=False)
    try:
        record_type = request.args.get('type')
        name = request.args.get('name')
        records = dns_service.list_dns_records(
            zone_id, record_type=record_type, name=name, label=_zone_label(zone_id)
        )
        return jsonify({'records': records})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/records', methods=['POST'])
@login_required
def create_dns_record(zone_id):
    _assert_zone_accessible(zone_id, write=True)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    for field in ('type', 'name', 'content'):
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    try:
        record = dns_service.create_dns_record(
            zone_id,
            record_type=data['type'],
            name=data['name'],
            content=data['content'],
            ttl=data.get('ttl', 1),
            proxied=data.get('proxied', False),
            priority=data.get('priority'),
            label=_zone_label(zone_id),
        )

        # Sync to local DB if domain is tracked
        domain = Domain.query.filter_by(cloudflare_zone_id=zone_id).first()
        if domain:
            db_rec = DNSRecord(
                domain_id=domain.id,
                cloudflare_record_id=record['id'],
                record_type=record['type'],
                name=record['name'],
                content=record['content'],
                ttl=record.get('ttl', 1),
                proxied=record.get('proxied', False),
                priority=record.get('priority'),
                managed_by='infrared',
                provider=domain.provider or 'cloudflare',
            )
            db.session.add(db_rec)
            db.session.commit()

        audit_service.log('dns.create', 'dns_record', record.get('id', ''),
                          f"{record.get('type')} {record.get('name')} → {record.get('content')}",
                          {'zone_id': zone_id, 'type': record.get('type'),
                           'name': record.get('name'), 'content': record.get('content')})
        return jsonify({'record': record}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/records/<record_id>', methods=['PUT'])
@login_required
def update_dns_record(zone_id, record_id):
    _assert_zone_accessible(zone_id, write=True)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    for field in ('type', 'name', 'content'):
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    try:
        record = dns_service.update_dns_record(
            zone_id, record_id,
            record_type=data['type'],
            name=data['name'],
            content=data['content'],
            ttl=data.get('ttl', 1),
            proxied=data.get('proxied', False),
            priority=data.get('priority'),
            label=_zone_label(zone_id),
        )

        # Update local DB if tracked
        db_rec = DNSRecord.query.filter_by(cloudflare_record_id=record_id).first()
        if db_rec:
            db_rec.record_type = record['type']
            db_rec.name = record['name']
            db_rec.content = record['content']
            db_rec.ttl = record.get('ttl', 1)
            db_rec.proxied = record.get('proxied', False)
            db_rec.priority = record.get('priority')
            db.session.commit()

        return jsonify({'record': record})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/records/<record_id>', methods=['DELETE'])
@login_required
def delete_dns_record(zone_id, record_id):
    _assert_zone_accessible(zone_id, write=True)
    try:
        dns_service.delete_dns_record(zone_id, record_id, label=_zone_label(zone_id))

        # Remove from local DB if tracked
        db_rec = DNSRecord.query.filter_by(cloudflare_record_id=record_id).first()
        if db_rec:
            db.session.delete(db_rec)
            db.session.commit()

        audit_service.log('dns.delete', 'dns_record', record_id, record_id,
                          {'zone_id': zone_id})
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ---------------------------------------------------------------------------
# SSL
# ---------------------------------------------------------------------------

@api_bp.route('/domains/zones/<zone_id>/ssl', methods=['GET'])
@login_required
def get_ssl(zone_id):
    _assert_zone_accessible(zone_id, write=False)
    try:
        result = dns_service.get_ssl_setting(zone_id, label=_zone_label(zone_id))
        return jsonify({'ssl': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/enable-dmarc', methods=['POST'])
@login_required
def enable_zone_dmarc(zone_id):
    """Enable Cloudflare DMARC Management for a zone.

    Returns the rua address Cloudflare provides for inclusion in the _dmarc TXT record.
    """
    _assert_zone_accessible(zone_id, write=True)
    try:
        result = dns_service.enable_dmarc_management(zone_id, label=_zone_label(zone_id))
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/ssl', methods=['PATCH'])
@login_required
def set_ssl(zone_id):
    _assert_zone_accessible(zone_id, write=True)
    data = request.get_json()
    value = data.get('value') if data else None
    if value not in ('off', 'flexible', 'full', 'strict'):
        return jsonify({'error': 'Invalid SSL value. Use: off, flexible, full, strict'}), 400

    try:
        result = dns_service.set_ssl_setting(zone_id, value, label=_zone_label(zone_id))
        return jsonify({'ssl': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ---------------------------------------------------------------------------
# Domain Pool Health (admin only)
# ---------------------------------------------------------------------------

_STALE_DAYS = 7

@api_bp.route('/domains/pool/health', methods=['GET'])
@login_required
@admin_required
def domain_pool_health():
    """Aggregate pool health: summary, per-account breakdown, per-domain flags."""
    domains = Domain.query.order_by(Domain.name).all()
    now = datetime.utcnow()
    stale_cutoff = now - timedelta(days=_STALE_DAYS)

    summary = {'total': 0, 'available': 0, 'checked_out': 0,
               'stale': 0, 'never_synced': 0}
    accounts = {}
    items = []

    for d in domains:
        summary['total'] += 1
        available = d.checkout_project_id is None
        stale = d.last_synced_at is None or d.last_synced_at < stale_cutoff

        if available:
            summary['available'] += 1
        else:
            summary['checked_out'] += 1
        if d.last_synced_at is None:
            summary['never_synced'] += 1
        if stale:
            summary['stale'] += 1

        label = d.credential_label or 'default'
        if label not in accounts:
            accounts[label] = {'label': label, 'total': 0, 'available': 0, 'checked_out': 0}
        accounts[label]['total'] += 1
        if available:
            accounts[label]['available'] += 1
        else:
            accounts[label]['checked_out'] += 1

        # DNS flags from locally synced records (no external API calls)
        records = list(d.dns_records)
        has_a = any(r.record_type == 'A' and r.name in (d.name, '@') for r in records)
        has_spf = any(r.record_type == 'TXT' and 'v=spf1' in (r.content or '') for r in records)
        has_dkim = any(r.record_type == 'TXT' and ('v=DKIM1' in (r.content or '') or 'k=rsa' in (r.content or '')) for r in records)
        has_dmarc = any(r.record_type == 'TXT' and 'v=DMARC1' in (r.content or '') for r in records)
        has_mx = any(r.record_type == 'MX' for r in records)

        items.append({
            'id': d.id,
            'name': d.name,
            'account_label': label,
            'status': d.status,
            'purpose': d.purpose,
            'checkout_project_id': d.checkout_project_id,
            'checkout_project_code': d.checkout_project.code if d.checkout_project else None,
            'checked_out_at': d.checked_out_at.isoformat() if d.checked_out_at else None,
            'record_count': len(records),
            'last_synced_at': d.last_synced_at.isoformat() if d.last_synced_at else None,
            'is_stale': stale,
            'dns_flags': {
                'a': has_a, 'spf': has_spf, 'dkim': has_dkim,
                'dmarc': has_dmarc, 'mx': has_mx,
            },
        })

    return jsonify({
        'summary': summary,
        'accounts': sorted(accounts.values(), key=lambda a: a['label']),
        'domains': items,
    })


@api_bp.route('/domains/<int:domain_id>/health', methods=['GET'])
@login_required
@admin_required
def domain_health_check(domain_id):
    """Run live readiness checks against external services for a single domain."""
    domain = Domain.query.get_or_404(domain_id)
    from app.services.readiness_service import check_domain_readiness
    return jsonify(check_domain_readiness(domain))
