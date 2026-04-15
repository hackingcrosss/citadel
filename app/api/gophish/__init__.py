from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import gophish_service
from app.utils.decorators import feature_required
from app.services.project_service import build_project_tag_map, get_active_project, get_project_domain_names


@api_bp.route('/gophish/profiles', methods=['GET'])
@login_required
@feature_required('gophish')
def list_gophish_profiles():
    try:
        profiles = gophish_service.list_sending_profiles()

        profile_ids = [str(p['id']) for p in profiles if p.get('id') is not None]
        tag_map = build_project_tag_map('gophish_sender', profile_ids)
        for p in profiles:
            tag = tag_map.get(str(p.get('id', '')))
            p['project_id'] = tag['project_id'] if tag else None
            p['project_code'] = tag['project_code'] if tag else None
            p['project_resource_id'] = tag['project_resource_id'] if tag else None

        _auditor_unscoped = current_user.is_auditor and get_active_project(current_user) is None
        if not current_user.is_admin and not _auditor_unscoped:
            active_project = get_active_project(current_user)
            if active_project is None:
                profiles = []
            else:
                project_domains = get_project_domain_names(active_project.id)

                def _domain_matches(addr):
                    """Extract domain from an email address and check against project domains
                    with subdomain suffix support (e.g. mg.example.com matches example.com)."""
                    part = addr.split('@')[-1].strip().rstrip('>').lower() if '@' in addr else ''
                    if not part:
                        return False
                    if part in project_domains:
                        return True
                    return any(part.endswith('.' + pd) for pd in project_domains)

                filtered = []
                for p in profiles:
                    if p.get('project_id') == active_project.id:
                        filtered.append(p)
                    elif _domain_matches(p.get('from_address', '')) or _domain_matches(p.get('username', '')):
                        filtered.append(p)
                profiles = filtered

        return jsonify({'profiles': profiles})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/profiles/<int:profile_id>', methods=['GET'])
@login_required
@feature_required('gophish')
def get_gophish_profile(profile_id):
    try:
        profile = gophish_service.get_sending_profile(profile_id)
        return jsonify({'profile': profile})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/profiles', methods=['POST'])
@login_required
@feature_required('gophish')
def create_gophish_profile():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    required = ['name', 'host', 'from_address', 'username', 'password']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Missing required field: {field}'}), 400

    profile_data = {
        'name': data['name'],
        'host': data['host'],
        'from_address': data['from_address'],
        'username': data['username'],
        'password': data['password'],
        'interface_type': 'SMTP',
        'ignore_cert_errors': data.get('ignore_cert_errors', False),
    }

    try:
        result = gophish_service.create_sending_profile(profile_data)
        return jsonify({'profile': result}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/profiles/<int:profile_id>', methods=['DELETE'])
@login_required
@feature_required('gophish')
def delete_gophish_profile(profile_id):
    try:
        gophish_service.delete_sending_profile(profile_id)
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ---------------------------------------------------------------------------
# Email Templates
# ---------------------------------------------------------------------------

@api_bp.route('/gophish/templates', methods=['GET'])
@login_required
@feature_required('gophish')
def list_gophish_templates():
    try:
        templates = gophish_service.list_templates()
        return jsonify({'templates': templates if isinstance(templates, list) else []})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/templates/<int:template_id>', methods=['GET'])
@login_required
@feature_required('gophish')
def get_gophish_template(template_id):
    try:
        template = gophish_service.get_template(template_id)
        return jsonify({'template': template})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/templates', methods=['POST'])
@login_required
@feature_required('gophish')
def create_gophish_template():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    if not data.get('name'):
        return jsonify({'error': 'Template name is required'}), 400
    if not data.get('html') and not data.get('text'):
        return jsonify({'error': 'Template must have html or text content'}), 400

    template_data = {
        'name': data['name'],
        'subject': data.get('subject', ''),
        'html': data.get('html', ''),
        'text': data.get('text', ''),
    }
    try:
        result = gophish_service.create_template(template_data)
        return jsonify({'template': result}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/templates/<int:template_id>', methods=['PUT'])
@login_required
@feature_required('gophish')
def update_gophish_template(template_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    try:
        existing = gophish_service.get_template(template_id)
        updated = {
            'id': template_id,
            'name': data.get('name', existing.get('name', '')),
            'subject': data.get('subject', existing.get('subject', '')),
            'html': data.get('html', existing.get('html', '')),
            'text': data.get('text', existing.get('text', '')),
        }
        result = gophish_service.update_template(template_id, updated)
        return jsonify({'template': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/templates/<int:template_id>', methods=['DELETE'])
@login_required
@feature_required('gophish')
def delete_gophish_template(template_id):
    try:
        gophish_service.delete_template(template_id)
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/templates/import', methods=['POST'])
@login_required
@feature_required('gophish')
def import_gophish_template():
    data = request.get_json()
    if not data or not data.get('content'):
        return jsonify({'error': 'Raw email content is required'}), 400
    try:
        result = gophish_service.import_email_template({
            'content': data['content'],
            'convert_links': data.get('convert_links', True),
        })
        return jsonify({'template': result}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ---------------------------------------------------------------------------
# User Groups
# ---------------------------------------------------------------------------

@api_bp.route('/gophish/groups', methods=['GET'])
@login_required
@feature_required('gophish')
def list_gophish_groups():
    try:
        groups = gophish_service.list_groups()
        return jsonify({'groups': groups if isinstance(groups, list) else []})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/groups/<int:group_id>', methods=['GET'])
@login_required
@feature_required('gophish')
def get_gophish_group(group_id):
    try:
        group = gophish_service.get_group(group_id)
        return jsonify({'group': group})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/groups/<int:group_id>', methods=['DELETE'])
@login_required
@feature_required('gophish')
def delete_gophish_group(group_id):
    try:
        gophish_service.delete_group(group_id)
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
