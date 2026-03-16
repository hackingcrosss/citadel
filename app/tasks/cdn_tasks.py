import logging

from app.tasks.celery_app import celery

_log = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=0, time_limit=600, soft_time_limit=570)
def create_cdn_distribution_task(self, dist_id, provider, origin_host, origin_port,
                                  comment, account_label, resource_group=None):
    """
    Background task for CDN distribution creation.
    The DB record is pre-created with status='creating' and external_id='task:<task_id>'.
    On success: updates external_id, domain, status='deploying'.
    On failure: sets status='error', external_id='error:<message>'.

    For Azure Front Door the creation involves multiple sequential steps (profile,
    endpoint, origin group, origin, route).  We update the DB record as soon as the
    endpoint is created so the frontend can display the domain and 'deploying' status
    while the remaining steps continue in the background.
    """
    from app import db
    from app.models.cdn_distribution import CdnDistribution
    from app.services import cdn_service

    dist = CdnDistribution.query.get(dist_id)
    if not dist:
        return {'error': 'Distribution record not found'}

    try:
        if provider == 'cloudfront':
            result = cdn_service.create_cloudfront_distribution(
                origin_host, origin_port, comment, label=account_label
            )
            dist.external_id = result['external_id']
            dist.domain = result['domain']
            dist.status = result.get('status', 'deploying')
            db.session.commit()
            return {'external_id': result['external_id'], 'domain': result['domain'], 'status': dist.status}

        # --- Azure Front Door: progressive DB updates ---
        result = _create_afd_progressive(
            dist, db, cdn_service,
            resource_group, origin_host, origin_port, comment, account_label,
        )
        return result

    except Exception as exc:
        # Refresh dist in case the session is stale after a partial commit
        db.session.rollback()
        dist = CdnDistribution.query.get(dist_id)
        if dist:
            dist.status = 'error'
            # Keep any external_id/domain that was already set
            if not dist.external_id or dist.external_id.startswith('task:'):
                dist.external_id = f'error:{str(exc)[:400]}'
            db.session.commit()
        raise


def _create_afd_progressive(dist, db, cdn_service,
                             resource_group, origin_host, origin_port,
                             comment, account_label):
    """Create AFD distribution with intermediate DB updates so the frontend
    can show progress as soon as the endpoint (domain) is available."""
    import re
    import secrets
    import time
    from azure.mgmt.cdn.models import (
        Profile, Sku,
        AFDEndpoint,
        AFDOriginGroup, LoadBalancingSettingsParameters, HealthProbeParameters,
        AFDOrigin,
        Route,
    )

    client, subscription_id = cdn_service._get_afd_client(label=account_label)

    profile_name = cdn_service._afd_profile_name()
    safe = re.sub(r'[^a-z0-9]', '-', origin_host.lower())[:20].strip('-')
    rand = secrets.token_hex(4)
    endpoint_name     = f"ep-{safe}-{rand}"[:63].strip('-')
    origin_group_name = f"og-{safe}"[:63].strip('-')
    origin_name       = f"origin-{safe}"[:63].strip('-')
    route_name        = 'default-route'

    # 1. Create profile
    _log.info("Creating AFD profile '%s'...", profile_name)
    client.profiles.begin_create(
        resource_group, profile_name,
        Profile(location='global', sku=Sku(name='Standard_AzureFrontDoor')),
    ).wait()
    cdn_service._afd_wait_succeeded(
        lambda: client.profiles.get(resource_group, profile_name),
        f"profile/{profile_name}",
    )

    # 2. Create endpoint — once done, update DB with domain so frontend sees it
    _log.info("Creating AFD endpoint '%s'...", endpoint_name)
    client.afd_endpoints.begin_create(
        resource_group, profile_name, endpoint_name,
        AFDEndpoint(location='global', enabled_state='Enabled'),
    ).wait()
    ep = cdn_service._afd_wait_succeeded(
        lambda: client.afd_endpoints.get(resource_group, profile_name, endpoint_name),
        f"endpoint/{endpoint_name}",
    )

    # ---- Early DB update: domain is now known ----
    ext_id = f"{resource_group}/{profile_name}/{endpoint_name}"
    dist.external_id = ext_id
    dist.domain = ep.host_name or ''
    dist.status = 'deploying'
    db.session.commit()
    _log.info("AFD endpoint ready: %s — DB updated to 'deploying'", ep.host_name)

    # 3. Create origin group
    _log.info("Creating AFD origin group '%s'...", origin_group_name)
    client.afd_origin_groups.begin_create(
        resource_group, profile_name, origin_group_name,
        AFDOriginGroup(
            load_balancing_settings=LoadBalancingSettingsParameters(
                sample_size=4,
                successful_samples_required=3,
                additional_latency_in_milliseconds=50,
            ),
            health_probe_settings=HealthProbeParameters(
                probe_path='/',
                probe_protocol='NotSet',
                probe_interval_in_seconds=100,
            ),
        ),
    ).wait()
    cdn_service._afd_wait_succeeded(
        lambda: client.afd_origin_groups.get(resource_group, profile_name, origin_group_name),
        f"origin-group/{origin_group_name}",
    )

    # 4. Create origin
    _origin_http_port  = origin_port if origin_port != 443 else 80
    _origin_https_port = origin_port if origin_port == 443 else 443
    _log.info("Creating AFD origin '%s' -> %s:%s", origin_name, origin_host, origin_port)
    client.afd_origins.begin_create(
        resource_group, profile_name, origin_group_name, origin_name,
        AFDOrigin(
            host_name=origin_host,
            http_port=_origin_http_port,
            https_port=_origin_https_port,
            origin_host_header=origin_host,
            priority=1,
            weight=1000,
            enabled_state='Enabled',
            enforce_certificate_name_check=False,
        ),
    ).wait()
    cdn_service._afd_wait_succeeded(
        lambda: client.afd_origins.get(resource_group, profile_name, origin_group_name, origin_name),
        f"origin/{origin_name}",
    )

    # 5. Create route
    origin_group_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Cdn/profiles/{profile_name}"
        f"/originGroups/{origin_group_name}"
    )
    forwarding_protocol = 'HttpsOnly' if origin_port == 443 else 'HttpOnly'
    _log.info("Creating AFD route '%s'...", route_name)
    client.routes.begin_create(
        resource_group, profile_name, endpoint_name, route_name,
        Route(
            origin_group={'id': origin_group_id},
            supported_protocols=['Http', 'Https'],
            patterns_to_match=['/*'],
            forwarding_protocol=forwarding_protocol,
            https_redirect='Disabled',
            link_to_default_domain='Enabled',
            enabled_state='Enabled',
        ),
    ).wait()
    cdn_service._afd_wait_succeeded(
        lambda: client.routes.get(resource_group, profile_name, endpoint_name, route_name),
        f"route/{route_name}",
    )

    _log.info("AFD distribution fully provisioned: %s", ext_id)
    return {'external_id': ext_id, 'domain': ep.host_name or '', 'status': 'deploying'}
