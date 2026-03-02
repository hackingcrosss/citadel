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


def _is_jwt_error(resp):
    """Return True if the response indicates a JWT signature/validity error."""
    try:
        body = resp.json()
        text = str(body.get('detail') or body.get('message') or body.get('title') or '')
    except Exception:
        text = resp.text or ''
    keywords = ('jwt', 'signature', 'token')
    return any(k in text.lower() for k in keywords)


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

    # Re-authenticate on 401, or on 400 with a JWT error (CS returns 400 for
    # stale tokens after a teamserver restart that regenerates the signing key).
    if resp.status_code == 401 or (resp.status_code == 400 and _is_jwt_error(resp)):
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
            err_json = resp.json()
            error = err_json.get('detail') or err_json.get('message') or err_json.get('title') or resp.text
        except Exception:
            pass
        raise Exception(f'Cobalt Strike API error ({resp.status_code}): {error}')

    if resp.status_code == 204 or not resp.text.strip():
        return None
    return resp.json()


def verify_connection():
    """Test connectivity by listing listeners."""
    listeners = _request('GET', '/api/v1/listeners')
    count = len(listeners) if isinstance(listeners, list) else 0
    return {'listener_count': count}


def list_listeners():
    return _request('GET', '/api/v1/listeners')


def get_listener(listener_name):
    return _request('GET', f'/api/v1/listeners/{listener_name}')


def create_listener(listener_type, data):
    """Create a listener. The CS REST API uses type-specific endpoints:
    POST /api/v1/listeners/{type}  with the listener config as JSON body.
    The body must NOT include a 'payload' field — the type is in the URL."""
    return _request('POST', f'/api/v1/listeners/{listener_type}', json=data)


def delete_listener(listener_name):
    return _request('DELETE', f'/api/v1/listeners/{listener_name}')
