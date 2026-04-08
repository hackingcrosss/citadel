"""Discoveries API — unified view of assets found by scanner + FOFA."""

import json
import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services.project_service import get_active_project
from app.utils.decorators import feature_required

_log = logging.getLogger(__name__)


@api_bp.route('/ia/discoveries', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_discoveries():
    """Return a unified, deduplicated asset list from all recon sources.

    Query params:
        source  - filter: 'scanner', 'fofa', or omit for both
    """
    from app.models.ia_scan_job import IAScanJob
    from app.models.ia_fofa_search import IAFofaSearch

    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    source_filter = request.args.get('source', '').lower()

    assets = {}  # key = "ip:port" -> merged asset dict

    # ── Scanner results ──────────────────────────────────────────────
    if source_filter in ('', 'scanner'):
        scan_jobs = (
            IAScanJob.query
            .filter_by(project_id=project.id, status='completed')
            .all()
        )
        for job in scan_jobs:
            if not job.raw_results:
                continue
            try:
                results = json.loads(job.raw_results)
            except (json.JSONDecodeError, TypeError):
                continue

            # Subdomains — have name + ip
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

            # Open ports — have host, port, service
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

            # Technologies — have host, tech, version
            for item in (results.get('technologies') or []):
                host = item.get('host', '')
                tech = item.get('tech', '')
                if not host:
                    continue
                # Find existing asset for this host or create placeholder
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

    # ── FOFA results ─────────────────────────────────────────────────
    if source_filter in ('', 'fofa'):
        fofa_searches = (
            IAFofaSearch.query
            .filter_by(project_id=project.id, status='completed')
            .all()
        )
        for search in fofa_searches:
            if not search.raw_results:
                continue
            try:
                results = json.loads(search.raw_results)
            except (json.JSONDecodeError, TypeError):
                continue

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
                    # Enrich with FOFA data if missing
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

    # ── Serialize ────────────────────────────────────────────────────
    result_list = []
    for a in assets.values():
        a['sources'] = sorted(a['sources'])
        a['hostnames'] = sorted(a['hostnames'])
        a['technologies'] = sorted(a['technologies'])
        result_list.append(a)

    # Sort: by IP, then port
    result_list.sort(key=lambda x: (x.get('ip', ''), int(x.get('port') or 0)))

    # Build summary stats
    unique_ips = len({a['ip'] for a in result_list if a['ip']})
    unique_hosts = len({h for a in result_list for h in a['hostnames']})
    unique_ports = len({a['port'] for a in result_list if a['port'] and a['port'] != '0'})
    countries = {}
    for a in result_list:
        c = a.get('country')
        if c:
            countries[c] = countries.get(c, 0) + 1

    return jsonify({
        'assets': result_list,
        'summary': {
            'total_assets': len(result_list),
            'unique_ips': unique_ips,
            'unique_hosts': unique_hosts,
            'unique_ports': unique_ports,
            'countries': countries,
            'scanner_count': sum(1 for a in result_list if 'scanner' in a['sources']),
            'fofa_count': sum(1 for a in result_list if 'fofa' in a['sources']),
        },
    })


def _new_asset(ip='', port='', host='', protocol='', title='',
               server='', country='', asn='', last_seen='', domain='', service=''):
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
