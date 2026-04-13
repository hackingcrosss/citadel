"""Unified asset aggregation across all recon sources (scanner, FOFA, ...).

Merges results from every completed recon source for a project into a single
deduplicated asset list.  Each asset carries a ``sources`` set so consumers
know where it came from.

The public entry point is :func:`aggregate_assets`.
"""

import json
import logging

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def aggregate_assets(project_id, source_filter=''):
    """Return unified assets, extras, and summary for *project_id*.

    Parameters
    ----------
    project_id : int
        Active project.
    source_filter : str
        ``''`` (all), ``'scanner'``, ``'fofa'``, or any future source tag.

    Returns
    -------
    dict
        ``assets``  – list of asset dicts (sources serialised as sorted list)
        ``extras``  – dict with keys like ``emails``, ``breaches`` that don't
                      fit the ip:port:host model
        ``sources`` – sorted list of source tags that contributed data
        ``summary`` – count aggregates
    """
    assets = {}          # key "ip:port:host" -> asset dict
    extras = {
        'emails': [],    # plain email strings
        'breaches': [],  # breach dicts/strings
    }
    active_sources = set()

    if source_filter in ('', 'scanner'):
        _ingest_scanner(project_id, assets, extras, active_sources)

    if source_filter in ('', 'fofa'):
        _ingest_fofa(project_id, assets, active_sources)

    # ── Future sources go here ──────────────────────────────────────
    # if source_filter in ('', 'shodan'):
    #     _ingest_shodan(project_id, assets, extras, active_sources)

    # ── Serialise sets → sorted lists ───────────────────────────────
    result_list = []
    for a in assets.values():
        a['sources'] = sorted(a['sources'])
        a['hostnames'] = sorted(a['hostnames'])
        a['technologies'] = sorted(a['technologies'])
        result_list.append(a)

    result_list.sort(key=lambda x: (x.get('ip', ''), int(x.get('port') or 0)))

    # ── Summary ─────────────────────────────────────────────────────
    unique_ips = len({a['ip'] for a in result_list if a['ip']})
    unique_hosts = len({h for a in result_list for h in a['hostnames']})
    unique_ports = len({a['port'] for a in result_list if a['port'] and a['port'] != '0'})
    countries = {}
    for a in result_list:
        c = a.get('country')
        if c:
            countries[c] = countries.get(c, 0) + 1

    source_counts = {}
    for src in active_sources:
        source_counts[f'{src}_count'] = sum(1 for a in result_list if src in a['sources'])

    summary = {
        'total_assets': len(result_list),
        'unique_ips': unique_ips,
        'unique_hosts': unique_hosts,
        'unique_ports': unique_ports,
        'countries': countries,
        **source_counts,
    }

    return {
        'assets': result_list,
        'extras': extras,
        'sources': sorted(active_sources),
        'summary': summary,
    }


# ---------------------------------------------------------------------------
# Source ingestors (private)
# ---------------------------------------------------------------------------

def _new_asset(ip='', port='', host='', protocol='', title='',
               server='', country='', asn='', last_seen='',
               domain='', service=''):
    return {
        'ip': ip,
        'port': port,
        'host': host,
        'domain': domain,
        'protocol': protocol,
        'title': title,
        'server': server,
        'service': service,
        'country': country,
        'asn': asn,
        'last_seen': last_seen,
        'sources': set(),
        'hostnames': set(),
        'technologies': set(),
    }


def _ingest_scanner(project_id, assets, extras, active_sources):
    """Merge all completed scanner jobs for *project_id* into *assets*."""
    from app.models.ia_scan_job import IAScanJob

    jobs = (
        IAScanJob.query
        .filter_by(project_id=project_id, status='completed')
        .all()
    )
    for job in jobs:
        if not job.raw_results:
            continue
        try:
            results = json.loads(job.raw_results)
        except (json.JSONDecodeError, TypeError):
            continue

        active_sources.add('scanner')

        # Subdomains
        for item in (results.get('subdomains') or []):
            ip = item.get('ip', '')
            host = item.get('name', '')
            if not ip and not host:
                continue
            key = f"{ip}:0:{host}"
            if key not in assets:
                assets[key] = _new_asset(ip=ip, host=host)
            assets[key]['sources'].add('scanner')
            if host:
                assets[key]['hostnames'].add(host)

        # Open ports
        for item in (results.get('open_ports') or []):
            ip = item.get('host', '')
            port = str(item.get('port', ''))
            service = item.get('service', '')
            if not ip:
                continue
            key = f"{ip}:{port}:{ip}"
            if key not in assets:
                assets[key] = _new_asset(ip=ip, port=port)
            assets[key]['sources'].add('scanner')
            if service:
                assets[key]['service'] = service

        # Technologies
        for item in (results.get('technologies') or []):
            host = item.get('host', '')
            tech = item.get('tech', '') or item.get('name', '')
            if not host:
                continue
            matched = False
            for a in assets.values():
                if host in a['hostnames'] or a['ip'] == host:
                    if tech:
                        a['technologies'].add(tech)
                    matched = True
                    break
            if not matched:
                key = f"{host}:0:{host}"
                if key not in assets:
                    assets[key] = _new_asset(ip=host, host=host)
                assets[key]['sources'].add('scanner')
                if tech:
                    assets[key]['technologies'].add(tech)

        # Extras: emails
        for email in (results.get('emails') or []):
            if email and email not in extras['emails']:
                extras['emails'].append(email)

        # Extras: breaches
        for breach in (results.get('breaches') or []):
            extras['breaches'].append(breach)


def _ingest_fofa(project_id, assets, active_sources):
    """Merge all completed FOFA searches for *project_id* into *assets*."""
    from app.models.ia_fofa_search import IAFofaSearch

    searches = (
        IAFofaSearch.query
        .filter_by(project_id=project_id, status='completed')
        .all()
    )
    for search in searches:
        if not search.raw_results:
            continue
        try:
            results = json.loads(search.raw_results)
        except (json.JSONDecodeError, TypeError):
            continue

        active_sources.add('fofa')

        for item in results:
            ip = item.get('ip', '')
            port = str(item.get('port', ''))
            host = item.get('host', '')
            if not ip and not host:
                continue
            key = f"{ip}:{port}:{host}"
            if key not in assets:
                assets[key] = _new_asset(
                    ip=ip, port=port, host=host,
                    protocol=item.get('protocol', ''),
                    title=item.get('title', ''),
                    server=item.get('server', ''),
                    country=item.get('country', ''),
                    asn=item.get('as_organization', ''),
                    last_seen=item.get('lastupdatetime', ''),
                    domain=item.get('domain', ''),
                )
            else:
                a = assets[key]
                if not a.get('protocol') and item.get('protocol'):
                    a['protocol'] = item['protocol']
                if not a.get('title') and item.get('title'):
                    a['title'] = item['title']
                if not a.get('server') and item.get('server'):
                    a['server'] = item['server']
                if not a.get('country') and item.get('country'):
                    a['country'] = item['country']
                if not a.get('asn') and item.get('as_organization'):
                    a['asn'] = item['as_organization']
                if not a.get('last_seen') and item.get('lastupdatetime'):
                    a['last_seen'] = item['lastupdatetime']
                if not a.get('domain') and item.get('domain'):
                    a['domain'] = item['domain']

            assets[key]['sources'].add('fofa')
            if host:
                assets[key]['hostnames'].add(host)
