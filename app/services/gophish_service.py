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
    resp = requests.request(method, url, headers=_headers(), verify=True, timeout=15, **kwargs)
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


def list_templates():
    return _request('GET', '/api/templates/')


def get_template(template_id):
    return _request('GET', f'/api/templates/{template_id}')


def create_template(data):
    return _request('POST', '/api/templates/', json=data)


def update_template(template_id, data):
    return _request('PUT', f'/api/templates/{template_id}', json=data)


def delete_template(template_id):
    return _request('DELETE', f'/api/templates/{template_id}')


def import_email_template(data):
    """Import an email (raw source) as a GoPhish template.
    data should have: content (raw email text), convert_links (bool).
    """
    return _request('POST', '/api/import/email', json=data)


def find_profile_for_domain(domain_name):
    """Find the first GoPhish sending profile whose from_address matches the given domain."""
    matches = find_all_profiles_for_domain(domain_name)
    return matches[0] if matches else None


def find_all_profiles_for_domain(domain_name):
    """Return all GoPhish sending profiles whose from_address matches the given domain."""
    profiles = list_sending_profiles()
    if not isinstance(profiles, list):
        return []
    domain_lower = domain_name.lower()
    matches = []
    for p in profiles:
        from_addr = (p.get('from_address') or '').lower()
        if '@' in from_addr and from_addr.rsplit('@', 1)[1] == domain_lower:
            matches.append(p)
            continue
        username = (p.get('username') or '').lower()
        if '@' in username and username.rsplit('@', 1)[1] == domain_lower:
            matches.append(p)
    return matches


_GROOMING_TEMPLATE_NAME = 'Citadel Grooming'


def _ensure_grooming_template(subject, html_body, text_body='', attachments=None):
    """Create or update the grooming template in GoPhish so send_test_email can reference it.

    Args:
        attachments: Optional list of dicts with 'name', 'content' (base64), and 'type' keys.
    """
    templates = list_templates()
    existing = None
    if isinstance(templates, list):
        for t in templates:
            if t.get('name') == _GROOMING_TEMPLATE_NAME:
                existing = t
                break

    tpl_data = {
        'name': _GROOMING_TEMPLATE_NAME,
        'subject': subject,
        'html': html_body,
        'text': text_body,
        'attachments': attachments or [],
    }

    if existing:
        tpl_data['id'] = existing['id']
        return update_template(existing['id'], tpl_data)
    else:
        return create_template(tpl_data)


def send_test_email(smtp_profile, to_email, subject, html_body, text_body='',
                    envelope_sender=None, attachments=None):
    """Send a single email via GoPhish's send_test_email utility endpoint.

    Args:
        smtp_profile: Full GoPhish SMTP profile dict (as returned by list/get).
        to_email: Recipient email address.
        subject: Email subject line.
        html_body: HTML body content.
        text_body: Plain text body (optional fallback).
        envelope_sender: Override the profile's from_address (e.g. "Name <user@domain>").
        attachments: Optional list of dicts with 'name', 'content' (base64), 'type' keys.

    Returns:
        API response dict (empty on success, GoPhish returns 200 with empty body).
    """
    # GoPhish requires the template to exist in its DB — create/update it first
    tpl = _ensure_grooming_template(subject, html_body, text_body, attachments=attachments)

    # Build SMTP profile with proper envelope sender if provided
    smtp = dict(smtp_profile)
    if envelope_sender:
        smtp['from_address'] = envelope_sender

    # Note: first_name/last_name in GoPhish payload are the RECIPIENT's name
    # (used for {{.FirstName}}/{{.LastName}} and the To: header).
    # The sender display name is controlled by smtp.from_address.
    payload = {
        'template': {
            'name': _GROOMING_TEMPLATE_NAME,
        },
        'first_name': '',
        'last_name': '',
        'email': to_email,
        'position': '',
        'url': '',
        'page': {
            'name': 'Blank',
            'html': '<html><body></body></html>',
        },
        'smtp': smtp,
    }
    url = _base_url() + '/api/util/send_test_email'
    resp = requests.post(url, headers=_headers(), json=payload, verify=True, timeout=30)
    if resp.status_code >= 400:
        error = resp.text
        try:
            error = resp.json().get('message', resp.text)
        except Exception:
            pass
        raise Exception(f'GoPhish send_test_email error ({resp.status_code}): {error}')
    try:
        return resp.json()
    except Exception:
        return {'success': True}


# ── Campaign CRUD ────────────────────────────────────────────────────────

def list_campaigns():
    return _request('GET', '/api/campaigns/')


def get_campaign(campaign_id):
    return _request('GET', f'/api/campaigns/{campaign_id}')


def get_campaign_results(campaign_id):
    """Get the results/timeline for a GoPhish campaign."""
    return _request('GET', f'/api/campaigns/{campaign_id}/results')


def get_campaign_summary(campaign_id):
    """Get the summary stats for a GoPhish campaign."""
    return _request('GET', f'/api/campaigns/{campaign_id}/summary')


def create_campaign(data):
    """Create and launch a GoPhish campaign.

    Expected data keys:
        name, template (dict with name), url (landing page URL),
        smtp (dict — sending profile), groups (list of group dicts),
        page (dict — landing page), launch_date (optional ISO string),
        send_by_date (optional ISO string).
    """
    return _request('POST', '/api/campaigns/', json=data)


def delete_campaign(campaign_id):
    return _request('DELETE', f'/api/campaigns/{campaign_id}')


def complete_campaign(campaign_id):
    """Mark a GoPhish campaign as complete."""
    return _request('GET', f'/api/campaigns/{campaign_id}/complete')


# ── Groups (target lists in GoPhish) ────────────────────────────────────

def list_groups():
    return _request('GET', '/api/groups/')


def get_group(group_id):
    return _request('GET', f'/api/groups/{group_id}')


def create_group(data):
    """Create a GoPhish group.

    data: {name: str, targets: [{first_name, last_name, email, position}]}
    """
    return _request('POST', '/api/groups/', json=data)


def delete_group(group_id):
    return _request('DELETE', f'/api/groups/{group_id}')


# ── Landing Pages ───────────────────────────────────────────────────────

def list_pages():
    return _request('GET', '/api/pages/')


def get_page(page_id):
    return _request('GET', f'/api/pages/{page_id}')


def create_page(data):
    """Create a GoPhish landing page.

    data: {name, html, capture_credentials (bool), capture_passwords (bool),
           redirect_url (optional)}
    """
    return _request('POST', '/api/pages/', json=data)


def delete_page(page_id):
    return _request('DELETE', f'/api/pages/{page_id}')
