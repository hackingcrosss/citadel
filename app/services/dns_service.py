import requests
from app.services.credential_service import get_credential

CF_BASE = 'https://api.cloudflare.com/client/v4'


def _headers():
    token = get_credential('cloudflare', 'api_token')
    if not token:
        raise ValueError("Cloudflare API token not configured. Set it in Settings.")
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }


def _request(method, path, **kwargs):
    url = f'{CF_BASE}{path}'
    resp = requests.request(method, url, headers=_headers(), timeout=15, **kwargs)
    data = resp.json()
    if not data.get('success', False):
        errors = data.get('errors', [])
        msg = errors[0].get('message', 'Unknown error') if errors else 'Unknown error'
        raise Exception(f"Cloudflare API error: {msg}")
    return data


# --- Token Verification ---

def verify_token():
    data = _request('GET', '/user/tokens/verify')
    return data['result']


# --- Zones ---

def list_zones(name_filter=None, page=1, per_page=50):
    params = {'page': page, 'per_page': per_page}
    if name_filter:
        params['name'] = name_filter
    data = _request('GET', '/zones', params=params)
    return data['result'], data.get('result_info', {})


def get_zone(zone_id):
    data = _request('GET', f'/zones/{zone_id}')
    return data['result']


# --- DNS Records ---

def list_dns_records(zone_id, record_type=None, name=None):
    params = {'per_page': 100}
    if record_type:
        params['type'] = record_type
    if name:
        params['name'] = name
    data = _request('GET', f'/zones/{zone_id}/dns_records', params=params)
    return data['result']


def create_dns_record(zone_id, record_type, name, content, ttl=1, proxied=False, priority=None):
    payload = {
        'type': record_type,
        'name': name,
        'content': content,
        'ttl': ttl,
        'proxied': proxied
    }
    if priority is not None:
        payload['priority'] = priority
    data = _request('POST', f'/zones/{zone_id}/dns_records', json=payload)
    return data['result']


def update_dns_record(zone_id, record_id, record_type, name, content, ttl=1, proxied=False, priority=None):
    payload = {
        'type': record_type,
        'name': name,
        'content': content,
        'ttl': ttl,
        'proxied': proxied
    }
    if priority is not None:
        payload['priority'] = priority
    data = _request('PUT', f'/zones/{zone_id}/dns_records/{record_id}', json=payload)
    return data['result']


def delete_dns_record(zone_id, record_id):
    data = _request('DELETE', f'/zones/{zone_id}/dns_records/{record_id}')
    return data['result']


# --- SSL Settings ---

def get_ssl_setting(zone_id):
    data = _request('GET', f'/zones/{zone_id}/settings/ssl')
    return data['result']


def set_ssl_setting(zone_id, value):
    data = _request('PATCH', f'/zones/{zone_id}/settings/ssl', json={'value': value})
    return data['result']
