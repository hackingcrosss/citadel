from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import email_service
from app.services.project_service import build_project_tag_map, get_active_project, get_project_domain_names


# --- Domains ---

@api_bp.route('/email/domains', methods=['GET'])
@login_required
def list_mailgun_domains():
    try:
        region = request.args.get('region')  # 'us', 'eu', or None for both
        domains = email_service.list_domains(region=region)

        domain_names = [d['name'] for d in domains if d.get('name')]
        tag_map = build_project_tag_map('mailgun_domain', domain_names)
        for d in domains:
            tag = tag_map.get(d.get('name', ''))
            d['project_id'] = tag['project_id'] if tag else None
            d['project_code'] = tag['project_code'] if tag else None
            d['project_resource_id'] = tag['project_resource_id'] if tag else None

        if not current_user.is_admin:
            active_project = get_active_project(current_user)
            if active_project is None:
                domains = []
            else:
                project_domains = get_project_domain_names(active_project.id)
                domains = [d for d in domains if d.get('name', '') in project_domains]

        return jsonify({'domains': domains})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/email/domains', methods=['POST'])
@login_required
def add_mailgun_domain():
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Domain name is required'}), 400

    region = data.get('region', 'us')
    try:
        result = email_service.add_domain(data['name'], region=region)
        return jsonify({'domain': result}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/email/domains/<path:name>', methods=['GET'])
@login_required
def get_mailgun_domain(name):
    region = request.args.get('region', 'us')
    try:
        result = email_service.get_domain(name, region=region)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/email/domains/<path:name>', methods=['DELETE'])
@login_required
def delete_mailgun_domain(name):
    region = request.args.get('region', 'us')
    try:
        email_service.delete_domain(name, region=region)
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/email/domains/<path:name>/verify', methods=['POST'])
@login_required
def verify_mailgun_domain(name):
    data = request.get_json(silent=True) or {}
    region = data.get('region', request.args.get('region', 'us'))
    try:
        result = email_service.verify_domain(name, region=region)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- SMTP Credentials ---

@api_bp.route('/email/domains/<path:name>/credentials', methods=['GET'])
@login_required
def list_smtp_credentials(name):
    region = request.args.get('region', 'us')
    try:
        creds = email_service.list_smtp_credentials(name, region=region)
        return jsonify({'credentials': creds})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/email/domains/<path:name>/credentials', methods=['POST'])
@login_required
def create_smtp_credential(name):
    data = request.get_json()
    if not data or not data.get('login') or not data.get('password'):
        return jsonify({'error': 'Login and password are required'}), 400

    region = data.get('region', 'us')
    try:
        result = email_service.create_smtp_credential(name, data['login'], data['password'], region=region)
        return jsonify(result), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/email/domains/<path:name>/credentials/<login>', methods=['DELETE'])
@login_required
def delete_smtp_credential(name, login):
    region = request.args.get('region', 'us')
    try:
        email_service.delete_smtp_credential(name, login, region=region)
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
