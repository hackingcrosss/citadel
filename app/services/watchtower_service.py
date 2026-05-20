"""Watchtower service — defender-facing IOC views for white-team users.

Watchtower intentionally exposes a narrow, project-scoped indicator DTO rather
than reusing red-team/internal serializers.  White-team access is constrained to
active projects for the user's company where they are explicitly assigned as a
`white_team` project member.
"""

import csv
import io
import ipaddress
from datetime import datetime
from urllib.parse import urlparse

from flask import abort

from app.models.project import Project, ProjectMember
from app.models.domain import Domain, DNSRecord
from app.models.project_resource import ProjectResource
from app.models.cdn_distribution import CdnDistribution
from app.models.ia_landing_page import IALandingPage
from app.models.ia_campaign import IACampaign
from app.models.phishlet import Phishlet, PhishletDNSRecord


IOC_CSV_FIELDS = [
    'type', 'indicator', 'value', 'record_type', 'category', 'status',
    'source', 'first_seen', 'updated_at', 'project_code', 'project_name',
]


def _iso(dt):
    return dt.isoformat() + 'Z' if dt else None


def _normalise_fqdn(record_name, domain_name):
    name = (record_name or '').strip().rstrip('.')
    domain = (domain_name or '').strip().rstrip('.')
    if not name or name == '@':
        return domain
    if domain and (name == domain or name.endswith('.' + domain)):
        return name
    return f'{name}.{domain}' if domain else name


def _is_ip(value):
    try:
        ipaddress.ip_address(str(value or '').strip())
        return True
    except ValueError:
        return False


def _base_url(url):
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f'{parsed.scheme}://{parsed.netloc}/'


def _host_from_url(url):
    parsed = urlparse(url or '')
    return parsed.netloc or None


def list_watchtower_projects(user):
    """Return active projects visible in Watchtower for this white-team user."""
    if not getattr(user, 'is_white_team', False) or not getattr(user, 'company_id', None):
        return []
    return (
        Project.query
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .filter(
            Project.status == 'active',
            Project.company_id == user.company_id,
            ProjectMember.user_id == user.id,
            ProjectMember.project_role == 'white_team',
        )
        .order_by(Project.name.asc())
        .all()
    )


def assert_watchtower_project(user, project_id):
    """Return project or abort if user cannot access it in Watchtower."""
    project = Project.query.get_or_404(project_id)
    if not getattr(user, 'is_white_team', False) or not getattr(user, 'company_id', None):
        abort(403)
    if project.status != 'active' or project.company_id != user.company_id:
        abort(403)
    member = ProjectMember.query.filter_by(
        project_id=project.id,
        user_id=user.id,
        project_role='white_team',
    ).first()
    if not member:
        abort(403)
    return project


def project_summary(project, iocs=None):
    iocs = collect_project_iocs(project) if iocs is None else iocs
    last_updated = None
    for item in iocs:
        ts = item.get('updated_at') or item.get('first_seen')
        if ts and (last_updated is None or ts > last_updated):
            last_updated = ts
    counts = {}
    for item in iocs:
        counts[item['type']] = counts.get(item['type'], 0) + 1
    return {
        'id': project.id,
        'code': project.code,
        'name': project.name,
        'description': project.description,
        'company_id': project.company_id,
        'company_name': project.company.name if project.company else None,
        'status': project.status,
        'ioc_count': len(iocs),
        'counts': counts,
        'last_ioc_update': last_updated,
        'created_at': _iso(project.created_at),
        'updated_at': _iso(project.updated_at),
    }


def _add(items, seen, project, *, type_, indicator, value='', record_type='',
         category='', status='active', source='', first_seen=None, updated_at=None):
    indicator = str(indicator or '').strip()
    if not indicator:
        return
    value = str(value or '').strip()
    key = (type_, indicator.lower(), value.lower(), record_type, category, source)
    if key in seen:
        return
    seen.add(key)
    items.append({
        'type': type_,
        'indicator': indicator,
        'value': value,
        'record_type': record_type or '',
        'category': category or '',
        'status': status or 'active',
        'source': source or '',
        'first_seen': _iso(first_seen),
        'updated_at': _iso(updated_at),
        'project_id': project.id,
        'project_code': project.code,
        'project_name': project.name,
    })


def collect_project_iocs(project):
    """Collect allowlisted IOC DTOs for a project.

    This deliberately omits internal implementation details such as provider
    credential labels, cloud account labels, Evilginx YAML, GoPhish campaign
    internals, target lists, captured data, task logs, and operator notes.
    """
    items = []
    seen = set()

    # Checked-out root domains and local DNS records.
    domains = Domain.query.filter_by(checkout_project_id=project.id).order_by(Domain.name.asc()).all()
    for domain in domains:
        category = domain.purpose or 'domain'
        _add(
            items, seen, project,
            type_='domain', indicator=domain.name, value='', record_type='',
            category=category, status=domain.status or 'active', source='domain_pool',
            first_seen=domain.checked_out_at or domain.created_at, updated_at=domain.updated_at,
        )
        for rec in DNSRecord.query.filter_by(domain_id=domain.id).order_by(DNSRecord.name.asc()).all():
            if rec.record_type in ('NS', 'SOA'):
                continue
            fqdn = _normalise_fqdn(rec.name, domain.name)
            rec_category = rec.managed_by or category
            _add(
                items, seen, project,
                type_='dns', indicator=fqdn, value=rec.content,
                record_type=rec.record_type, category=rec_category,
                status='active', source='dns_record',
                first_seen=rec.created_at, updated_at=rec.updated_at,
            )
            if rec.record_type in ('A', 'AAAA') and _is_ip(rec.content):
                _add(
                    items, seen, project,
                    type_='ip', indicator=rec.content, value=fqdn,
                    record_type=rec.record_type, category=rec_category,
                    status='active', source='dns_record',
                    first_seen=rec.created_at, updated_at=rec.updated_at,
                )
            elif rec.record_type == 'CNAME' and rec.content:
                _add(
                    items, seen, project,
                    type_='hostname', indicator=rec.content.rstrip('.'), value=fqdn,
                    record_type='CNAME', category=rec_category,
                    status='active', source='dns_record',
                    first_seen=rec.created_at, updated_at=rec.updated_at,
                )

    # Evilginx-created DNS records — expose only observable FQDN/IP/status.
    phishlet_rows = (
        PhishletDNSRecord.query
        .join(Phishlet, PhishletDNSRecord.phishlet_id == Phishlet.id)
        .filter(Phishlet.project_id == project.id)
        .all()
    )
    for rec in phishlet_rows:
        ph = rec.phishlet
        value = ph.target_ip if ph else ''
        _add(
            items, seen, project,
            type_='dns', indicator=rec.fqdn, value=value,
            record_type='A' if _is_ip(value) else '', category='phishing',
            status=rec.status or (ph.status if ph else 'active'), source='evilginx_dns',
            first_seen=rec.created_at, updated_at=ph.updated_at if ph else None,
        )
        if _is_ip(value):
            _add(
                items, seen, project,
                type_='ip', indicator=value, value=rec.fqdn,
                record_type='A', category='phishing',
                status=rec.status or (ph.status if ph else 'active'), source='evilginx_dns',
                first_seen=rec.created_at, updated_at=ph.updated_at if ph else None,
            )

    # Landing pages — expose base host/URL only, not HTML/templates/cloned source.
    for page in IALandingPage.query.filter_by(project_id=project.id).all():
        if page.fqdn:
            _add(
                items, seen, project,
                type_='hostname', indicator=page.fqdn, value='', record_type='',
                category='landing_page', status=page.status or 'active', source='landing_page',
                first_seen=page.created_at, updated_at=page.updated_at,
            )
            _add(
                items, seen, project,
                type_='url', indicator=f'https://{page.fqdn}/', value='', record_type='',
                category='landing_page', status=page.status or 'active', source='landing_page',
                first_seen=page.deployed_at or page.created_at, updated_at=page.updated_at,
            )

    # Campaign phishing URL — reduce to base URL to avoid lure/path disclosure.
    for campaign in IACampaign.query.filter_by(project_id=project.id).all():
        base = _base_url(campaign.phishing_url)
        host = _host_from_url(campaign.phishing_url)
        if host:
            _add(
                items, seen, project,
                type_='hostname', indicator=host, value='', record_type='',
                category='phishing', status=campaign.status or 'active', source='campaign_url',
                first_seen=campaign.scheduled_start or campaign.created_at, updated_at=campaign.updated_at,
            )
        if base:
            _add(
                items, seen, project,
                type_='url', indicator=base, value='', record_type='',
                category='phishing', status=campaign.status or 'active', source='campaign_url',
                first_seen=campaign.scheduled_start or campaign.created_at, updated_at=campaign.updated_at,
            )

    # CDN distributions explicitly tagged to this project.
    cdn_ids = [r.external_id for r in ProjectResource.query.filter_by(project_id=project.id, resource_type='cdn_dist').all()]
    if cdn_ids:
        cdns = CdnDistribution.query.filter(CdnDistribution.id.in_([int(i) for i in cdn_ids if str(i).isdigit()])).all()
        for cdn in cdns:
            if cdn.domain:
                _add(
                    items, seen, project,
                    type_='hostname', indicator=cdn.domain, value='', record_type='',
                    category='cdn', status=cdn.status or 'active', source='cdn_distribution',
                    first_seen=cdn.created_at, updated_at=cdn.updated_at,
                )
            if cdn.origin_host:
                origin_type = 'ip' if _is_ip(cdn.origin_host) else 'hostname'
                _add(
                    items, seen, project,
                    type_=origin_type, indicator=cdn.origin_host, value=cdn.domain or '',
                    record_type='', category='cdn_origin', status=cdn.status or 'active',
                    source='cdn_distribution', first_seen=cdn.created_at, updated_at=cdn.updated_at,
                )

    # Mailgun domains explicitly tagged to this project; DNS records above will
    # carry SPF/DKIM/MX/TXT values when synced locally.
    for r in ProjectResource.query.filter_by(project_id=project.id, resource_type='mailgun_domain').all():
        _add(
            items, seen, project,
            type_='domain', indicator=r.external_id, value='', record_type='',
            category='email', status='active', source='mailgun_domain',
            first_seen=r.tagged_at, updated_at=r.tagged_at,
        )

    type_order = {'domain': 0, 'dns': 1, 'ip': 2, 'hostname': 3, 'url': 4}
    return sorted(items, key=lambda x: (type_order.get(x['type'], 99), x['indicator'].lower(), x['value'].lower()))


def _csv_safe(value):
    value = '' if value is None else str(value)
    if value and value[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + value
    return value


def iocs_to_csv(iocs):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=IOC_CSV_FIELDS, extrasaction='ignore')
    writer.writeheader()
    for item in iocs:
        writer.writerow({k: _csv_safe(item.get(k, '')) for k in IOC_CSV_FIELDS})
    return output.getvalue()


def generated_at():
    return datetime.utcnow().isoformat() + 'Z'
