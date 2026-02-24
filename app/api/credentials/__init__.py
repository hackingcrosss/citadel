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
        'gophish': _test_gophish,
        'cobaltstrike': _test_cobaltstrike,
        'openai': _test_openai,
    }

    tester = testers.get(provider)
    if not tester:
        return jsonify({'error': f'No test available for {provider}'}), 400

    try:
        result = tester()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@api_bp.route('/credentials/<provider>/<key_name>', methods=['GET'])
@login_required
def get_single_credential(provider, key_name):
    """Get a single credential value (unmasked). Used for non-secret config like NPM public IP."""
    value = credential_service.get_credential(provider, key_name)
    if value is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'provider': provider, 'key': key_name, 'value': value})


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


def _test_gophish():
    from app.services import gophish_service
    result = gophish_service.verify_connection()
    return result


def _test_cobaltstrike():
    from app.services import cobaltstrike_service
    result = cobaltstrike_service.verify_connection()
    return result


def _test_openai():
    from app.services import website_generator_service
    client, deployment = website_generator_service._get_client()
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": "Say 'ok' in one word."}],
        max_tokens=5,
    )
    return {'status': 'ok', 'model': deployment, 'reply': response.choices[0].message.content.strip()}
