"""ia_landing_service.py — Landing page deployment and lifecycle.

Wraps the Docker + NPM + DNS deploy pattern used by the website generator,
adapted for credential-harvest and payload-delivery landing pages.
Also bridges to GoPhish landing page API for campaign integration.
"""

import logging
from datetime import datetime

from app import db
from app.models.ia_landing_page import IALandingPage
from app.services import gophish_service

_log = logging.getLogger(__name__)

_VALID_PAGE_TYPES = {'cred_harvest', 'payload_delivery', 'redirect', 'awareness'}
_VALID_SOURCES = {'manual', 'clone', 'gophish'}
_EDITABLE_FIELDS = {'name', 'page_type', 'domain_id', 'template_source', 'clone_url',
                    'html_content', 'capture_credentials', 'capture_passwords',
                    'redirect_url'}


# ── CRUD ────────────────────────────────────────────────────────────────

def list_landing_pages(project_id, status=None):
    q = IALandingPage.query.filter_by(project_id=project_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(IALandingPage.created_at.desc()).all()


def get_landing_page(page_id):
    return IALandingPage.query.get(page_id)


def create_landing_page(project_id, data, user_id):
    page_type = data.get('page_type', 'cred_harvest')
    if page_type not in _VALID_PAGE_TYPES:
        raise ValueError(f'Invalid page type: {page_type}')

    source = data.get('template_source', 'manual')
    if source not in _VALID_SOURCES:
        raise ValueError(f'Invalid template source: {source}')

    page = IALandingPage(
        project_id=project_id,
        name=data['name'][:200],
        page_type=page_type,
        template_source=source,
        clone_url=data.get('clone_url', '')[:500] if data.get('clone_url') else None,
        html_content=data.get('html_content'),
        domain_id=data.get('domain_id'),
        capture_credentials=data.get('capture_credentials', True),
        capture_passwords=data.get('capture_passwords', False),
        redirect_url=data.get('redirect_url', '')[:500] if data.get('redirect_url') else None,
        deployed_by_id=user_id,
    )
    db.session.add(page)
    db.session.commit()
    return page


def update_landing_page(page, data):
    if page.status not in ('draft', 'error'):
        raise ValueError('Can only edit pages in draft or error status')

    for field in _EDITABLE_FIELDS:
        if field not in data:
            continue
        val = data[field]
        if field == 'page_type' and val not in _VALID_PAGE_TYPES:
            raise ValueError(f'Invalid page type: {val}')
        if field == 'template_source' and val not in _VALID_SOURCES:
            raise ValueError(f'Invalid template source: {val}')
        if field == 'name' and val:
            val = str(val)[:200]
        if field in ('clone_url', 'redirect_url') and val:
            val = str(val)[:500]
        setattr(page, field, val)

    page.updated_at = datetime.utcnow()
    db.session.commit()
    return page


# ── Deploy pipeline ─────────────────────────────────────────────────────

def deploy_landing_page(page):
    """Deploy a landing page via Docker + NPM + DNS.

    Steps:
    1. Validate page has HTML and domain
    2. Deploy HTML to NPM host via website_generator's deploy pattern
    3. Create NPM proxy host
    4. Create DNS record
    5. Optionally push to GoPhish as a landing page
    6. Update page status to 'live'

    Returns list of step results.
    """
    from app.services import website_generator_service, npm_service, dns_service
    from app.services.credential_service import get_credential
    from app.services.project_service import tag_resource

    if page.status == 'live':
        raise ValueError('Page is already deployed')

    if not page.html_content:
        raise ValueError('Page has no HTML content')

    if not page.domain_id or not page.domain:
        raise ValueError('No domain configured for this page')

    page.status = 'deploying'
    db.session.commit()

    steps = []
    domain = page.domain

    # Derive subdomain from page name
    import re, random, string
    slug = re.sub(r'[^a-z0-9]+', '-', page.name.lower()).strip('-') or 'lp'
    suffix = ''.join(random.choices(string.digits, k=4))
    folder_name = f'lp-{slug}-{suffix}'

    # Step 1: Deploy HTML files
    try:
        deploy_result = website_generator_service.deploy_website(page.html_content, folder_name)
        page.container_name = deploy_result['folder']
        tag_resource(page.project_id, 'container', page.container_name, page.name, page.deployed_by_id)
        tag_resource(page.project_id, 'website_gen_site', page.container_name, page.name, page.deployed_by_id)
        steps.append({'step': 'deploy_files', 'status': 'ok', 'folder': page.container_name})
    except Exception as e:
        page.status = 'error'
        db.session.commit()
        steps.append({'step': 'deploy_files', 'status': 'error', 'error': str(e)})
        return steps

    # Step 2: Start container
    try:
        service_name = f'nginx_{page.container_name}'
        website_generator_service.start_container(service_name)
        steps.append({'step': 'start_container', 'status': 'ok'})
    except Exception as e:
        steps.append({'step': 'start_container', 'status': 'error', 'error': str(e)})

    # Step 3: Create NPM proxy host
    # Use first available subdomain pattern for this domain
    fqdn = f'{page.container_name}.{domain.name}'
    page.fqdn = fqdn

    try:
        proxy = npm_service.create_proxy_host(
            domain_names=[fqdn],
            forward_host=page.container_name,
            forward_port=80,
        )
        page.npm_host_id = proxy.get('id')
        if page.npm_host_id is not None:
            tag_resource(page.project_id, 'npm_host', str(page.npm_host_id), fqdn, page.deployed_by_id)
        steps.append({'step': 'npm_proxy', 'status': 'ok', 'proxy_id': page.npm_host_id})
    except Exception as e:
        steps.append({'step': 'npm_proxy', 'status': 'error', 'error': str(e)})

    # Step 4: Cloudflare DNS A record
    try:
        npm_public_ip = get_credential('npm', 'public_ip')
        if not npm_public_ip:
            raise ValueError('NPM Public IP not configured')

        zone_id = domain.cloudflare_zone_id
        if not zone_id:
            raise ValueError('Domain has no Cloudflare zone ID')

        dns_record = dns_service.create_dns_record(
            zone_id=zone_id,
            record_type='A',
            name=page.container_name,
            content=npm_public_ip,
            ttl=1,
            proxied=True,
        )
        steps.append({'step': 'dns_record', 'status': 'ok',
                      'record_id': dns_record.get('id')})
    except Exception as e:
        steps.append({'step': 'dns_record', 'status': 'error', 'error': str(e)})

    # Step 5: Push to GoPhish as landing page (for campaign linking)
    try:
        gp_page = gophish_service.create_page({
            'name': f'Citadel: {page.name[:150]}',
            'html': page.html_content,
            'capture_credentials': page.capture_credentials,
            'capture_passwords': page.capture_passwords,
            'redirect_url': page.redirect_url or '',
        })
        page.gophish_page_id = gp_page.get('id')
        steps.append({'step': 'gophish_page', 'status': 'ok',
                      'gophish_id': page.gophish_page_id})
    except Exception as e:
        # GoPhish push is optional — page can still be live without it
        steps.append({'step': 'gophish_page', 'status': 'error', 'error': str(e)})

    # Determine final status
    critical_failed = any(s['status'] == 'error' for s in steps
                          if s['step'] in ('deploy_files', 'start_container'))
    if critical_failed:
        page.status = 'error'
    else:
        page.status = 'live'
        page.deployed_at = datetime.utcnow()

    db.session.commit()
    _log.info('Landing page %s deploy: %s (fqdn=%s)', page.id, page.status, page.fqdn)
    return steps


# ── Teardown ────────────────────────────────────────────────────────────

def teardown_landing_page(page):
    """Tear down a deployed landing page.

    Removes: container, NPM proxy host, DNS record, GoPhish page.
    Returns list of step results.
    """
    from app.services import website_generator_service, npm_service, dns_service

    steps = []

    # Stop and remove container
    if page.container_name:
        try:
            website_generator_service.remove_deployed_site(page.container_name)
            steps.append({'step': 'remove_container', 'status': 'ok'})
        except Exception as e:
            steps.append({'step': 'remove_container', 'status': 'error', 'error': str(e)})

    # Remove NPM proxy host
    if page.npm_host_id:
        try:
            npm_service.delete_proxy_host(page.npm_host_id)
            steps.append({'step': 'remove_npm', 'status': 'ok'})
        except Exception as e:
            steps.append({'step': 'remove_npm', 'status': 'error', 'error': str(e)})

    # Remove DNS record (find by FQDN)
    if page.fqdn and page.domain and page.domain.cloudflare_zone_id:
        try:
            zone_id = page.domain.cloudflare_zone_id
            records = dns_service.list_dns_records(zone_id)
            for r in records:
                if r.get('name', '').lower() == page.fqdn.lower():
                    dns_service.delete_dns_record(zone_id, r['id'])
                    steps.append({'step': 'remove_dns', 'status': 'ok'})
                    break
            else:
                steps.append({'step': 'remove_dns', 'status': 'ok', 'note': 'No record found'})
        except Exception as e:
            steps.append({'step': 'remove_dns', 'status': 'error', 'error': str(e)})

    # Remove GoPhish landing page
    if page.gophish_page_id:
        try:
            gophish_service.delete_page(page.gophish_page_id)
            steps.append({'step': 'remove_gophish', 'status': 'ok'})
        except Exception as e:
            steps.append({'step': 'remove_gophish', 'status': 'error', 'error': str(e)})

    page.status = 'torn_down'
    page.torn_down_at = datetime.utcnow()
    db.session.commit()

    _log.info('Landing page %s torn down', page.id)
    return steps
