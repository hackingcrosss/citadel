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


# Payload string → REST API type slug mapping (ordered: longer keys first to
# avoid 'beacon_http' matching before 'beacon_https')
_PAYLOAD_TYPE_MAP = [
    ('beacon_https',          'https'),
    ('beacon_http',           'http'),
    ('beacon_dns',            'dns'),
    ('bind_pipe',             'smb'),
    ('bind_tcp',              'tcp'),
    ('foreign_reverse_https', 'foreignHttps'),
    ('foreign_reverse_http',  'foreignHttp'),
    ('external_c2',           'externalC2'),
]

# Valid POST fields per listener type (from CS REST API docs / schemas.txt).
# Only these are sent on recreate — everything else is read-only.
_TYPE_VALID_FIELDS = {
    'http':  {'name', 'color', 'hosts', 'host', 'httpPort', 'httpBindPort',
              'httpHostHeader', 'hostRotationStrategy', 'maxRetryStrategy',
              'profile', 'ignoreProxySettings', 'httpProxy', 'guardRails'},
    'https': {'name', 'color', 'hosts', 'host', 'httpPort', 'httpBindPort',
              'httpHostHeader', 'hostRotationStrategy', 'maxRetryStrategy',
              'profile', 'ignoreProxySettings', 'httpProxy', 'guardRails'},
    'dns':   {'name', 'color', 'hosts', 'host', 'dnsBindPort',
              'hostRotationStrategy', 'maxRetryStrategy', 'profile',
              'dnsResolver', 'guardRails'},
}


def _detect_type(listener):
    """Detect the listener type slug from the payload string."""
    payload = listener.get('payload', '')
    for key, slug in _PAYLOAD_TYPE_MAP:
        if key in payload:
            return slug
    return None


def update_listener_hosts(listener_name, new_hosts):
    """Update a listener's callback hosts by deleting and recreating it.
    Returns the new listener data."""
    current = get_listener(listener_name)
    if not current:
        raise Exception(f'Listener "{listener_name}" not found')

    listener_type = _detect_type(current)
    if not listener_type:
        raise Exception(f'Cannot determine listener type from payload: {current.get("payload")}')

    if listener_type not in ('http', 'https', 'dns'):
        raise Exception(f'Listener type "{listener_type}" does not support callback hosts')

    # Build the recreation body using ONLY valid POST fields for this type
    valid = _TYPE_VALID_FIELDS.get(listener_type, set())
    body = {k: v for k, v in current.items() if k in valid}
    body['hosts'] = new_hosts

    # Delete then recreate — if recreate fails, attempt to restore original config
    delete_listener(listener_name)
    try:
        return create_listener(listener_type, body)
    except Exception as exc:
        # Attempt to restore the original listener
        restore_body = {k: v for k, v in current.items() if k in valid}
        try:
            create_listener(listener_type, restore_body)
        except Exception:
            pass  # restore is best-effort
        raise Exception(f'Failed to recreate listener with new hosts: {exc}. '
                        f'Attempted to restore original config.')
