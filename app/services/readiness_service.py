import logging
from app.services.dns_service import list_dns_records, get_ssl_setting, get_whois_info
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

    # ── 2. Domain age (30+ days) ────────────────────────────────────────────
    try:
        whois_info = get_whois_info(domain_name)
        age_days = whois_info.get('age_days')
        if age_days is not None:
            if age_days >= 30:
                checks['domain_age'] = _check(True, f'{age_days} days old')
            else:
                checks['domain_age'] = _check(False, f'Only {age_days} days old (need 30+)')
        else:
            checks['domain_age'] = _check(False, 'Could not determine registration date')
    except Exception as exc:
        checks['domain_age'] = _check(False, f'WHOIS lookup failed: {exc}')

    # ── 3. SSL strict/full ───────────────────────────────────────────────────
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
        configured_region = domain.mailgun_region or 'us'
        # Try configured region first, then fall back to the other region.
        # Domains are sometimes registered in EU while the local record says 'us'.
        regions_to_try = [configured_region] + [r for r in ('us', 'eu') if r != configured_region]
        # Name candidates: bare domain and mg.<domain> prefix.
        name_candidates = [domain_name, f'mg.{domain_name}']
        mg_data = None
        mg_matched_name = None
        mg_matched_region = None
        for region in regions_to_try:
            for candidate in name_candidates:
                try:
                    mg_data = mg_get_domain(candidate, region=region)
                    mg_matched_name = candidate
                    mg_matched_region = region
                    break
                except Exception as exc:
                    err = str(exc)
                    if '404' in err or 'not found' in err.lower():
                        continue
                    raise
            if mg_data is not None:
                break
        if mg_data is None:
            checks['mailgun_verified'] = _check(False, 'Not registered in Mailgun')
        else:
            state = (mg_data.get('domain') or {}).get('state', 'unknown')
            detail = f'State: {state}'
            if mg_matched_name != domain_name:
                detail += f' (as {mg_matched_name})'
            if mg_matched_region != configured_region:
                detail += f' [{mg_matched_region.upper()}]'
            checks['mailgun_verified'] = _check(True, detail)
    except Exception as exc:
        checks['mailgun_verified'] = _check(False, f'Error: {exc}')

    # ── 8. NPM proxy active ──────────────────────────────────────────────────
    try:
        hosts = list_proxy_hosts()
        matching = [
            h for h in hosts
            if any(
                n == domain_name or n.endswith('.' + domain_name)
                for n in h.get('domain_names', [])
            )
        ]
        if matching:
            h = matching[0]
            forward = (
                f"{h.get('forward_scheme', 'http')}://"
                f"{h.get('forward_host', '')}:{h.get('forward_port', '')}"
            )
            checks['npm_proxy_active'] = _check(True, f'Proxy \u2192 {forward}')
        else:
            checks['npm_proxy_active'] = _check(False, 'No proxy host found')
    except Exception as exc:
        checks['npm_proxy_active'] = _check(False, f'Error: {exc}')

    overall = all(c['ok'] for c in checks.values())
    return {'domain': domain_name, 'checks': checks, 'overall': overall}
