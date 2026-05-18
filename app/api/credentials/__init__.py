import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import credential_service
from app.utils.decorators import admin_required
from app.utils.errors import safe_error

_log = logging.getLogger(__name__)

# Keys whose values must pass outbound-URL validation before being stored.
# Blocks SSRF via credential-write (E-1).
_URL_CREDENTIAL_KEYS = {'api_url', 'endpoint', 'host', 'webhook_url'}


_MULTI_ACCOUNT_PROVIDERS = {'cloudflare', 'aws', 'azure', 'cobaltstrike', 'hetzner'}

# Providers whose /labels and /test endpoints are hidden from non-admins.
# Hetzner is NOT in this set: operators need to see account labels to select
# Hetzner servers in compute pickers. Writing/reading full credentials is
# already admin-only via the @admin_required decorator on GET/POST.
_ADMIN_ONLY_PROVIDERS = set()


@api_bp.route('/credentials/<provider>/labels', methods=['GET'])
@login_required
def get_credential_labels(provider):
    """Return account labels for a multi-account provider (no credential values)."""
    if provider in _ADMIN_ONLY_PROVIDERS and not current_user.is_admin:
        return jsonify({'error': 'Administrator access required'}), 403
    labels = credential_service.get_account_labels(provider)
    return jsonify({'labels': labels})


@api_bp.route('/credentials/<provider>', methods=['GET'])
@login_required
@admin_required
def get_credentials(provider):
    data = credential_service.get_all_for_provider(provider)
    if provider in _MULTI_ACCOUNT_PROVIDERS:
        # Return accounts grouped by label for the multi-account UI
        accounts = [
            {'label': lbl, **keys}
            for lbl, keys in sorted(data.items())
        ]
        return jsonify({provider: {'configured': len(accounts) > 0, 'accounts': accounts}})
    # All other providers: flat {key_name: {...}} format (backward compat)
    flat = data.get('default', {})
    return jsonify({provider: flat})


@api_bp.route('/credentials/<provider>', methods=['POST'])
@login_required
@admin_required
def save_credentials(provider):
    payload = request.get_json()
    if not payload:
        return jsonify({'error': 'No data provided'}), 400

    from app.utils.url_validation import validate_outbound_url

    if provider in _MULTI_ACCOUNT_PROVIDERS:
        label = (payload.pop('label', None) or 'default').strip()
        saved = []
        for key_name, value in payload.items():
            if value and str(value).strip():
                val = str(value).strip()
                # E-1: validate URL-type credentials against SSRF allowlist
                if key_name in _URL_CREDENTIAL_KEYS:
                    ok, reason = validate_outbound_url(val, resolve=False)
                    if not ok:
                        return jsonify({'error': f'Invalid {key_name}: {reason}'}), 400
                credential_service.set_credential(provider, key_name, val, label=label)
                saved.append(key_name)
        return jsonify({'saved': saved, 'provider': provider, 'label': label})

    # Other providers: always use label='default'
    saved = []
    for key_name, value in payload.items():
        if value and str(value).strip():
            val = str(value).strip()
            # E-1: validate URL-type credentials against SSRF allowlist
            if key_name in _URL_CREDENTIAL_KEYS:
                ok, reason = validate_outbound_url(val, resolve=False)
                if not ok:
                    return jsonify({'error': f'Invalid {key_name}: {reason}'}), 400
            credential_service.set_credential(provider, key_name, val)
            saved.append(key_name)
    return jsonify({'saved': saved, 'provider': provider})


@api_bp.route('/credentials/cloudflare/account/<label>', methods=['DELETE'])
@login_required
@admin_required
def delete_cloudflare_account(label):
    labels = credential_service.get_account_labels('cloudflare')
    if len(labels) <= 1:
        return jsonify({'error': 'Cannot delete the last Cloudflare account'}), 400
    deleted = credential_service.delete_account('cloudflare', label)
    if deleted:
        return jsonify({'deleted': True, 'label': label})
    return jsonify({'error': 'Account not found'}), 404


@api_bp.route('/credentials/aws/account/<label>', methods=['DELETE'])
@login_required
@admin_required
def delete_aws_account(label):
    labels = credential_service.get_account_labels('aws')
    if len(labels) <= 1:
        return jsonify({'error': 'Cannot delete the last AWS account'}), 400
    deleted = credential_service.delete_account('aws', label)
    if deleted:
        return jsonify({'deleted': True, 'label': label})
    return jsonify({'error': 'Account not found'}), 404


@api_bp.route('/credentials/azure/account/<label>', methods=['DELETE'])
@login_required
@admin_required
def delete_azure_account(label):
    labels = credential_service.get_account_labels('azure')
    if len(labels) <= 1:
        return jsonify({'error': 'Cannot delete the last Azure account'}), 400
    deleted = credential_service.delete_account('azure', label)
    if deleted:
        return jsonify({'deleted': True, 'label': label})
    return jsonify({'error': 'Account not found'}), 404


@api_bp.route('/credentials/cobaltstrike/account/<label>', methods=['DELETE'])
@login_required
@admin_required
def delete_cobaltstrike_account(label):
    labels = credential_service.get_account_labels('cobaltstrike')
    if len(labels) <= 1:
        return jsonify({'error': 'Cannot delete the last C2 server'}), 400
    deleted = credential_service.delete_account('cobaltstrike', label)
    if deleted:
        return jsonify({'deleted': True, 'label': label})
    return jsonify({'error': 'C2 server not found'}), 404


@api_bp.route('/credentials/hetzner/account/<label>', methods=['DELETE'])
@login_required
@admin_required
def delete_hetzner_account(label):
    # Deleting the last account is allowed — it fully disables the integration
    # (sidebar disappears, /hetzner redirects, API returns 404).
    deleted = credential_service.delete_account('hetzner', label)
    if deleted:
        return jsonify({'deleted': True, 'label': label})
    return jsonify({'error': 'Account not found'}), 404


@api_bp.route('/credentials/<provider>/test', methods=['POST'])
@login_required
def test_credentials(provider):
    if provider in _ADMIN_ONLY_PROVIDERS and not current_user.is_admin:
        return jsonify({'error': 'Administrator access required'}), 403

    testers = {
        'cloudflare': _test_cloudflare,
        'mailgun': _test_mailgun,
        'npm': _test_npm,
        'aws': _test_aws,
        'azure': _test_azure,
        'hetzner': _test_hetzner,
        'docker': _test_docker,
        'gophish': _test_gophish,
        'cobaltstrike': _test_cobaltstrike,
        'openai': _test_openai,
        'scanner': _test_scanner,
        'fofa': _test_fofa,
    }

    tester = testers.get(provider)
    if not tester:
        return jsonify({'error': f'No test available for {provider}'}), 400

    try:
        payload = request.get_json(silent=True) or {}
        label = payload.get('label', 'default') if provider in _MULTI_ACCOUNT_PROVIDERS else 'default'
        result = tester(label=label) if provider in _MULTI_ACCOUNT_PROVIDERS else tester()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return safe_error(e, 400, success=False)


_PUBLIC_CREDENTIAL_KEYS = {
    ('npm', 'public_ip'),
    # G-04: 'cobaltstrike/listener_ip' and 'cobaltstrike/redirector_ip' used to
    # live here, leaking C2 infrastructure IPs to any authenticated user
    # (auditor, white_team, plain user, project_admin). Removed — now require
    # admin. The /api/cobaltstrike/servers endpoint is the legitimate
    # operator-visible surface for these values.
}


@api_bp.route('/credentials/<provider>/<key_name>', methods=['GET'])
@login_required
def get_single_credential(provider, key_name):
    """Get a single credential value. Non-secret keys are readable by all
    authenticated users; everything else requires admin."""
    if (provider, key_name) not in _PUBLIC_CREDENTIAL_KEYS:
        if not current_user.is_admin:
            return jsonify({'error': 'Administrator access required'}), 403
    value = credential_service.get_credential(provider, key_name)
    if value is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'provider': provider, 'key': key_name, 'value': value})


@api_bp.route('/credentials/<provider>/<key_name>', methods=['DELETE'])
@login_required
@admin_required
def delete_credential(provider, key_name):
    deleted = credential_service.delete_credential(provider, key_name)
    if deleted:
        return jsonify({'deleted': True})
    return jsonify({'error': 'Credential not found'}), 404


def _test_cloudflare(label='default'):
    from app.services import dns_service
    result = dns_service.verify_token(label=label)
    return {'status': result.get('status', 'unknown')}


def _test_mailgun():
    from app.services import email_service
    result = email_service.verify_api_key()
    return result


def _test_npm():
    from app.services import npm_service
    result = npm_service.verify_connection()
    return result


def _test_aws(label='default'):
    from app.services import aws_service
    result = aws_service.verify_credentials(label=label)
    return result


def _test_docker():
    from app.services import docker_service
    containers = docker_service.list_containers()
    return {'container_count': len(containers)}


def _test_gophish():
    from app.services import gophish_service
    result = gophish_service.verify_connection()
    return result


def _test_cobaltstrike(label='default'):
    from app.services import cobaltstrike_service
    result = cobaltstrike_service.verify_connection(label=label)
    return result


def _test_openai():
    from app.services.openai_service import get_client, completion_kwargs
    client, deployment = get_client()
    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": "Say 'ok' in one word."}],
        **completion_kwargs(max_tokens=5, temperature=0.1),
    )
    return {'status': 'ok', 'model': deployment, 'reply': response.choices[0].message.content.strip()}


def _test_hetzner(label='default'):
    from app.services import hetzner_service
    result = hetzner_service.verify_credentials(label=label)
    return result


def _test_azure(label='default'):
    from azure.identity import ClientSecretCredential
    from azure.mgmt.resource import ResourceManagementClient
    from app.services.credential_service import get_credential

    tenant_id = get_credential('azure', 'tenant_id', label=label)
    client_id = get_credential('azure', 'client_id', label=label)
    client_secret = get_credential('azure', 'client_secret', label=label)
    subscription_id = get_credential('azure', 'subscription_id', label=label)

    if not all([tenant_id, client_id, client_secret, subscription_id]):
        raise ValueError(f"Azure credentials not fully configured for account '{label}'. "
                         "Set tenant_id, client_id, client_secret, and subscription_id in Settings.")

    cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    rm_client = ResourceManagementClient(cred, subscription_id)
    groups = list(rm_client.resource_groups.list())
    return {'subscription_id': subscription_id, 'resource_group_count': len(groups)}


def _test_scanner():
    from app.services import ia_scan_service
    result = ia_scan_service.test_connection()
    return result


def _test_fofa():
    from app.services import fofa_service
    result = fofa_service.test_connection()
    return result
