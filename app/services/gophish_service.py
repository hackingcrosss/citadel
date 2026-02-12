import requests
import urllib3
from app.services.credential_service import get_credential

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _base_url():
    url = get_credential('gophish', 'api_url')
    if not url:
        raise ValueError('GoPhish API URL not configured')
    return url.rstrip('/')


def _headers():
    key = get_credential('gophish', 'api_key')
    if not key:
        raise ValueError('GoPhish API key not configured')
    return {'Authorization': key, 'Content-Type': 'application/json'}


def _request(method, path, **kwargs):
    url = _base_url() + path
    resp = requests.request(method, url, headers=_headers(), verify=False, timeout=15, **kwargs)
    if resp.status_code >= 400:
        error = resp.text
        try:
            error = resp.json().get('message', resp.text)
        except Exception:
            pass
        raise Exception(f'GoPhish API error ({resp.status_code}): {error}')
    if resp.status_code == 204:
        return None
    return resp.json()


def verify_connection():
    profiles = _request('GET', '/api/smtp/')
    return {'profile_count': len(profiles) if isinstance(profiles, list) else 0}


def list_sending_profiles():
    return _request('GET', '/api/smtp/')


def get_sending_profile(profile_id):
    return _request('GET', f'/api/smtp/{profile_id}')


def create_sending_profile(data):
    return _request('POST', '/api/smtp/', json=data)


def delete_sending_profile(profile_id):
    return _request('DELETE', f'/api/smtp/{profile_id}')
