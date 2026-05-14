import re
from flask import request, jsonify, abort
from flask_login import login_required, current_user
from app.api import api_bp
from app.utils.decorators import feature_required
from app.services.project_service import get_active_project, get_project_domain_names
from app.utils.errors import safe_error


def _require_can_write_infra():
    """Abort 403 if the current user can't write infrastructure. Operators
    and admins legitimately deploy websites; auditors, white_team, and
    project_admin do not. There's no dedicated decorator for this, so the
    handlers call this helper inline."""
    if not current_user.can_write_infra:
        abort(403)

# Cloudflare zone IDs are 32-char hex strings
_ZONE_ID_RE = re.compile(r'^[a-f0-9]{32}$')
# DNS label: up to 63 chars, alphanumeric + hyphens, no leading/trailing hyphen
_LABEL_RE = re.compile(r'^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$')
# FQDN (used for domain and zone_name)
_DOMAIN_RE = re.compile(r'^(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$')
# Deployed site folder names (lowercase alphanum, hyphens, underscores)
_FOLDER_RE = re.compile(r'^[a-z0-9][a-z0-9_\-]{0,63}$')


@api_bp.route('/website-generator/generate', methods=['POST'])
@login_required
@feature_required('website_generator')
def website_generator_generate():
    _require_can_write_infra()
    data = request.get_json() or {}
    category = data.get('category', '').strip()
    if not category:
        return jsonify({'error': 'category is required'}), 400

    domain = data.get('domain', '').strip() or None
    subdomain = data.get('subdomain', '').strip() or ''
    zone_id = data.get('zone_id', '').strip() or ''
    zone_name = data.get('zone_name', '').strip() or ''
    extra_context = data.get('extra_context', '').strip() or None

    if zone_id and not _ZONE_ID_RE.match(zone_id):
        return jsonify({'error': 'Invalid zone_id format'}), 400
    if zone_name and not _DOMAIN_RE.match(zone_name):
        return jsonify({'error': 'Invalid zone_name format'}), 400
    if domain and not _DOMAIN_RE.match(domain):
        return jsonify({'error': 'Invalid domain format'}), 400
    if subdomain and not _LABEL_RE.match(subdomain):
        return jsonify({'error': 'Invalid subdomain format'}), 400

    from app.tasks.website_generator_tasks import generate_website_task
    from app.services import task_log_service
    task = generate_website_task.delay(category, domain=domain, extra_context=extra_context)
    task_log_service.log_task(task.id, 'website_generation', category,
                              meta={'subdomain': subdomain, 'domain': domain or '',
                                    'zone_id': zone_id, 'zone_name': zone_name})
    return jsonify({'task_id': task.id})


@api_bp.route('/website-generator/status/<task_id>', methods=['GET'])
@login_required
@feature_required('website_generator')
def website_generator_status(task_id):
    from app.tasks.celery_app import celery
    result = celery.AsyncResult(task_id)

    response = {'task_id': task_id, 'status': result.status}
    if result.status == 'SUCCESS':
        response['result'] = result.result
    elif result.status == 'FAILURE':
        response['error'] = str(result.result)
    return jsonify(response)


@api_bp.route('/website-generator/deploy', methods=['POST'])
@login_required
@feature_required('website_generator')
def website_generator_deploy():
    _require_can_write_infra()
    data = request.get_json() or {}
    html = data.get('html', '').strip()
    category = data.get('category', '').strip()
    if not html:
        return jsonify({'error': 'html is required'}), 400
    if not category:
        return jsonify({'error': 'category is required'}), 400

    try:
        from app.services import website_generator_service
        result = website_generator_service.deploy_website(html, category)
        return jsonify(result)
    except Exception as e:
        return safe_error(e, 500)


@api_bp.route('/website-generator/relaunch', methods=['POST'])
@login_required
@feature_required('website_generator')
def website_generator_relaunch():
    _require_can_write_infra()
    try:
        from app.services import website_generator_service
        result = website_generator_service.relaunch_containers()
        return jsonify(result)
    except Exception as e:
        return safe_error(e, 500)


@api_bp.route('/website-generator/publish', methods=['POST'])
@login_required
@feature_required('website_generator')
def website_generator_publish():
    _require_can_write_infra()
    data = request.get_json() or {}
    html = data.get('html', '').strip()
    category = data.get('category', '').strip()
    zone_id = data.get('zone_id', '').strip()
    zone_name = data.get('zone_name', '').strip()
    subdomain = data.get('subdomain', '').strip()

    if not html:
        return jsonify({'error': 'html is required'}), 400
    if not category:
        return jsonify({'error': 'category is required'}), 400
    if not zone_id or not zone_name:
        return jsonify({'error': 'zone_id and zone_name are required'}), 400
    if not _ZONE_ID_RE.match(zone_id):
        return jsonify({'error': 'Invalid zone_id format'}), 400
    if not _DOMAIN_RE.match(zone_name):
        return jsonify({'error': 'Invalid zone_name format'}), 400
    if subdomain and not _LABEL_RE.match(subdomain):
        return jsonify({'error': 'Invalid subdomain format'}), 400

    try:
        from app.services import website_generator_service
        result = website_generator_service.publish_website(
            html=html,
            category=category,
            zone_id=zone_id,
            zone_name=zone_name,
            subdomain=subdomain,
        )
        return jsonify(result)
    except Exception as e:
        return safe_error(e, 500)


@api_bp.route('/website-generator/deployed-sites', methods=['GET'])
@login_required
@feature_required('website_generator')
def get_deployed_sites():
    """Return sites discovered from docker-compose + NPM proxy host matching."""
    try:
        from app.services import website_generator_service
        sites = website_generator_service.get_deployed_sites()

        # Scope to active project's domains
        _auditor_unscoped = current_user.is_auditor and get_active_project(current_user) is None
        if not current_user.is_admin and not _auditor_unscoped:
            active_project = get_active_project(current_user)
            if active_project is None:
                sites = []
            else:
                project_domains = get_project_domain_names(active_project.id)
                sites = [s for s in sites if _fqdn_matches_domains(s.get('fqdn', ''), project_domains)]

        return jsonify({'sites': sites})
    except Exception as e:
        return safe_error(e, 500, sites=[])


def _fqdn_matches_domains(fqdn, domain_set):
    """Check if an FQDN belongs to any domain in the set (exact or subdomain match)."""
    if not fqdn:
        return False
    fqdn = fqdn.lower().rstrip('.')
    if fqdn in domain_set:
        return True
    # Check if it's a subdomain of any project domain
    for d in domain_set:
        if fqdn.endswith('.' + d):
            return True
    return False


@api_bp.route('/website-generator/deployed-sites/<folder_name>', methods=['DELETE'])
@login_required
@feature_required('website_generator')
def delete_deployed_site(folder_name):
    """Stop the container and remove its service from docker-compose.yaml."""
    _require_can_write_infra()
    if not _FOLDER_RE.match(folder_name):
        return jsonify({'error': 'Invalid folder name'}), 400
    try:
        from app.services import website_generator_service
        result = website_generator_service.remove_deployed_site(folder_name)
        return jsonify({'ok': True, **result})
    except Exception as e:
        return safe_error(e, 500)
