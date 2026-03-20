import logging
from datetime import datetime
from flask import request, jsonify, session
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import audit_service
from app import db
from app.models.project import Project, ProjectMember, PROJECT_ROLES
from app.models.project_resource import ProjectResource, RESOURCE_TYPES
from app.models.domain import Domain
from app.models.cdn_distribution import CdnDistribution
from app.models.user import User
from app.utils.decorators import admin_required, project_member_required
from app.services.project_service import (
    get_projects_for_user,
    get_user_project_role,
    get_active_project,
    set_active_project,
    clear_active_project,
    get_resources_by_project,
    assert_domain_accessible,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Projects CRUD
# ---------------------------------------------------------------------------

@api_bp.route('/projects', methods=['GET'])
@login_required
def list_projects():
    projects = get_projects_for_user(current_user)
    include_members = request.args.get('include_members') == 'true'
    return jsonify([p.to_dict(include_members=include_members) for p in projects])


@api_bp.route('/projects', methods=['POST'])
@login_required
def create_project():
    if not current_user.can_manage_projects:
        return jsonify({'error': 'Project Admin or Admin role required to create projects'}), 403

    data = request.get_json(silent=True) or {}

    # Company is the driver — every project must belong to one
    company_id = data.get('company_id')
    if not company_id:
        return jsonify({'error': 'A company is required to create a project'}), 400
    from app.models.company import Company
    company = Company.query.get(company_id)
    if not company:
        return jsonify({'error': 'Company not found'}), 404

    # Use user-supplied codename or auto-generate one
    user_code = (data.get('name') or '').strip().upper()
    if user_code:
        existing = Project.query.filter_by(code=user_code).first()
        if existing:
            return jsonify({'error': f'Codename "{user_code}" is already in use'}), 409
        code = user_code
    else:
        from app.utils.codenames import generate_codename
        existing_codes = {p.code for p in Project.query.with_entities(Project.code).all()}
        code = generate_codename(existing_codes)

    name = code
    description = (data.get('description') or '').strip() or None

    project = Project(
        name=name,
        code=code,
        description=description,
        company_id=company_id,
        status='active',
        created_by_id=current_user.id,
    )
    db.session.add(project)
    db.session.flush()

    # Creator is automatically added as project_admin (if project_admin role) or operator (admin)
    creator_role = 'project_admin' if current_user.is_project_admin else 'operator'
    member = ProjectMember(
        project_id=project.id,
        user_id=current_user.id,
        project_role=creator_role,
        added_by_id=current_user.id,
    )
    db.session.add(member)
    db.session.commit()

    _log.info('User %s created project %s for company %s', current_user.email, code, company.code)
    audit_service.log('project.create', 'project', project.id, project.code,
                      {'name': name, 'company': company.code})
    return jsonify(project.to_dict(include_members=True)), 201


@api_bp.route('/projects/<int:project_id>', methods=['GET'])
@login_required
@project_member_required()
def get_project(project_id):
    from flask import g
    return jsonify(g.project.to_dict(include_members=True))


@api_bp.route('/projects/<int:project_id>', methods=['PATCH'])
@login_required
def update_project(project_id):
    project = Project.query.get_or_404(project_id)

    # Allow admin or project_admin who is a member of this project
    if not current_user.is_admin:
        if not current_user.is_project_admin:
            return jsonify({'error': 'Project Admin or Admin role required'}), 403
        member_role = get_user_project_role(current_user.id, project_id)
        if member_role != 'project_admin':
            return jsonify({'error': 'You are not a project admin of this project'}), 403

    data = request.get_json(silent=True) or {}

    if 'code' in data:
        code = (data['code'] or '').strip().upper()
        if not code:
            return jsonify({'error': 'Codename cannot be empty'}), 400
        if len(code) > 40:
            return jsonify({'error': 'Codename too long (max 40 characters)'}), 400
        existing = Project.query.filter(Project.code == code, Project.id != project_id).first()
        if existing:
            return jsonify({'error': f'Codename "{code}" is already in use'}), 409
        project.code = code
        project.name = code

    if 'name' in data and 'code' not in data:
        name = (data['name'] or '').strip()
        if not name:
            return jsonify({'error': 'Project name cannot be empty'}), 400
        project.name = name

    if 'description' in data:
        project.description = (data['description'] or '').strip() or None

    if 'status' in data:
        status = data['status']
        if status not in ('active', 'archived'):
            return jsonify({'error': 'Status must be "active" or "archived"'}), 400
        project.status = status

    db.session.commit()
    _log.info('User %s updated project %s', current_user.email, project.code)
    return jsonify(project.to_dict())


@api_bp.route('/projects/<int:project_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)

    # Block deletion if any domains are currently checked out
    checked_out = Domain.query.filter_by(checkout_project_id=project_id).count()
    if checked_out:
        return jsonify({
            'error': f'Cannot delete project: {checked_out} domain(s) are still checked out. '
                     'Release all domains first.',
        }), 409

    _log.info('Admin %s deleted project %s', current_user.email, project.code)
    audit_service.log('project.delete', 'project', project.id, project.code)
    db.session.delete(project)
    db.session.commit()
    return jsonify({'deleted': True})


# ---------------------------------------------------------------------------
# Project Members
# ---------------------------------------------------------------------------

@api_bp.route('/projects/<int:project_id>/members', methods=['GET'])
@login_required
@project_member_required()
def list_members(project_id):
    from flask import g
    members = ProjectMember.query.filter_by(project_id=project_id).all()
    return jsonify([m.to_dict() for m in members])


def _can_manage_members(project_id):
    """Return True if current_user can add/remove/update members of this project."""
    if current_user.is_admin:
        return True
    if current_user.is_project_admin:
        return get_user_project_role(current_user.id, project_id) == 'project_admin'
    return False


@api_bp.route('/projects/<int:project_id>/members', methods=['POST'])
@login_required
def add_member(project_id):
    project = Project.query.get_or_404(project_id)

    if not _can_manage_members(project_id):
        return jsonify({'error': 'Project Admin or Admin role required to manage members'}), 403

    data = request.get_json(silent=True) or {}

    user_id = data.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400

    user = User.query.get_or_404(user_id)

    # Default project_role to match the user's system role when not provided
    _ROLE_TO_PROJECT_ROLE = {
        'admin': 'project_admin',
        'project_admin': 'project_admin',
        'operator': 'operator',
        'white_team': 'white_team',
    }
    default_role = _ROLE_TO_PROJECT_ROLE.get(user.role, 'operator')
    project_role = (data.get('project_role') or default_role).strip()

    if project_role not in PROJECT_ROLES:
        return jsonify({'error': f'project_role must be one of: {", ".join(PROJECT_ROLES)}'}), 400

    # Auditors don't need project membership — they already see everything
    if user.is_auditor:
        return jsonify({'error': 'Auditors have global read access; project membership is not needed'}), 400

    # white_team users can only be added to projects linked to their company
    if user.is_white_team:
        if project_role != 'white_team':
            return jsonify({'error': 'Users with white_team role must be added with project_role=white_team'}), 400
        if user.company_id is None or project.company_id is None or user.company_id != project.company_id:
            return jsonify({
                'error': 'White team user can only be added to projects belonging to their company',
            }), 409

    if ProjectMember.query.filter_by(project_id=project_id, user_id=user_id).first():
        return jsonify({'error': 'User is already a member of this project'}), 409

    member = ProjectMember(
        project_id=project_id,
        user_id=user_id,
        project_role=project_role,
        added_by_id=current_user.id,
    )
    db.session.add(member)
    db.session.commit()

    _log.info('User %s added user %s to project %s as %s',
              current_user.email, user.email, project.code, project_role)
    audit_service.log('project.member_add', 'project', project.id, project.code,
                      {'user': user.email, 'role': project_role})
    return jsonify(member.to_dict()), 201


@api_bp.route('/projects/<int:project_id>/members/<int:user_id>', methods=['PUT'])
@login_required
def update_member(project_id, user_id):
    Project.query.get_or_404(project_id)

    if not _can_manage_members(project_id):
        return jsonify({'error': 'Project Admin or Admin role required to manage members'}), 403

    member = ProjectMember.query.filter_by(
        project_id=project_id, user_id=user_id
    ).first_or_404()
    data = request.get_json(silent=True) or {}

    project_role = (data.get('project_role') or '').strip()
    if not project_role:
        return jsonify({'error': 'project_role is required'}), 400
    if project_role not in PROJECT_ROLES:
        return jsonify({'error': f'project_role must be one of: {", ".join(PROJECT_ROLES)}'}), 400

    member.project_role = project_role
    db.session.commit()
    return jsonify(member.to_dict())


@api_bp.route('/projects/<int:project_id>/members/<int:user_id>', methods=['DELETE'])
@login_required
def remove_member(project_id, user_id):
    Project.query.get_or_404(project_id)

    if not _can_manage_members(project_id):
        return jsonify({'error': 'Project Admin or Admin role required to manage members'}), 403

    member = ProjectMember.query.filter_by(
        project_id=project_id, user_id=user_id
    ).first_or_404()

    removed_user = User.query.get(user_id)
    audit_service.log('project.member_remove', 'project', project_id, '',
                      {'user': removed_user.email if removed_user else str(user_id)})
    db.session.delete(member)
    db.session.commit()
    return jsonify({'deleted': True})


# ---------------------------------------------------------------------------
# Domain Checkout / Release
# ---------------------------------------------------------------------------

@api_bp.route('/projects/<int:project_id>/domains', methods=['GET'])
@login_required
@project_member_required()
def list_project_domains(project_id):
    domains = Domain.query.filter_by(checkout_project_id=project_id).order_by(Domain.name).all()
    return jsonify([d.to_dict() for d in domains])


@api_bp.route('/projects/<int:project_id>/domains/<int:domain_id>/checkout', methods=['POST'])
@login_required
@project_member_required(write=True)
def checkout_domain(project_id, domain_id):
    from flask import g
    project = g.project
    if project.status == 'archived':
        return jsonify({'error': 'Cannot check out domains to an archived project'}), 409

    # SELECT FOR UPDATE prevents race conditions
    domain = Domain.query.with_for_update().get(domain_id)

    # If the domain record doesn't exist locally yet, auto-create it from the
    # request body. This allows operators to check out CF zones that haven't
    # been imported by an admin yet (the frontend passes name/cloudflare_zone_id).
    if domain is None:
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip().lower()
        zone_id = (data.get('cloudflare_zone_id') or '').strip()
        if not name:
            return jsonify({'error': 'Domain not found and no name provided to create it'}), 404
        # Avoid duplicate by name
        domain = Domain.query.filter_by(name=name).first()
        if domain is None:
            domain = Domain(
                name=name,
                cloudflare_zone_id=zone_id or None,
                status='active',
                credential_label=data.get('credential_label', 'default') or 'default',
                provider=data.get('provider', 'cloudflare') or 'cloudflare',
            )
            db.session.add(domain)
            db.session.flush()  # get domain.id without committing yet

    if domain.checkout_project_id is not None:
        conflict_project = Project.query.get(domain.checkout_project_id)
        conflict_code = conflict_project.code if conflict_project else '?'
        return jsonify({
            'error': f'Domain is already checked out to project {conflict_code}',
            'checkout_project_id': domain.checkout_project_id,
        }), 409

    # Fix credential_label if still 'default' but the caller knows the real account
    data = request.get_json(silent=True) or {}
    req_label = data.get('credential_label') or ''
    if req_label and domain.credential_label == 'default' and req_label != 'default':
        domain.credential_label = req_label

    domain.checkout_project_id = project_id
    domain.checked_out_at = datetime.utcnow()
    domain.checked_out_by_id = current_user.id
    db.session.commit()

    _log.info('User %s checked out domain %s to project %s',
              current_user.email, domain.name, project.code)
    audit_service.log('domain.checkout', 'domain', domain.id, domain.name,
                      {'project': project.code, 'project_id': project_id})
    return jsonify(domain.to_dict())


@api_bp.route('/projects/<int:project_id>/domains/<int:domain_id>/release', methods=['POST'])
@login_required
@project_member_required(write=True)
def release_domain(project_id, domain_id):
    domain = Domain.query.get_or_404(domain_id)

    if domain.checkout_project_id != project_id:
        return jsonify({'error': 'Domain is not checked out to this project'}), 409

    domain.checkout_project_id = None
    domain.checked_out_at = None
    domain.checked_out_by_id = None
    db.session.commit()

    _log.info('User %s released domain %s from project %s',
              current_user.email, domain.name, project_id)
    audit_service.log('domain.release', 'domain', domain.id, domain.name,
                      {'project_id': project_id})
    return jsonify(domain.to_dict())


@api_bp.route('/admin/domains/<int:domain_id>/force-release', methods=['POST'])
@login_required
@admin_required
def force_release_domain(domain_id):
    domain = Domain.query.get_or_404(domain_id)

    if domain.checkout_project_id is None:
        return jsonify({'error': 'Domain is not checked out'}), 409

    prev_project_id = domain.checkout_project_id
    prev_project = Project.query.get(prev_project_id)
    domain.checkout_project_id = None
    domain.checked_out_at = None
    domain.checked_out_by_id = None
    db.session.commit()

    _log.warning('Admin %s force-released domain %s from project %s',
                 current_user.email, domain.name,
                 prev_project.code if prev_project else prev_project_id)
    audit_service.log('domain.force_release', 'domain', domain.id, domain.name,
                      {'prev_project': prev_project.code if prev_project else str(prev_project_id)})
    return jsonify(domain.to_dict())


# ---------------------------------------------------------------------------
# Domain Readiness Checklist
# ---------------------------------------------------------------------------

@api_bp.route('/projects/<int:project_id>/domains/<int:domain_id>/readiness', methods=['GET'])
@login_required
@project_member_required()
def domain_readiness(project_id, domain_id):
    domain = Domain.query.get_or_404(domain_id)
    if domain.checkout_project_id != project_id:
        return jsonify({'error': 'Domain is not checked out to this project'}), 404
    from app.services.readiness_service import check_domain_readiness
    result = check_domain_readiness(domain)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Teardown Preview
# ---------------------------------------------------------------------------

@api_bp.route('/projects/<int:project_id>/teardown/preview', methods=['GET'])
@login_required
@project_member_required(write=True)
def teardown_preview(project_id):
    """Return a structured preview of all resources that would be cleaned up
    during a project teardown. External service errors are non-fatal and
    collected into the 'warnings' list rather than aborting."""
    warnings = []
    resources = get_resources_by_project(project_id)

    by_type = {}
    for r in resources:
        by_type.setdefault(r.resource_type, []).append(r)

    result = {
        'cs_listeners': [],
        'npm_hosts': [],
        'containers': [],
        'website_gen_sites': [],
        'gophish_senders': [],
        'mailgun_domains': [],
        'cdn_distributions': [],
        'dns_records': {},
        'domains': [],
        'warnings': [],
    }

    # ── CS Listeners ─────────────────────────────────────────────────────────
    for r in by_type.get('cs_listener', []):
        entry = {'name': r.external_id, 'label': r.label, 'project_resource_id': r.id}
        try:
            from app.services import cobaltstrike_service
            details = cobaltstrike_service.get_listener(r.external_id)
            if details:
                entry['type'] = details.get('type', '')
        except Exception as exc:
            warnings.append(f'CS listener {r.external_id}: {exc}')
        result['cs_listeners'].append(entry)

    # ── NPM Proxy Hosts ──────────────────────────────────────────────────────
    # Collect checked-out domain names for domain-based NPM discovery
    checked_out_domains = Domain.query.filter_by(checkout_project_id=project_id).all()
    checked_out_names = {d.name.lower() for d in checked_out_domains}

    npm_host_map = {}
    try:
        from app.services import npm_service
        npm_host_map = {str(h['id']): h for h in (npm_service.list_proxy_hosts() or [])}
    except Exception as exc:
        warnings.append(f'NPM hosts: {exc}')

    # Start with explicitly tagged NPM hosts
    seen_npm_ids = set()
    for r in by_type.get('npm_host', []):
        seen_npm_ids.add(r.external_id)
        h = npm_host_map.get(r.external_id)
        domain_display = (h.get('domain_names') or [''])[0] if h else (r.label or r.external_id)
        result['npm_hosts'].append({
            'id': r.external_id,
            'label': r.label,
            'domain': domain_display,
            'project_resource_id': r.id,
        })

    # Also discover untagged NPM hosts whose domain_names match a
    # checked-out domain (exact match or subdomain of it)
    if checked_out_names and npm_host_map:
        for hid, h in npm_host_map.items():
            if hid in seen_npm_ids:
                continue
            for dn in (h.get('domain_names') or []):
                dn_lower = dn.lower()
                if any(dn_lower == co or dn_lower.endswith('.' + co)
                       for co in checked_out_names):
                    result['npm_hosts'].append({
                        'id': hid,
                        'label': None,
                        'domain': dn,
                        'project_resource_id': None,
                    })
                    seen_npm_ids.add(hid)
                    break

    # ── Containers + Website Gen Sites ────────────────────────────────────────
    deployed_site_map = {}
    if by_type.get('container'):
        try:
            from app.services import website_generator_service
            deployed_site_map = {
                s['folder']: s
                for s in (website_generator_service.get_deployed_sites() or [])
            }
        except Exception as exc:
            warnings.append(f'Deployed sites: {exc}')
    for r in by_type.get('container', []):
        if r.external_id in deployed_site_map:
            site = deployed_site_map[r.external_id]
            npm_id = site.get('npm_host_id')
            result['website_gen_sites'].append({
                'folder': r.external_id,
                'label': r.label,
                'domain': site.get('fqdn', ''),
                'npm_host_id': str(npm_id) if npm_id is not None else None,
                'project_resource_id': r.id,
            })
        else:
            result['containers'].append({
                'name': r.external_id,
                'label': r.label,
                'project_resource_id': r.id,
            })

    # ── GoPhish Senders ──────────────────────────────────────────────────────
    seen_gophish_ids = set()
    for r in by_type.get('gophish_sender', []):
        seen_gophish_ids.add(r.external_id)
        entry = {
            'id': r.external_id,
            'name': r.label or r.external_id,
            'smtp_username': '',
            'smtp_host': '',
            'project_resource_id': r.id,
        }
        try:
            from app.services import gophish_service
            profile = gophish_service.get_sending_profile(r.external_id)
            if profile:
                entry['name'] = profile.get('name', entry['name'])
                entry['smtp_username'] = profile.get('username', '')
                entry['smtp_host'] = profile.get('host', '')
        except Exception as exc:
            warnings.append(f'GoPhish profile {r.external_id}: {exc}')
        result['gophish_senders'].append(entry)

    # Discover untagged GoPhish profiles whose SMTP username domain
    # matches a checked-out domain
    if checked_out_names:
        try:
            from app.services import gophish_service
            all_profiles = gophish_service.list_sending_profiles() or []
            for profile in all_profiles:
                pid_str = str(profile.get('id', ''))
                if pid_str in seen_gophish_ids:
                    continue
                username = profile.get('username', '') or ''
                at_idx = username.rfind('@')
                if at_idx > 0:
                    smtp_domain = username[at_idx + 1:].lower()
                    if smtp_domain in checked_out_names:
                        seen_gophish_ids.add(pid_str)
                        result['gophish_senders'].append({
                            'id': pid_str,
                            'name': profile.get('name', pid_str),
                            'smtp_username': username,
                            'smtp_host': profile.get('host', ''),
                            'project_resource_id': None,
                        })
        except Exception as exc:
            warnings.append(f'GoPhish discovery: {exc}')

    # ── Mailgun Domains ──────────────────────────────────────────────────────
    seen_mg_names = set()
    for r in by_type.get('mailgun_domain', []):
        seen_mg_names.add(r.external_id.lower())
        domain_rec = Domain.query.filter_by(name=r.external_id).first()
        region = domain_rec.mailgun_region if (domain_rec and domain_rec.mailgun_region) else 'us'
        result['mailgun_domains'].append({
            'name': r.external_id,
            'region': region,
            'project_resource_id': r.id,
        })

    # Discover untagged Mailgun domains that match a checked-out domain
    if checked_out_names:
        try:
            from app.services import email_service
            all_mg_domains = email_service.list_domains() or []
            for mg in all_mg_domains:
                mg_name = (mg.get('name') or '').lower()
                if mg_name in seen_mg_names:
                    continue
                if mg_name in checked_out_names:
                    seen_mg_names.add(mg_name)
                    domain_rec = Domain.query.filter_by(name=mg_name).first()
                    region = mg.get('region', 'US').lower() if mg.get('region') else (
                        domain_rec.mailgun_region if (domain_rec and domain_rec.mailgun_region) else 'us'
                    )
                    result['mailgun_domains'].append({
                        'name': mg.get('name', mg_name),
                        'region': region,
                        'project_resource_id': None,
                    })
        except Exception as exc:
            warnings.append(f'Mailgun discovery: {exc}')

    # ── CDN Distributions ────────────────────────────────────────────────────
    seen_cdn_ids = set()
    for r in by_type.get('cdn_dist', []):
        seen_cdn_ids.add(r.external_id)
        result['cdn_distributions'].append({
            'id': r.external_id,
            'label': r.label,
            'project_resource_id': r.id,
        })

    # Discover untagged CDN distributions whose origin_host matches a
    # checked-out domain or whose comment matches a tagged CS listener
    if checked_out_names or by_type.get('cs_listener'):
        cs_listener_names = {r.external_id for r in by_type.get('cs_listener', [])}
        try:
            all_cdns = CdnDistribution.query.all()
            for cdn in all_cdns:
                cdn_id_str = str(cdn.id)
                if cdn_id_str in seen_cdn_ids:
                    continue
                origin = (cdn.origin_host or '').lower()
                comment = cdn.comment or ''
                if ((origin and origin in checked_out_names)
                        or (comment and comment in cs_listener_names)):
                    seen_cdn_ids.add(cdn_id_str)
                    result['cdn_distributions'].append({
                        'id': cdn_id_str,
                        'label': cdn.comment or cdn.domain or cdn_id_str,
                        'project_resource_id': None,
                    })
        except Exception as exc:
            warnings.append(f'CDN discovery: {exc}')

    # ── Checked-out Domains + DNS Records ─────────────────────────────────────
    domains = sorted(checked_out_domains, key=lambda d: d.name)
    for domain in domains:
        result['domains'].append({
            'id': domain.id,
            'name': domain.name,
            'zone_id': domain.cloudflare_zone_id,
        })
        if not domain.cloudflare_zone_id:
            continue
        try:
            from app.services import dns_service
            from app.models.domain import DNSRecord
            records = dns_service.list_dns_records(
                domain.cloudflare_zone_id, label=domain.credential_label or 'default'
            )
            local_managed_by = {
                lr.cloudflare_record_id: lr.managed_by
                for lr in DNSRecord.query.filter_by(domain_id=domain.id).all()
            }
            managed, manual = [], []
            for rec in (records or []):
                if rec.get('type') in ('NS', 'SOA'):
                    continue
                rec_id = rec.get('id', '')
                rec_managed_by = local_managed_by.get(rec_id, 'manual')
                entry = {
                    'id': rec_id,
                    'type': rec.get('type', ''),
                    'name': rec.get('name', ''),
                    'content': rec.get('content', ''),
                    'managed_by': rec_managed_by,
                }
                if rec_managed_by in ('infrared', 'mailgun'):
                    managed.append(entry)
                else:
                    manual.append(entry)
            result['dns_records'][domain.name] = {
                'zone_id': domain.cloudflare_zone_id,
                'domain_id': domain.id,
                'credential_label': domain.credential_label or 'default',
                'managed': managed,
                'manual': manual,
            }
        except Exception as exc:
            warnings.append(f'DNS records for {domain.name}: {exc}')
            result['dns_records'][domain.name] = {
                'zone_id': domain.cloudflare_zone_id,
                'domain_id': domain.id,
                'credential_label': domain.credential_label or 'default',
                'managed': [],
                'manual': [],
            }

    result['warnings'] = warnings
    return jsonify(result)


# ---------------------------------------------------------------------------
# Project Resources (tagging non-domain infra)
# ---------------------------------------------------------------------------

@api_bp.route('/projects/<int:project_id>/resources', methods=['GET'])
@login_required
@project_member_required()
def list_resources(project_id):
    resource_type = request.args.get('type')
    resources = get_resources_by_project(project_id, resource_type)
    return jsonify([r.to_dict() for r in resources])


@api_bp.route('/projects/<int:project_id>/resources', methods=['POST'])
@login_required
@project_member_required(write=True)
def tag_resource(project_id):
    data = request.get_json(silent=True) or {}

    resource_type = (data.get('resource_type') or '').strip()
    external_id = (data.get('external_id') or '').strip()
    label = (data.get('label') or '').strip() or None

    if not resource_type:
        return jsonify({'error': 'resource_type is required'}), 400
    if resource_type not in RESOURCE_TYPES:
        return jsonify({'error': f'resource_type must be one of: {", ".join(RESOURCE_TYPES)}'}), 400
    if not external_id:
        return jsonify({'error': 'external_id is required'}), 400

    existing = ProjectResource.query.filter_by(
        project_id=project_id,
        resource_type=resource_type,
        external_id=external_id,
    ).first()
    if existing:
        return jsonify({'error': 'Resource is already tagged to this project'}), 409

    resource = ProjectResource(
        project_id=project_id,
        resource_type=resource_type,
        external_id=external_id,
        label=label,
        tagged_by_id=current_user.id,
    )
    db.session.add(resource)
    db.session.commit()

    _log.info('User %s tagged %s:%s to project %s',
              current_user.email, resource_type, external_id, project_id)
    return jsonify(resource.to_dict()), 201


@api_bp.route('/projects/<int:project_id>/resources/<int:resource_id>', methods=['DELETE'])
@login_required
@project_member_required(write=True)
def untag_resource(project_id, resource_id):
    resource = ProjectResource.query.filter_by(
        id=resource_id, project_id=project_id
    ).first_or_404()

    _log.info('User %s untagged %s:%s from project %s',
              current_user.email, resource.resource_type, resource.external_id, project_id)
    db.session.delete(resource)
    db.session.commit()
    return jsonify({'deleted': True})


# ---------------------------------------------------------------------------
# Active Project (session)
# ---------------------------------------------------------------------------

@api_bp.route('/projects/active', methods=['GET'])
@login_required
def get_active():
    project = get_active_project(current_user)
    if not project:
        return jsonify({'active_project': None})
    return jsonify({'active_project': project.to_dict()})


@api_bp.route('/projects/<int:project_id>/activate', methods=['POST'])
@login_required
def activate_project(project_id):
    project = set_active_project(current_user, project_id)
    return jsonify({'active_project': project.to_dict()})


@api_bp.route('/projects/active', methods=['DELETE'])
@login_required
def deactivate_project():
    clear_active_project()
    return jsonify({'active_project': None})
