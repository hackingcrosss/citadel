import logging
from app.services.dns_service import list_dns_records, get_ssl_setting
from app.services.email_service import get_domain as mg_get_domain
from app.services.npm_service import list_proxy_hosts

_log = logging.getLogger(__name__)


def _check(ok, detail):
    return {'ok': ok, 'detail': detail}


def check_domain_readiness(domain):
    """Run all readiness checks for a project-checked-out domain.

    Checks:
      - dns_a_record:      root A record exists in Cloudflare
      - ssl_strict:        CF SSL mode is 'full' or 'strict'
      - spf:               TXT record with v=spf1 exists
      - dkim:              TXT record with v=DKIM1 / k=rsa exists
      - mailgun_verified:  domain state is 'active' in Mailgun
      - npm_proxy_active:  enabled NPM proxy host found for this domain

    Returns:
        {'domain': str, 'checks': {name: {ok, detail}}, 'overall': bool}
    """
    zone_id = domain.cloudflare_zone_id
    label = domain.credential_label or 'default'
    domain_name = domain.name
    checks = {}

    # Fetch all CF DNS records in one request — used for A, SPF, DKIM checks.
    cf_records = []
    cf_error = None
    if zone_id:
        try:
            cf_records = list_dns_records(zone_id, label=label)
        except Exception as exc:
            cf_error = str(exc)

    # ── 1. DNS A record ──────────────────────────────────────────────────────
    if not zone_id:
        checks['dns_a_record'] = _check(False, 'No Cloudflare zone ID')
    elif cf_error:
        checks['dns_a_record'] = _check(False, f'CF error: {cf_error}')
    else:
        root_a = [r for r in cf_records
                  if r.get('type') == 'A' and r.get('name') in (domain_name, '@')]
        if root_a:
            checks['dns_a_record'] = _check(True, f"A \u2192 {root_a[0]['content']}")
        else:
            checks['dns_a_record'] = _check(False, 'No root A record found')

    # ── 2. SSL strict/full ───────────────────────────────────────────────────
    if not zone_id:
        checks['ssl_strict'] = _check(False, 'No Cloudflare zone ID')
    elif cf_error:
        checks['ssl_strict'] = _check(False, f'CF error: {cf_error}')
    else:
        try:
            ssl = get_ssl_setting(zone_id, label=label)
            mode = ssl.get('value', 'unknown')
            checks['ssl_strict'] = _check(mode in ('full', 'strict'), f'SSL mode: {mode}')
        except Exception as exc:
            checks['ssl_strict'] = _check(False, f'Error: {exc}')

    # ── 3. SPF record ────────────────────────────────────────────────────────
    if not zone_id or cf_error:
        checks['spf'] = _check(
            False, f'CF error: {cf_error}' if cf_error else 'No Cloudflare zone ID'
        )
    else:
        txt_recs = [r for r in cf_records if r.get('type') == 'TXT']
        spf = next((r for r in txt_recs if 'v=spf1' in r.get('content', '')), None)
        if spf:
            detail = spf['content']
            if len(detail) > 80:
                detail = detail[:77] + '\u2026'
            checks['spf'] = _check(True, detail)
        else:
            checks['spf'] = _check(False, 'No SPF TXT record found')

    # ── 4. DKIM record ───────────────────────────────────────────────────────
    if not zone_id or cf_error:
        checks['dkim'] = _check(
            False, f'CF error: {cf_error}' if cf_error else 'No Cloudflare zone ID'
        )
    else:
        txt_recs = [r for r in cf_records if r.get('type') == 'TXT']
        dkim = next(
            (r for r in txt_recs
             if 'v=DKIM1' in r.get('content', '') or 'k=rsa' in r.get('content', '')),
            None,
        )
        if dkim:
            checks['dkim'] = _check(True, f'Found on: {dkim["name"]}')
        else:
            checks['dkim'] = _check(False, 'No DKIM TXT record found')

    # ── 5. DMARC record ──────────────────────────────────────────────────────
    if not zone_id or cf_error:
        checks['dmarc'] = _check(
            False, f'CF error: {cf_error}' if cf_error else 'No Cloudflare zone ID'
        )
    else:
        txt_recs = [r for r in cf_records if r.get('type') == 'TXT']
        dmarc = next(
            (r for r in txt_recs if 'v=DMARC1' in r.get('content', '')),
            None,
        )
        if dmarc:
            detail = dmarc['content']
            if len(detail) > 80:
                detail = detail[:77] + '\u2026'
            checks['dmarc'] = _check(True, detail)
        else:
            checks['dmarc'] = _check(False, 'No _dmarc TXT record found')

    # ── 7. Mailgun verified ──────────────────────────────────────────────────
    try:
        region = domain.mailgun_region or 'us'
        mg_data = mg_get_domain(domain_name, region=region)
        state = (mg_data.get('domain') or {}).get('state', 'unknown')
        checks['mailgun_verified'] = _check(state == 'active', f'State: {state}')
    except Exception as exc:
        err = str(exc)
        if '404' in err or 'not found' in err.lower():
            checks['mailgun_verified'] = _check(False, 'Not registered in Mailgun')
        else:
            checks['mailgun_verified'] = _check(False, f'Error: {exc}')

    # ── 8. NPM proxy active ──────────────────────────────────────────────────
    try:
        hosts = list_proxy_hosts()
        matching = [h for h in hosts if domain_name in h.get('domain_names', [])]
        enabled = [h for h in matching if h.get('enabled', False)]
        if enabled:
            h = enabled[0]
            forward = (
                f"{h.get('forward_scheme', 'http')}://"
                f"{h.get('forward_host', '')}:{h.get('forward_port', '')}"
            )
            checks['npm_proxy_active'] = _check(True, f'Proxy \u2192 {forward}')
        elif matching:
            checks['npm_proxy_active'] = _check(False, 'Proxy host exists but is disabled')
        else:
            checks['npm_proxy_active'] = _check(False, 'No proxy host found')
    except Exception as exc:
        checks['npm_proxy_active'] = _check(False, f'Error: {exc}')

    overall = all(c['ok'] for c in checks.values())
    return {'domain': domain_name, 'checks': checks, 'overall': overall}
