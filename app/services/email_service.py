import requests
from urllib.parse import quote
from app.services.credential_service import get_credential

MG_BASES = {
    'us': 'https://api.mailgun.net/v3',
    'eu': 'https://api.eu.mailgun.net/v3',
}


def _auth():
    api_key = get_credential('mailgun', 'api_key')
    if not api_key:
        raise ValueError("Mailgun API key not configured. Set it in Settings.")
    return ('api', api_key)


def _request(method, path, region='us', **kwargs):
    base = MG_BASES.get(region, MG_BASES['us'])
    url = f'{base}{path}'
    resp = requests.request(method, url, auth=_auth(), timeout=15, **kwargs)
    if resp.status_code >= 400:
        try:
            err = resp.json().get('message', resp.text)
        except Exception:
            err = resp.text
        raise Exception(f"Mailgun API error ({resp.status_code}): {err}")
    return resp.json()


# --- Verification ---

def verify_api_key():
    data = _request('GET', '/domains', params={'limit': 1})
    return {'total_count': data.get('total_count', 0)}


# --- Domains ---

def list_domains(region=None):
    if region and region in MG_BASES:
        data = _request('GET', '/domains', region=region, params={'limit': 100})
        items = data.get('items', [])
        for d in items:
            d['region'] = region.upper()
        return items

    # Fetch from both regions
    all_domains = []
    for r in ('us', 'eu'):
        try:
            data = _request('GET', '/domains', region=r, params={'limit': 100})
            items = data.get('items', [])
            for d in items:
                d['region'] = r.upper()
            all_domains.extend(items)
        except Exception:
            pass
    return all_domains


def add_domain(name, region='us'):
    safe_name = quote(name, safe='')
    # Check if domain already exists
    try:
        existing = _request('GET', f'/domains/{safe_name}', region=region)
        # Domain exists – return it with a flag
        existing['already_existed'] = True
        return existing
    except Exception:
        pass  # 404 means domain doesn't exist, proceed to create

    data = _request('POST', '/domains', region=region, data={
        'name': name,
        'spam_action': 'disabled',
        'wildcard': False,
        'force_dkim_authority': True,
        'dkim_key_size': 2048,
    })
    return data


def get_domain(name, region='us'):
    safe_name = quote(name, safe='')
    data = _request('GET', f'/domains/{safe_name}', region=region)
    return data


def delete_domain(name, region='us'):
    safe_name = quote(name, safe='')
    data = _request('DELETE', f'/domains/{safe_name}', region=region)
    return data


def verify_domain(name, region='us'):
    safe_name = quote(name, safe='')
    data = _request('PUT', f'/domains/{safe_name}/verify', region=region)
    return data


# --- SMTP Credentials ---

def list_smtp_credentials(domain, region='us'):
    safe_domain = quote(domain, safe='')
    data = _request('GET', f'/domains/{safe_domain}/credentials', region=region, params={'limit': 100})
    return data.get('items', [])


def create_smtp_credential(domain, login, password, region='us'):
    safe_domain = quote(domain, safe='')
    data = _request('POST', f'/domains/{safe_domain}/credentials', region=region, data={
        'login': login,
        'password': password
    })
    # G-01: Mailgun's create-credential API echoes the submitted password
    # in the response. Strip it so the plaintext credential never re-exits
    # the service layer (and never lands in logs / proxies / API responses).
    if isinstance(data, dict):
        data.pop('password', None)
    return data


def delete_smtp_credential(domain, login, region='us'):
    safe_domain = quote(domain, safe='')
    safe_login = quote(login, safe='')
    data = _request('DELETE', f'/domains/{safe_domain}/credentials/{safe_login}', region=region)
    return data
