import logging
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app
from app.services.credential_service import get_credential, get_account_labels

_log = logging.getLogger(__name__)

CF_BASE = 'https://api.cloudflare.com/client/v4'
# Cloudflare supports up to 1000; 500 keeps responses snappy while halving round-trips.
_ZONES_PER_PAGE = 500
# CF DNS records endpoint max is 100 per page but 5-second fetches are fine at that size.
_RECORDS_PER_PAGE = 100

# zone_id -> account_label, populated whenever list_zones_all_accounts() runs.
# Used by _zone_label() so untracked zones still route to the right account.
_zone_account_cache: dict = {}


def _headers(label='default'):
    token = get_credential('cloudflare', 'api_token', label=label)
    if not token:
        raise ValueError(f"Cloudflare API token not configured for account '{label}'. Set it in Settings.")
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }


def _request(method, path, label='default', **kwargs):
    url = f'{CF_BASE}{path}'
    resp = requests.request(method, url, headers=_headers(label=label), timeout=15, **kwargs)
    data = resp.json()
    if not data.get('success', False):
        errors = data.get('errors', [])
        msg = errors[0].get('message', 'Unknown error') if errors else 'Unknown error'
        raise Exception(f"Cloudflare API error: {msg}")
    return data


# --- Token Verification ---

def verify_token(label='default'):
    data = _request('GET', '/user/tokens/verify', label=label)
    return data['result']


# --- Zones ---

def list_zones(name_filter=None, page=1, per_page=_ZONES_PER_PAGE, label='default'):
    params = {'page': page, 'per_page': per_page}
    if name_filter:
        params['name'] = name_filter
    data = _request('GET', '/zones', label=label, params=params)
    return data['result'], data.get('result_info', {})


def _fetch_all_zones_for_account(lbl):
    """Fetch every page of zones for a single account. Returns list of zone dicts."""
    zones = []
    page = 1
    while True:
        page_zones, info = list_zones(page=page, per_page=_ZONES_PER_PAGE, label=lbl)
        for z in page_zones:
            z['account_label'] = lbl
        zones.extend(page_zones)
        if page >= info.get('total_pages', 1):
            break
        page += 1
    return zones


def list_zones_all_accounts():
    """Fetch zones from every configured Cloudflare account in parallel.

    Each zone dict gets an extra ``account_label`` field.  Individual account
    errors are logged and skipped so one bad token does not block the rest.
    """
    labels = get_account_labels('cloudflare')
    if not labels:
        return []

    all_zones = []

    # Single account — no threading overhead needed.
    if len(labels) == 1:
        try:
            all_zones = _fetch_all_zones_for_account(labels[0])
            _zone_account_cache.update({z['id']: z['account_label'] for z in all_zones})
        except Exception as exc:
            _log.warning("Cloudflare zone fetch failed for account '%s': %s", labels[0], exc)
        return all_zones

    # Capture the real app object so each thread can push its own context.
    # current_app is a proxy — ._get_current_object() gives the actual Flask app.
    app = current_app._get_current_object()

    def _fetch_in_context(lbl):
        with app.app_context():
            return _fetch_all_zones_for_account(lbl)

    with ThreadPoolExecutor(max_workers=min(len(labels), 8)) as pool:
        futures = {pool.submit(_fetch_in_context, lbl): lbl for lbl in labels}
        for future in as_completed(futures):
            lbl = futures[future]
            try:
                all_zones.extend(future.result())
            except Exception as exc:
                _log.warning("Cloudflare zone fetch failed for account '%s': %s", lbl, exc)

    _zone_account_cache.update({z['id']: z['account_label'] for z in all_zones})
    return all_zones


def get_zone(zone_id, label='default'):
    data = _request('GET', f'/zones/{zone_id}', label=label)
    return data['result']


# --- DNS Records ---

def list_dns_records(zone_id, record_type=None, name=None, label='default'):
    """Return all DNS records for a zone, paging through the full result set."""
    params = {'per_page': _RECORDS_PER_PAGE}
    if record_type:
        params['type'] = record_type
    if name:
        params['name'] = name

    records = []
    page = 1
    while True:
        params['page'] = page
        data = _request('GET', f'/zones/{zone_id}/dns_records', label=label, params=params)
        records.extend(data['result'])
        info = data.get('result_info', {})
        if page >= info.get('total_pages', 1):
            break
        page += 1

    return records


def create_dns_record(zone_id, record_type, name, content, ttl=1, proxied=False, priority=None, label='default'):
    payload = {
        'type': record_type,
        'name': name,
        'content': content,
        'ttl': ttl,
        'proxied': proxied
    }
    if priority is not None:
        payload['priority'] = priority
    data = _request('POST', f'/zones/{zone_id}/dns_records', label=label, json=payload)
    return data['result']


def update_dns_record(zone_id, record_id, record_type, name, content, ttl=1, proxied=False, priority=None, label='default'):
    payload = {
        'type': record_type,
        'name': name,
        'content': content,
        'ttl': ttl,
        'proxied': proxied
    }
    if priority is not None:
        payload['priority'] = priority
    data = _request('PUT', f'/zones/{zone_id}/dns_records/{record_id}', label=label, json=payload)
    return data['result']


def delete_dns_record(zone_id, record_id, label='default'):
    data = _request('DELETE', f'/zones/{zone_id}/dns_records/{record_id}', label=label)
    return data['result']


# --- SSL Settings ---

def get_ssl_setting(zone_id, label='default'):
    data = _request('GET', f'/zones/{zone_id}/settings/ssl', label=label)
    return data['result']


def set_ssl_setting(zone_id, value, label='default'):
    data = _request('PATCH', f'/zones/{zone_id}/settings/ssl', label=label, json={'value': value})
    return data['result']


def enable_dmarc_management(zone_id, label='default'):
    """Enable Cloudflare DMARC Management for a zone.

    Returns a dict with:
      - 'tag': unique Cloudflare reporting tag (the rua address prefix)
      - 'rua': full rua mailto address for use in the _dmarc TXT record
    """
    data = _request(
        'PATCH',
        f'/zones/{zone_id}/email/security/dmarc-reports',
        label=label,
        json={'enabled': True},
    )
    result = data.get('result', {})
    # Cloudflare returns the reporting tag used to build the rua address.
    tag = result.get('tag') or result.get('rua_tag') or result.get('rua_mailbox') or ''
    rua = f'{tag}@dmarc-reports.cloudflare.net' if tag else None
    return {'enabled': result.get('enabled', True), 'tag': tag, 'rua': rua}


# --- WHOIS ---

def get_whois_info(domain_name):
    """Fetch WHOIS registration/expiration dates for a domain.

    Returns a dict with creation_date, expiration_date, age_days, is_expired,
    is_aged (>30 days old), and registrar.
    """
    try:
        import whois
    except ImportError:
        raise ValueError("python-whois package is not installed")

    w = whois.whois(domain_name)

    def _first_date(val):
        if val is None:
            return None
        if isinstance(val, list):
            val = val[0] if val else None
        if isinstance(val, datetime):
            # Ensure timezone-aware for safe comparisons
            if val.tzinfo is None:
                return val.replace(tzinfo=timezone.utc)
            return val
        return None

    creation = _first_date(w.creation_date)
    expiration = _first_date(w.expiration_date)
    now = datetime.now(timezone.utc)

    age_days = (now - creation).days if creation else None
    is_expired = expiration < now if expiration else None
    is_aged = age_days >= 30 if age_days is not None else None

    return {
        'domain': domain_name,
        'creation_date': creation.isoformat() if creation else None,
        'expiration_date': expiration.isoformat() if expiration else None,
        'age_days': age_days,
        'is_expired': is_expired,
        'is_aged': is_aged,
        'registrar': w.registrar if hasattr(w, 'registrar') else None,
    }
