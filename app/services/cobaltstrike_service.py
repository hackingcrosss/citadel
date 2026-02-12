import requests
import urllib3
import threading
from app.services.credential_service import get_credential

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Module-level JWT token cache
_token_cache = {
    'token': None,
    'lock': threading.Lock()
}


def _base_url():
    url = get_credential('cobaltstrike', 'api_url')
    if not url:
        raise ValueError('Cobalt Strike API URL not configured')
    return url.rstrip('/')


def _get_credentials():
    username = get_credential('cobaltstrike', 'username')
    password = get_credential('cobaltstrike', 'password')
    if not username or not password:
        raise ValueError('Cobalt Strike username/password not configured')
    return username, password


def _authenticate():
    """Authenticate with the CS REST API and return a JWT token."""
    username, password = _get_credentials()
    url = _base_url() + '/api/auth/login'
    resp = requests.post(url, json={
        'username': username,
        'password': password
    }, verify=False, timeout=15)
    if resp.status_code >= 400:
        raise Exception(f'Cobalt Strike auth failed ({resp.status_code}): {resp.text}')
    data = resp.json()
    token = data.get('access_token')
    if not token:
        raise Exception('No access_token in Cobalt Strike auth response')
    return token


def _get_token(force_refresh=False):
    """Get a cached token or authenticate to obtain a new one."""
    with _token_cache['lock']:
        if _token_cache['token'] is None or force_refresh:
            _token_cache['token'] = _authenticate()
        return _token_cache['token']


def _headers(token=None):
    t = token or _get_token()
    return {
        'Authorization': f'Bearer {t}',
        'Content-Type': 'application/json'
    }


def _request(method, path, **kwargs):
    url = _base_url() + path
    token = _get_token()
    resp = requests.request(
        method, url,
        headers=_headers(token),
        verify=False,
        timeout=15,
        **kwargs
    )

    # On 401, re-authenticate once and retry
    if resp.status_code == 401:
        new_token = _get_token(force_refresh=True)
        resp = requests.request(
            method, url,
            headers=_headers(new_token),
            verify=False,
            timeout=15,
            **kwargs
        )

    if resp.status_code >= 400:
        error = resp.text
        try:
            error = resp.json().get('message', resp.text)
        except Exception:
            pass
        raise Exception(f'Cobalt Strike API error ({resp.status_code}): {error}')

    if resp.status_code == 204:
        return None
    return resp.json()


def verify_connection():
    """Test connectivity by listing listeners."""
    listeners = _request('GET', '/api/v1/listeners')
    count = len(listeners) if isinstance(listeners, list) else 0
    return {'listener_count': count}


def list_listeners():
    return _request('GET', '/api/v1/listeners')


def get_listener(listener_id):
    return _request('GET', f'/api/v1/listeners/{listener_id}')


def create_listener(data):
    return _request('POST', '/api/v1/listeners', json=data)


def delete_listener(listener_id):
    return _request('DELETE', f'/api/v1/listeners/{listener_id}')
