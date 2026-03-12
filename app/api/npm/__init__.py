from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import npm_service
from app.services.project_service import build_project_tag_map, assert_resource_writable, get_active_project, get_project_domain_names
from app.services import audit_service


# --- Proxy Hosts ---

@api_bp.route('/npm/hosts', methods=['GET'])
@login_required
def list_proxy_hosts():
    try:
        hosts = npm_service.list_proxy_hosts()

        # Enrich hosts with project tag (NPM host IDs are integers; store as strings)
        host_ids = [str(h['id']) for h in hosts if h.get('id') is not None]
        tag_map = build_project_tag_map('npm_host', host_ids)
        for h in hosts:
            tag = tag_map.get(str(h.get('id', '')))
            h['project_id'] = tag['project_id'] if tag else None
            h['project_code'] = tag['project_code'] if tag else None
            h['project_resource_id'] = tag['project_resource_id'] if tag else None

        if not current_user.is_admin:
            active_project = get_active_project(current_user)
            if active_project is None:
                hosts = []
            else:
                project_domains = get_project_domain_names(active_project.id)
                filtered = []
                for h in hosts:
                    if h.get('project_id') == active_project.id:
                        filtered.append(h)
                    else:
                        host_domains = h.get('domain_names') or []
                        if any(dn == d or dn.endswith('.' + d) for dn in host_domains for d in project_domains):
                            filtered.append(h)
                hosts = filtered

        return jsonify({'hosts': hosts})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/npm/hosts', methods=['POST'])
@login_required
def create_proxy_host():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    for field in ('domain_names', 'forward_host', 'forward_port'):
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    try:
        host = npm_service.create_proxy_host(
            domain_names=data['domain_names'],
            forward_host=data['forward_host'],
            forward_port=data['forward_port'],
            forward_scheme=data.get('forward_scheme', 'http'),
            ssl_forced=data.get('ssl_forced', False),
            block_exploits=data.get('block_exploits', True),
            allow_websocket_upgrade=data.get('allow_websocket_upgrade', False),
            advanced_config=data.get('advanced_config', ''),
        )
        names = ', '.join(data.get('domain_names', []))
        audit_service.log('npm_proxy.create', 'npm_proxy', host.get('id', ''), names,
                          {'domain_names': data['domain_names'],
                           'forward': f"{data.get('forward_scheme','http')}://{data['forward_host']}:{data['forward_port']}"})
        return jsonify({'host': host}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/npm/hosts/<int:host_id>', methods=['GET'])
@login_required
def get_proxy_host(host_id):
    try:
        host = npm_service.get_proxy_host(host_id)
        return jsonify({'host': host})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/npm/hosts/<int:host_id>', methods=['PUT'])
@login_required
def update_proxy_host(host_id):
    assert_resource_writable('npm_host', str(host_id), current_user)
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    _ALLOWED_UPDATE_FIELDS = {
        'domain_names', 'forward_host', 'forward_port', 'forward_scheme',
        'ssl_forced', 'block_exploits', 'allow_websocket_upgrade',
        'access_list_id', 'certificate_id', 'http2_support',
        'hsts_enabled', 'hsts_subdomains', 'locations', 'advanced_config',
    }
    kwargs = {k: v for k, v in data.items() if k in _ALLOWED_UPDATE_FIELDS}

    try:
        host = npm_service.update_proxy_host(host_id, **kwargs)
        return jsonify({'host': host})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/npm/hosts/<int:host_id>', methods=['DELETE'])
@login_required
def delete_proxy_host(host_id):
    assert_resource_writable('npm_host', str(host_id), current_user)
    try:
        npm_service.delete_proxy_host(host_id)
        audit_service.log('npm_proxy.delete', 'npm_proxy', host_id, str(host_id))
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/npm/hosts/<int:host_id>/enable', methods=['POST'])
@login_required
def enable_proxy_host(host_id):
    assert_resource_writable('npm_host', str(host_id), current_user)
    try:
        npm_service.enable_proxy_host(host_id)
        return jsonify({'enabled': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/npm/hosts/<int:host_id>/disable', methods=['POST'])
@login_required
def disable_proxy_host(host_id):
    assert_resource_writable('npm_host', str(host_id), current_user)
    try:
        npm_service.disable_proxy_host(host_id)
        return jsonify({'disabled': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Access Lists ---

@api_bp.route('/npm/access-lists', methods=['GET'])
@login_required
def list_access_lists():
    try:
        lists = npm_service.list_access_lists()
        return jsonify({'access_lists': lists})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Certificates ---

@api_bp.route('/npm/certificates', methods=['GET'])
@login_required
def list_certificates():
    try:
        certs = npm_service.list_certificates()
        return jsonify({'certificates': certs})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Redirection Hosts ---

@api_bp.route('/npm/redirections', methods=['GET'])
@login_required
def list_redirections():
    try:
        redirections = npm_service.list_redirection_hosts()
        return jsonify({'redirections': redirections})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Auth Token ---

@api_bp.route('/npm/token', methods=['POST'])
@login_required
def get_npm_token():
    """Authenticate with NPM using email/password and store the resulting token."""
    data = request.get_json()
    if not data or not data.get('identity') or not data.get('secret'):
        return jsonify({'error': 'Email and password are required'}), 400

    try:
        from app.services import credential_service
        token = npm_service.get_token(data['identity'], data['secret'])
        if token:
            credential_service.set_credential('npm', 'api_token', token)
            return jsonify({'success': True, 'message': 'Token saved'})
        return jsonify({'error': 'No token returned'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400
