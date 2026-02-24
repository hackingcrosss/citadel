import requests
from app.services.credential_service import get_credential


def _base_url():
    url = get_credential('npm', 'api_url')
    if not url:
        raise ValueError("NPM API URL not configured. Set it in Settings.")
    return url.rstrip('/')


def _headers():
    token = get_credential('npm', 'api_token')
    if not token:
        raise ValueError("NPM API token not configured. Set it in Settings.")
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }


def _request(method, path, **kwargs):
    url = f'{_base_url()}{path}'
    resp = requests.request(method, url, headers=_headers(), timeout=15, **kwargs)
    if resp.status_code >= 400:
        try:
            err = resp.json().get('error', {}).get('message', resp.text)
        except Exception:
            err = resp.text
        raise Exception(f"NPM API error ({resp.status_code}): {err}")
    return resp.json()


# --- Token / Verification ---

def verify_connection():
    # NPM doesn't have a dedicated verify endpoint; listing hosts works as a test
    data = _request('GET', '/nginx/proxy-hosts')
    return {'host_count': len(data) if isinstance(data, list) else 0}


def get_token(identity, secret):
    """Authenticate with NPM and get a JWT token.

    This is used for initial setup — user provides email/password,
    we get a token and store it.
    """
    url = f'{_base_url()}/tokens'
    resp = requests.post(url, json={
        'identity': identity,
        'secret': secret
    }, timeout=15)
    if resp.status_code >= 400:
        raise Exception(f"NPM auth failed ({resp.status_code})")
    data = resp.json()
    return data.get('token', data.get('access_token', ''))


# --- Proxy Hosts ---

def list_proxy_hosts():
    data = _request('GET', '/nginx/proxy-hosts')
    return data if isinstance(data, list) else []


def get_proxy_host(host_id):
    data = _request('GET', f'/nginx/proxy-hosts/{host_id}')
    return data


def create_proxy_host(domain_names, forward_host, forward_port,
                      forward_scheme='http', ssl_forced=False,
                      block_exploits=True, allow_websocket_upgrade=False):
    payload = {
        'domain_names': domain_names if isinstance(domain_names, list) else [domain_names],
        'forward_host': forward_host,
        'forward_port': int(forward_port),
        'forward_scheme': forward_scheme,
        'ssl_forced': ssl_forced,
        'block_exploits': block_exploits,
        'allow_websocket_upgrade': allow_websocket_upgrade,
        'access_list_id': '0',
        'meta': {'letsencrypt_agree': False, 'dns_challenge': False},
        'advanced_config': '',
        'locations': [],
        'certificate_id': 0,
        'http2_support': False,
        'hsts_enabled': False,
        'hsts_subdomains': False,
    }
    data = _request('POST', '/nginx/proxy-hosts', json=payload)
    return data


def update_proxy_host(host_id, **kwargs):
    current = get_proxy_host(host_id)

    payload = {
        'domain_names': kwargs.get('domain_names', current.get('domain_names', [])),
        'forward_host': kwargs.get('forward_host', current.get('forward_host', '')),
        'forward_port': int(kwargs.get('forward_port', current.get('forward_port', 80))),
        'forward_scheme': kwargs.get('forward_scheme', current.get('forward_scheme', 'http')),
        'ssl_forced': kwargs.get('ssl_forced', current.get('ssl_forced', False)),
        'block_exploits': kwargs.get('block_exploits', current.get('block_exploits', True)),
        'allow_websocket_upgrade': kwargs.get('allow_websocket_upgrade', current.get('allow_websocket_upgrade', False)),
        'access_list_id': kwargs.get('access_list_id', current.get('access_list_id', '0')),
        'meta': current.get('meta', {}),
        'advanced_config': kwargs.get('advanced_config', current.get('advanced_config', '')),
        'locations': current.get('locations', []),
        'certificate_id': current.get('certificate_id', 0),
        'http2_support': kwargs.get('http2_support', current.get('http2_support', False)),
        'hsts_enabled': kwargs.get('hsts_enabled', current.get('hsts_enabled', False)),
        'hsts_subdomains': kwargs.get('hsts_subdomains', current.get('hsts_subdomains', False)),
    }
    data = _request('PUT', f'/nginx/proxy-hosts/{host_id}', json=payload)
    return data


def delete_proxy_host(host_id):
    data = _request('DELETE', f'/nginx/proxy-hosts/{host_id}')
    return data


def enable_proxy_host(host_id):
    data = _request('POST', f'/nginx/proxy-hosts/{host_id}/enable')
    return data


def disable_proxy_host(host_id):
    data = _request('POST', f'/nginx/proxy-hosts/{host_id}/disable')
    return data


# --- Access Lists ---

def list_access_lists():
    data = _request('GET', '/nginx/access-lists')
    return data if isinstance(data, list) else []


# --- SSL Certificates ---

def list_certificates():
    data = _request('GET', '/nginx/certificates')
    return data if isinstance(data, list) else []


# --- Redirection Hosts ---

def list_redirection_hosts():
    data = _request('GET', '/nginx/redirection-hosts')
    return data if isinstance(data, list) else []
