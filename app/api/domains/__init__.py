import re
from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import dns_service
from app.services.plan_service import get_current_plan
from app import db
from app.models.domain import Domain, DNSRecord
from datetime import datetime

# RFC-1123 hostname: labels separated by dots, each 1–63 chars [a-z0-9-]
_DOMAIN_RE = re.compile(
    r'^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$'
)


# --- Local Domain Management ---

@api_bp.route('/domains', methods=['GET'])
@login_required
def list_local_domains():
    """List all locally tracked domains."""
    domains = Domain.query.order_by(Domain.name).all()
    return jsonify({'domains': [d.to_dict() for d in domains]})


@api_bp.route('/domains', methods=['POST'])
@login_required
def create_local_domain():
    """Track a new domain locally."""
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
    )
    db.session.add(domain)
    db.session.commit()
    return jsonify({'domain': domain.to_dict()}), 201


@api_bp.route('/domains/<int:domain_id>', methods=['GET'])
@login_required
def get_local_domain(domain_id):
    """Get a locally tracked domain with its DNS records."""
    domain = Domain.query.get_or_404(domain_id)
    result = domain.to_dict()
    result['dns_records'] = [r.to_dict() for r in domain.dns_records]
    return jsonify({'domain': result})


@api_bp.route('/domains/<int:domain_id>', methods=['PUT'])
@login_required
def update_local_domain(domain_id):
    """Update a locally tracked domain."""
    domain = Domain.query.get_or_404(domain_id)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    for field in ('registrar', 'status', 'purpose', 'notes', 'mailgun_region', 'cloudflare_zone_id'):
        if field in data:
            setattr(domain, field, data[field])

    db.session.commit()
    return jsonify({'domain': domain.to_dict()})


@api_bp.route('/domains/<int:domain_id>', methods=['DELETE'])
@login_required
def delete_local_domain(domain_id):
    """Remove a domain from local tracking (does not affect Cloudflare)."""
    domain = Domain.query.get_or_404(domain_id)
    db.session.delete(domain)
    db.session.commit()
    return jsonify({'deleted': True})


@api_bp.route('/domains/<int:domain_id>/sync', methods=['POST'])
@login_required
def sync_domain(domain_id):
    """Sync a domain's DNS records from Cloudflare into the local database."""
    domain = Domain.query.get_or_404(domain_id)
    if not domain.cloudflare_zone_id:
        return jsonify({'error': 'Domain has no Cloudflare zone ID linked'}), 400

    try:
        records = dns_service.list_dns_records(domain.cloudflare_zone_id)
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
            )
            db.session.add(db_rec)

    for cf_id, db_rec in existing.items():
        if cf_id not in seen_ids:
            db.session.delete(db_rec)

    domain.last_synced_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'synced': len(records), 'domain': domain.to_dict()})


# --- Cloudflare Zones ---

@api_bp.route('/domains/zones', methods=['GET'])
@login_required
def list_zones():
    try:
        name_filter = request.args.get('name')
        page = request.args.get('page', 1, type=int)
        zones, page_info = dns_service.list_zones(name_filter=name_filter, page=page)
        return jsonify({'zones': zones, 'page_info': page_info})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>', methods=['GET'])
@login_required
def get_zone(zone_id):
    try:
        zone = dns_service.get_zone(zone_id)
        return jsonify({'zone': zone})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- DNS Records (Cloudflare) ---

@api_bp.route('/domains/zones/<zone_id>/records', methods=['GET'])
@login_required
def list_dns_records(zone_id):
    try:
        record_type = request.args.get('type')
        name = request.args.get('name')
        records = dns_service.list_dns_records(zone_id, record_type=record_type, name=name)
        return jsonify({'records': records})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/records', methods=['POST'])
@login_required
def create_dns_record(zone_id):
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
            priority=data.get('priority')
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
            )
            db.session.add(db_rec)
            db.session.commit()

        return jsonify({'record': record}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/records/<record_id>', methods=['PUT'])
@login_required
def update_dns_record(zone_id, record_id):
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
            priority=data.get('priority')
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
    try:
        dns_service.delete_dns_record(zone_id, record_id)

        # Remove from local DB if tracked
        db_rec = DNSRecord.query.filter_by(cloudflare_record_id=record_id).first()
        if db_rec:
            db.session.delete(db_rec)
            db.session.commit()

        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- SSL ---

@api_bp.route('/domains/zones/<zone_id>/ssl', methods=['GET'])
@login_required
def get_ssl(zone_id):
    try:
        result = dns_service.get_ssl_setting(zone_id)
        return jsonify({'ssl': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/ssl', methods=['PATCH'])
@login_required
def set_ssl(zone_id):
    data = request.get_json()
    value = data.get('value') if data else None
    if value not in ('off', 'flexible', 'full', 'strict'):
        return jsonify({'error': 'Invalid SSL value. Use: off, flexible, full, strict'}), 400

    try:
        result = dns_service.set_ssl_setting(zone_id, value)
        return jsonify({'ssl': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
