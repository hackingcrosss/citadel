from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import credential_service


@api_bp.route('/credentials/<provider>', methods=['GET'])
@login_required
def get_credentials(provider):
    data = credential_service.get_all_for_provider(provider)
    return jsonify({provider: data})


@api_bp.route('/credentials/<provider>', methods=['POST'])
@login_required
def save_credentials(provider):
    payload = request.get_json()
    if not payload:
        return jsonify({'error': 'No data provided'}), 400

    saved = []
    for key_name, value in payload.items():
        if value and value.strip():
            credential_service.set_credential(provider, key_name, value.strip())
            saved.append(key_name)

    return jsonify({'saved': saved, 'provider': provider})


@api_bp.route('/credentials/<provider>/test', methods=['POST'])
@login_required
def test_credentials(provider):
    testers = {
        'cloudflare': _test_cloudflare,
        'mailgun': _test_mailgun,
        'npm': _test_npm,
        'aws': _test_aws,
        'docker': _test_docker,
    }

    tester = testers.get(provider)
    if not tester:
        return jsonify({'error': f'No test available for {provider}'}), 400

    try:
        result = tester()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api_bp.route('/credentials/<provider>/<key_name>', methods=['DELETE'])
@login_required
def delete_credential(provider, key_name):
    deleted = credential_service.delete_credential(provider, key_name)
    if deleted:
        return jsonify({'deleted': True})
    return jsonify({'error': 'Credential not found'}), 404


def _test_cloudflare():
    from app.services import dns_service
    result = dns_service.verify_token()
    return {'status': result.get('status', 'unknown')}


def _test_mailgun():
    from app.services import email_service
    result = email_service.verify_api_key()
    return result


def _test_npm():
    from app.services import npm_service
    result = npm_service.verify_connection()
    return result


def _test_aws():
    from app.services import aws_service
    result = aws_service.verify_credentials()
    return result


def _test_docker():
    from app.services import docker_service
    containers = docker_service.list_containers()
    return {'container_count': len(containers)}
