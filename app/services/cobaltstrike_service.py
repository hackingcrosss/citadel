import requests
import urllib3
import threading
from app.services.credential_service import get_credential

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Per-label JWT token cache: {label: {'token': str|None, 'lock': Lock}}
_token_caches = {}
_cache_lock = threading.Lock()


def _get_label_cache(label='default'):
    with _cache_lock:
        if label not in _token_caches:
            _token_caches[label] = {'token': None, 'lock': threading.Lock()}
        return _token_caches[label]


def _base_url(label='default'):
    url = get_credential('cobaltstrike', 'api_url', label=label)
    if not url:
        raise ValueError(f'Cobalt Strike API URL not configured for server "{label}"')
    return url.rstrip('/')


def _tls_verify(label='default'):
    """Return the TLS verification setting for this CS server.

    Defaults to True (secure). An administrator can explicitly set the
    stored credential ``tls_verify`` to ``"0"`` to disable verification
    for self-signed teamserver certs. The UI exposes this as a conscious
    opt-in toggle.
    """
    val = get_credential('cobaltstrike', 'tls_verify', label=label)
    if val is None:
        return True
    return val.strip().lower() not in ('0', 'false', 'no', 'off')


def _get_credentials(label='default'):
    username = get_credential('cobaltstrike', 'username', label=label)
    password = get_credential('cobaltstrike', 'password', label=label)
    if not username or not password:
        raise ValueError(f'Cobalt Strike username/password not configured for server "{label}"')
    return username, password


def _authenticate(label='default'):
    """Authenticate with the CS REST API and return a JWT token."""
    username, password = _get_credentials(label)
    url = _base_url(label) + '/api/auth/login'
    resp = requests.post(url, json={
        'username': username,
        'password': password
    }, verify=_tls_verify(label), timeout=15)
    if resp.status_code >= 400:
        raise Exception(f'Cobalt Strike auth failed ({resp.status_code}): {resp.text}')
    data = resp.json()
    token = data.get('access_token')
    if not token:
        raise Exception('No access_token in Cobalt Strike auth response')
    return token


def _get_token(label='default', force_refresh=False):
    """Get a cached token or authenticate to obtain a new one."""
    cache = _get_label_cache(label)
    with cache['lock']:
        if cache['token'] is None or force_refresh:
            cache['token'] = _authenticate(label)
        return cache['token']


def _headers(label='default', token=None):
    t = token or _get_token(label)
    return {
        'Authorization': f'Bearer {t}',
        'Content-Type': 'application/json'
    }


def _is_auth_error(resp):
    """Return True if the response indicates the cached JWT is stale.

    After a teamserver restart the signing key is regenerated, so any
    previously cached token will fail validation. CS may return:
      - 401 Unauthorized
      - 403 Forbidden (some CS REST API builds)
      - 400 with a body mentioning jwt/signature/token/expired/invalid
      - 422 (validation error on malformed/expired bearer)
    """
    if resp.status_code in (401, 403, 422):
        return True
    if resp.status_code == 400:
        try:
            body = resp.json()
            text = str(body.get('detail') or body.get('message') or body.get('title') or '')
        except Exception:
            text = resp.text or ''
        keywords = ('jwt', 'signature', 'token', 'expired', 'invalid', 'unauthorized', 'forbidden')
        return any(k in text.lower() for k in keywords)
    return False


def _request(method, path, label='default', **kwargs):
    url = _base_url(label) + path
    tls = _tls_verify(label)

    # First attempt — use the cached token.  If the CS REST API restarted
    # the TCP connect itself may fail (ConnectionError / timeout), so catch
    # that and retry once after a short pause.
    for attempt in range(2):
        try:
            token = _get_token(label, force_refresh=(attempt > 0))
            resp = requests.request(
                method, url,
                headers=_headers(label, token),
                verify=tls,
                timeout=15,
                **kwargs
            )
            break
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 0:
                import time
                time.sleep(2)
                continue
            raise

    # Re-authenticate on any auth-related error (stale JWT after CS restart).
    if _is_auth_error(resp):
        new_token = _get_token(label, force_refresh=True)
        resp = requests.request(
            method, url,
            headers=_headers(label, new_token),
            verify=tls,
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


def verify_connection(label='default'):
    """Test connectivity by listing listeners (always re-authenticates)."""
    # Force a fresh token — the most common reason to hit "Test" is after
    # a teamserver restart that invalidated the cached JWT.
    cache = _get_label_cache(label)
    with cache['lock']:
        cache['token'] = None
    listeners = _request('GET', '/api/v1/listeners', label=label)
    count = len(listeners) if isinstance(listeners, list) else 0
    return {'listener_count': count}


def list_listeners(label='default'):
    return _request('GET', '/api/v1/listeners', label=label)


def get_listener(listener_name, label='default'):
    return _request('GET', f'/api/v1/listeners/{listener_name}', label=label)


def create_listener(listener_type, data, label='default'):
    """Create a listener. The CS REST API uses type-specific endpoints:
    POST /api/v1/listeners/{type}  with the listener config as JSON body.
    The body must NOT include a 'payload' field — the type is in the URL."""
    return _request('POST', f'/api/v1/listeners/{listener_type}', label=label, json=data)


def delete_listener(listener_name, label='default'):
    return _request('DELETE', f'/api/v1/listeners/{listener_name}', label=label)


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


def update_listener_hosts(listener_name, new_hosts, label='default'):
    """Update a listener's callback hosts by deleting and recreating it.
    Returns the new listener data."""
    current = get_listener(listener_name, label=label)
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
    delete_listener(listener_name, label=label)
    try:
        return create_listener(listener_type, body, label=label)
    except Exception as exc:
        # Attempt to restore the original listener
        restore_body = {k: v for k, v in current.items() if k in valid}
        try:
            create_listener(listener_type, restore_body, label=label)
        except Exception:
            pass  # restore is best-effort
        raise Exception(f'Failed to recreate listener with new hosts: {exc}. '
                        f'Attempted to restore original config.')
