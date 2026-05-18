from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import cobaltstrike_service
from app.utils.decorators import feature_required
from app.services.project_service import build_project_tag_map, assert_resource_writable, get_active_project, filter_by_active_project, tag_resource, get_project_domain_names
from app.services import audit_service
from app.utils.errors import safe_error

# Valid listener types — these are the exact URL slugs for POST /api/v1/listeners/{type}
VALID_TYPES = {'http', 'https', 'dns', 'smb', 'tcp', 'foreignHttp', 'foreignHttps', 'externalC2', 'userDefinedC2'}

# Required fields per listener type (validated before sending to CS)
TYPE_REQUIRED = {
    'http':           ['name', 'host'],
    'https':          ['name', 'host'],
    'dns':            ['name', 'host'],
    'smb':            ['name', 'pipename'],
    'tcp':            ['name', 'port'],
    'foreignHttp':    ['name', 'host', 'port'],
    'foreignHttps':   ['name', 'host', 'port'],
    'externalC2':     ['name', 'port'],
    'userDefinedC2':  ['name', 'port'],
}


@api_bp.route('/cobaltstrike/listeners', methods=['GET'])
@login_required
@feature_required('cobaltstrike')
def list_cs_listeners():
    label = request.args.get('label', 'default')
    try:
        listeners = cobaltstrike_service.list_listeners(label=label)

        # Enrich listeners with project tag
        names = [l.get('name', '') for l in listeners if l.get('name')]
        tag_map = build_project_tag_map('cs_listener', names)
        for listener in listeners:
            tag = tag_map.get(listener.get('name', ''))
            listener['project_id'] = tag['project_id'] if tag else None
            listener['project_code'] = tag['project_code'] if tag else None
            listener['project_resource_id'] = tag['project_resource_id'] if tag else None

        _auditor_unscoped = current_user.is_auditor and get_active_project(current_user) is None
        if not current_user.is_admin and not _auditor_unscoped:
            active_project = get_active_project(current_user)
            if active_project is None:
                listeners = []
            else:
                from app.models.cdn_distribution import CdnDistribution
                from app.services.project_service import get_project_resource_external_ids
                project_domains = get_project_domain_names(active_project.id)
                # Collect CDN endpoint domains (*.cloudfront.net / *.azurefd.net) for
                # CDN distributions associated with this project
                cdn_dist_ids = get_project_resource_external_ids(active_project.id, 'cdn_dist')
                project_cdn_domains = {
                    cdn.domain for cdn in CdnDistribution.query.filter(
                        CdnDistribution.domain.isnot(None),
                        CdnDistribution.domain != '',
                    ).all()
                    if str(cdn.id) in cdn_dist_ids or cdn.origin_host in project_domains
                }
                all_project_hosts = project_domains | project_cdn_domains
                filtered = []
                for l in listeners:
                    if l.get('project_id') == active_project.id:
                        filtered.append(l)
                    else:
                        hosts = l.get('host', [])
                        if isinstance(hosts, str):
                            hosts = [hosts]
                        if any(h in all_project_hosts for h in hosts):
                            filtered.append(l)
                listeners = filtered

        return jsonify({'listeners': listeners})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/cobaltstrike/listeners/<path:listener_name>', methods=['GET'])
@login_required
@feature_required('cobaltstrike')
def get_cs_listener(listener_name):
    label = request.args.get('label', 'default')
    try:
        listener = cobaltstrike_service.get_listener(listener_name, label=label)
        return jsonify({'listener': listener})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/cobaltstrike/listeners', methods=['POST'])
@login_required
@feature_required('cobaltstrike')
def create_cs_listener():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    label = data.pop('c2_server', None) or data.pop('label', 'default')
    listener_type = data.pop('type', '')
    if not listener_type:
        return jsonify({'error': 'Missing required field: type'}), 400
    if listener_type not in VALID_TYPES:
        return jsonify({'error': f'Unknown listener type: {listener_type}. Valid: {", ".join(sorted(VALID_TYPES))}'}), 400

    required = TYPE_REQUIRED.get(listener_type, ['name'])
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Missing required field for {listener_type}: {field}'}), 400

    # Write guard — creating a listener is a write action
    assert_resource_writable('cs_listener', data.get('name', ''), current_user)

    try:
        result = cobaltstrike_service.create_listener(listener_type, data, label=label)
        # Auto-tag to active project if one is set
        listener_name = result.get('name') or data.get('name', '')
        if listener_name:
            active_project = get_active_project(current_user)
            if active_project:
                try:
                    tag_resource(active_project.id, 'cs_listener', listener_name, listener_name, current_user.id)
                except Exception:
                    pass  # tagging failure must never block the create response
        audit_service.log('cs_listener.create', 'cs_listener', listener_name, listener_name,
                          {'type': listener_type, 'hosts': data.get('host') or data.get('hosts')})
        return jsonify({'listener': result}), 201
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/cobaltstrike/listeners/<path:listener_name>/hosts', methods=['PATCH'])
@login_required
@feature_required('cobaltstrike')
def update_cs_listener_hosts(listener_name):
    """Update a listener's callback hosts (delete + recreate under the hood)."""
    assert_resource_writable('cs_listener', listener_name, current_user)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    label = data.get('label', 'default')
    hosts = data.get('hosts')
    if not isinstance(hosts, list) or not hosts:
        return jsonify({'error': 'hosts must be a non-empty list of strings'}), 400

    # Validate each host is a non-empty string
    hosts = [h.strip() for h in hosts if isinstance(h, str) and h.strip()]
    if not hosts:
        return jsonify({'error': 'hosts must contain at least one valid hostname'}), 400

    try:
        result = cobaltstrike_service.update_listener_hosts(listener_name, hosts, label=label)
        audit_service.log('cs_listener.update_hosts', 'cs_listener', listener_name, listener_name,
                          {'hosts': hosts})
        return jsonify({'listener': result})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/cobaltstrike/listeners/<path:listener_name>', methods=['DELETE'])
@login_required
@feature_required('cobaltstrike')
def delete_cs_listener(listener_name):
    assert_resource_writable('cs_listener', listener_name, current_user)
    label = request.args.get('label', 'default')
    try:
        cobaltstrike_service.delete_listener(listener_name, label=label)
        audit_service.log('cs_listener.delete', 'cs_listener', listener_name, listener_name)
        return jsonify({'deleted': True})
    except Exception as e:
        return safe_error(e, 400)


# ---------------------------------------------------------------------------
# C2 server listing (for operations page selector)
# ---------------------------------------------------------------------------

@api_bp.route('/cobaltstrike/servers', methods=['GET'])
@login_required
@feature_required('cobaltstrike')
def list_c2_servers():
    """Return configured C2 server labels with their type and IPs."""
    # G-04: listener_ip / redirector_ip are C2 infra IPs. Operators legitimately
    # use this for deploying infrastructure; auditors / white_team / project_admin
    # have no operational need and shouldn't see C2 callback IPs.
    if not current_user.can_write_infra:
        return jsonify({'error': 'Operator access required'}), 403
    from app.services.credential_service import get_all_for_provider, get_credential
    data = get_all_for_provider('cobaltstrike')
    servers = []
    for label, keys in sorted(data.items()):
        c2_type = get_credential('cobaltstrike', 'c2_type', label=label) or 'cobaltstrike'
        listener_ip = get_credential('cobaltstrike', 'listener_ip', label=label) or ''
        redirector_ip = get_credential('cobaltstrike', 'redirector_ip', label=label) or ''
        has_profile = bool(get_credential('cobaltstrike', 'malleable_profile', label=label))
        tls_raw = get_credential('cobaltstrike', 'tls_verify', label=label)
        tls_verify = tls_raw is None or tls_raw.strip().lower() not in ('0', 'false', 'no', 'off')
        api_url_info = keys.get('api_url', {})
        servers.append({
            'label': label,
            'c2_type': c2_type,
            'listener_ip': listener_ip,
            'redirector_ip': redirector_ip,
            'has_profile': has_profile,
            'tls_verify': tls_verify,
            'configured': bool(api_url_info),
            'api_url_masked': api_url_info.get('masked', ''),
        })
    return jsonify({'servers': servers})


# ---------------------------------------------------------------------------
# Malleable C2 profile parser — generate Nginx restrictor config
# ---------------------------------------------------------------------------

@api_bp.route('/cobaltstrike/parse-profile', methods=['POST'])
@login_required
@feature_required('cobaltstrike')
def parse_malleable_profile():
    """Parse a Malleable C2 profile and return extracted indicators + Nginx config."""
    data = request.get_json(silent=True) or {}
    profile_text = data.get('profile', '').strip()
    if not profile_text:
        return jsonify({'error': 'No profile text provided'}), 400

    try:
        from app.services.malleable_c2_parser import parse_profile, generate_nginx_config
        parsed = parse_profile(profile_text)
        backend = data.get('backend', '$forward_scheme://$server:$port')
        # D-02: validate backend against injection
        from app.utils.url_validation import is_safe_nginx_backend
        if not is_safe_nginx_backend(backend):
            return jsonify({'error': 'Invalid backend value — must not contain newlines, quotes, semicolons, or braces'}), 400
        nginx_config = generate_nginx_config(parsed, backend=backend)
        return jsonify({
            'parsed': parsed,
            'nginx_config': nginx_config,
        })
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/cobaltstrike/nginx-config', methods=['GET'])
@login_required
@feature_required('cobaltstrike')
def get_stored_nginx_config():
    """Generate Nginx restrictor config from the stored Malleable C2 profile."""
    from app.services.credential_service import get_credential
    from app.services.malleable_c2_parser import parse_profile, generate_nginx_config

    label = request.args.get('label', 'default')
    profile_text = get_credential('cobaltstrike', 'malleable_profile', label=label)
    if not profile_text:
        return jsonify({'error': 'No Malleable C2 profile stored. Upload one in Settings.', 'nginx_config': ''}), 404

    try:
        parsed = parse_profile(profile_text)
        nginx_config = generate_nginx_config(parsed)
        return jsonify({
            'nginx_config': nginx_config,
            'has_profile': True,
        })
    except Exception as e:
        return safe_error(e, 400, nginx_config='')
