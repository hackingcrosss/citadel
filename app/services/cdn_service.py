import logging
import re
import secrets
import time
from app.services.credential_service import get_credential, get_account_labels

_log = logging.getLogger(__name__)

_CITADEL_TAG = 'citadel-managed'


# ---------------------------------------------------------------------------
# CloudFront helpers
# ---------------------------------------------------------------------------

def _get_cf_client(label='default'):
    import boto3
    access_key = get_credential('aws', 'access_key_id', label=label)
    secret_key = get_credential('aws', 'secret_access_key', label=label)
    if not access_key or not secret_key:
        raise ValueError(f"AWS credentials not configured for account '{label}'. Set them in Settings.")
    return boto3.client(
        'cloudfront',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name='us-east-1',   # CloudFront is global but API is us-east-1
    )


def list_cloudfront_distributions(label='default'):
    client = _get_cf_client(label)
    paginator = client.get_paginator('list_distributions')
    results = []
    for page in paginator.paginate():
        items = page.get('DistributionList', {}).get('Items', [])
        for d in items:
            origins = d.get('Origins', {}).get('Items', [])
            origin_host = origins[0].get('DomainName', '') if origins else ''
            results.append({
                'external_id': d['Id'],
                'domain': d.get('DomainName', ''),
                'status': 'deployed' if d.get('Status') == 'Deployed' else 'deploying',
                'origin_host': origin_host,
                'comment': d.get('Comment', ''),
                'account_label': label,
                'provider': 'cloudfront',
            })
    return results


def list_cf_all_accounts():
    labels = get_account_labels('aws')
    results = []
    for lbl in labels:
        try:
            dists = list_cloudfront_distributions(lbl)
            results.extend(dists)
        except Exception as exc:
            _log.warning("CloudFront list failed for account '%s': %s", lbl, exc)
    return results


def create_cloudfront_distribution(origin_host, origin_port, comment, label='default'):
    client = _get_cf_client(label)
    origin_id = f"citadel-{origin_host.replace('.', '-').replace(':', '-')}"
    caller_ref = f"citadel-{int(time.time())}"

    protocol = 'https-only' if origin_port == 443 else 'http-only'

    config = {
        'CallerReference': caller_ref,
        'Comment': comment or '',
        'Origins': {
            'Quantity': 1,
            'Items': [{
                'Id': origin_id,
                'DomainName': origin_host,
                'CustomOriginConfig': {
                    'HTTPPort': 80,
                    'HTTPSPort': origin_port,
                    'OriginProtocolPolicy': protocol,
                    'OriginSSLProtocols': {'Quantity': 1, 'Items': ['TLSv1.2']},
                },
            }],
        },
        'DefaultCacheBehavior': {
            'TargetOriginId': origin_id,
            'ViewerProtocolPolicy': 'allow-all',
            'AllowedMethods': {
                'Quantity': 7,
                'Items': ['GET', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'POST', 'DELETE'],
                'CachedMethods': {'Quantity': 2, 'Items': ['GET', 'HEAD']},
            },
            'ForwardedValues': {
                'QueryString': True,
                'Cookies': {'Forward': 'all'},
                'Headers': {'Quantity': 1, 'Items': ['*']},
            },
            'MinTTL': 0,
            'DefaultTTL': 0,
            'MaxTTL': 0,
            'Compress': False,
        },
        'Enabled': True,
        'PriceClass': 'PriceClass_100',
    }

    resp = client.create_distribution(DistributionConfig=config)
    dist = resp['Distribution']
    return {
        'external_id': dist['Id'],
        'domain': dist['DomainName'],
        'status': 'deploying' if dist['Status'] == 'InProgress' else 'deployed',
        'etag': resp['ETag'],
    }


def get_cloudfront_distribution(dist_id, label='default'):
    client = _get_cf_client(label)
    resp = client.get_distribution(Id=dist_id)
    dist = resp['Distribution']
    return {
        'external_id': dist['Id'],
        'domain': dist['DomainName'],
        'status': 'deployed' if dist['Status'] == 'Deployed' else 'deploying',
        'enabled': dist['DistributionConfig'].get('Enabled', True),
        'etag': resp['ETag'],
    }


def disable_cloudfront_distribution(dist_id, label='default'):
    """Set Enabled=False. CloudFront requires this before delete. Returns (status, new_etag)."""
    client = _get_cf_client(label)
    resp = client.get_distribution_config(Id=dist_id)
    etag = resp['ETag']
    config = resp['DistributionConfig']
    if not config.get('Enabled', True):
        # Already disabled — get current ETag from get_distribution
        r2 = client.get_distribution(Id=dist_id)
        return r2['Distribution']['Status'], r2['ETag']
    config['Enabled'] = False
    resp2 = client.update_distribution(Id=dist_id, DistributionConfig=config, IfMatch=etag)
    return resp2['Distribution']['Status'], resp2['ETag']


def update_cloudfront_origin(dist_id, origin_host, origin_port, comment, label='default'):
    """Update the origin host/port on an existing CloudFront distribution."""
    client = _get_cf_client(label)
    resp = client.get_distribution_config(Id=dist_id)
    etag = resp['ETag']
    config = resp['DistributionConfig']

    new_origin_id = f"citadel-{origin_host.replace('.', '-').replace(':', '-')}"
    protocol = 'https-only' if origin_port == 443 else 'http-only'

    origins = config.get('Origins', {}).get('Items', [])
    if origins:
        origins[0]['Id'] = new_origin_id
        origins[0]['DomainName'] = origin_host
        origins[0]['CustomOriginConfig']['HTTPSPort'] = origin_port
        origins[0]['CustomOriginConfig']['OriginProtocolPolicy'] = protocol
        config['Origins']['Items'] = origins
        config['Origins']['Quantity'] = len(origins)

    config['DefaultCacheBehavior']['TargetOriginId'] = new_origin_id
    if comment is not None:
        config['Comment'] = comment

    client.update_distribution(Id=dist_id, DistributionConfig=config, IfMatch=etag)


def delete_cloudfront_distribution(dist_id, etag, label='default'):
    """Delete a CloudFront distribution. Must be disabled and Deployed first."""
    client = _get_cf_client(label)
    client.delete_distribution(Id=dist_id, IfMatch=etag)
    return {'deleted': dist_id}


# ---------------------------------------------------------------------------
# Azure Front Door helpers
# ---------------------------------------------------------------------------

def _afd_profile_name():
    """Generate a unique AFD profile name: citadel-cdn-<8 random hex chars>.
    Each distribution gets its own profile so a failed creation never blocks the next one.
    """
    return f"citadel-cdn-{secrets.token_hex(4)}"


def _get_afd_client(label='default'):
    from azure.identity import ClientSecretCredential
    from azure.mgmt.cdn import CdnManagementClient
    tenant_id = get_credential('azure', 'tenant_id', label=label)
    client_id = get_credential('azure', 'client_id', label=label)
    client_secret = get_credential('azure', 'client_secret', label=label)
    subscription_id = get_credential('azure', 'subscription_id', label=label)
    if not all([tenant_id, client_id, client_secret, subscription_id]):
        raise ValueError(f"Azure credentials not fully configured for account '{label}'.")
    cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    return CdnManagementClient(cred, subscription_id), subscription_id


def list_afd_distributions(resource_group, label='default'):
    client, _ = _get_afd_client(label)
    results = []
    try:
        profiles = list(client.profiles.list_by_resource_group(resource_group))
    except Exception:
        return results
    for profile in profiles:
        if not (profile.sku and 'FrontDoor' in (profile.sku.name or '')):
            continue
        profile_name = profile.name
        try:
            endpoints = list(client.afd_endpoints.list_by_profile(resource_group, profile_name))
        except Exception:
            continue
        for ep in endpoints:
                # Resolve first origin host for display (best-effort)
                origin_host = ''
                try:
                    ogs = list(client.afd_origin_groups.list_by_profile(resource_group, profile_name))
                    if ogs:
                        origins = list(client.afd_origins.list_by_origin_group(
                            resource_group, profile_name, ogs[0].name))
                        if origins:
                            origin_host = origins[0].host_name or ''
                except Exception:
                    pass
                results.append({
                    'external_id': f"{resource_group}/{profile_name}/{ep.name}",
                    'domain': ep.host_name or '',
                    'status': 'deployed' if str(ep.deployment_status or '').lower() == 'succeeded' else 'deploying',
                    'origin_host': origin_host,
                    'account_label': label,
                    'provider': 'azure_front_door',
                })
    return results


def list_afd_all_accounts(resource_group=None):
    labels = get_account_labels('azure')
    results = []
    for lbl in labels:
        try:
            # If no RG given, enumerate all RGs
            if resource_group:
                rgs = [resource_group]
            else:
                from app.services.azure_service import list_resource_groups
                rgs = list_resource_groups(label=lbl)
            for rg in rgs:
                results.extend(list_afd_distributions(rg, label=lbl))
        except Exception as exc:
            _log.warning("AFD list failed for account '%s': %s", lbl, exc)
    return results


def _afd_wait_succeeded(poll_fn, resource_desc, timeout=300, interval=10):
    """Poll poll_fn() until provisioning_state == Succeeded or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            obj = poll_fn()
            state = str(getattr(obj, 'provisioning_state', '') or '').lower()
            _log.debug("%s provisioning_state=%s", resource_desc, state)
            if state == 'succeeded':
                return obj
            if state == 'failed':
                raise RuntimeError(f"{resource_desc} provisioning failed")
        except RuntimeError:
            raise
        except Exception as exc:
            _log.debug("%s poll error (retrying): %s", resource_desc, exc)
        time.sleep(interval)
    raise TimeoutError(f"{resource_desc} did not reach Succeeded within {timeout}s")


def create_afd_distribution(resource_group, origin_host, origin_port, comment, label='default'):
    from azure.mgmt.cdn.models import (
        Profile, Sku,
        AFDEndpoint,
        AFDOriginGroup, LoadBalancingSettingsParameters, HealthProbeParameters,
        AFDOrigin,
        Route,
    )
    client, subscription_id = _get_afd_client(label)

    # Each distribution gets its own uniquely named profile so a failed/orphaned
    # creation never blocks future ones.
    profile_name = _afd_profile_name()

    # AFD resource names: lowercase alphanumeric + hyphens only, max 63 chars.
    # Endpoint names are globally unique across all Azure tenants — add a random
    # suffix so two distributions pointing to the same origin never collide.
    safe = re.sub(r'[^a-z0-9]', '-', origin_host.lower())[:20].strip('-')
    rand = secrets.token_hex(4)
    endpoint_name     = f"ep-{safe}-{rand}"[:63].strip('-')
    origin_group_name = f"og-{safe}"[:63].strip('-')
    origin_name       = f"origin-{safe}"[:63].strip('-')
    route_name        = 'default-route'

    # 1. Create profile and wait for Succeeded
    _log.info("Creating AFD profile '%s'...", profile_name)
    client.profiles.begin_create(
        resource_group, profile_name,
        Profile(location='global', sku=Sku(name='Standard_AzureFrontDoor')),
    ).wait()
    _afd_wait_succeeded(
        lambda: client.profiles.get(resource_group, profile_name),
        f"profile/{profile_name}",
    )

    # 2. Create endpoint and wait for Succeeded
    _log.info("Creating AFD endpoint '%s'...", endpoint_name)
    client.afd_endpoints.begin_create(
        resource_group, profile_name, endpoint_name,
        AFDEndpoint(location='global', enabled_state='Enabled'),
    ).wait()
    ep = _afd_wait_succeeded(
        lambda: client.afd_endpoints.get(resource_group, profile_name, endpoint_name),
        f"endpoint/{endpoint_name}",
    )

    # 3. Create origin group and wait for Succeeded.
    # Disable active health probing (NotSet) — the origin is a C2 server that may
    # not expose a probe-friendly endpoint, and a failing HTTP probe to port 80
    # would cause AFD to mark the origin unhealthy and return error pages to beacons.
    # Passive failure detection from real traffic is sufficient for this use case.
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
    _afd_wait_succeeded(
        lambda: client.afd_origin_groups.get(resource_group, profile_name, origin_group_name),
        f"origin-group/{origin_group_name}",
    )

    # 4. Create origin and wait for Succeeded.
    # Route creation fails with BadRequest if the origin group has no Succeeded origins.
    # Port routing: AFD connects to origin via http_port for HttpOnly forwarding and
    # https_port for HttpsOnly. Set the correct port on the right side so AFD actually
    # reaches the origin on the intended port.
    _origin_http_port  = origin_port if origin_port != 443 else 80
    _origin_https_port = origin_port if origin_port == 443 else 443
    _log.info("Creating AFD origin '%s' → %s:%s", origin_name, origin_host, origin_port)
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
            # Allow self-signed / custom TLS certs on the C2 server
            enforce_certificate_name_check=False,
        ),
    ).wait()
    _afd_wait_succeeded(
        lambda: client.afd_origins.get(resource_group, profile_name, origin_group_name, origin_name),
        f"origin/{origin_name}",
    )

    # 5. Create route.
    # link_to_default_domain='Enabled' makes the *.azurefd.net hostname work without a
    # custom domain — any external DNS (Cloudflare, Route 53, etc.) can CNAME to it.
    origin_group_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.Cdn/profiles/{profile_name}"
        f"/originGroups/{origin_group_name}"
    )
    # HttpsOnly: AFD connects to origin via TLS (port 443).
    # HttpOnly:  AFD connects via plain HTTP on http_port — correct for non-TLS origins.
    # MatchRequest would mirror the incoming protocol, so HTTPS browser requests would
    # reach a plain-HTTP origin over TLS which fails with "page not found".
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
    _afd_wait_succeeded(
        lambda: client.routes.get(resource_group, profile_name, endpoint_name, route_name),
        f"route/{route_name}",
    )

    return {
        'external_id': f"{resource_group}/{profile_name}/{endpoint_name}",
        'domain': ep.host_name or '',
        'status': 'deploying',
    }


def update_afd_health_probe(resource_group, profile_name, probe_protocol, probe_path, probe_interval, label='default'):
    """Update health probe settings on the first origin group of an AFD profile.

    We fetch the current origin group and re-send load_balancing_settings alongside
    health_probe_settings because some AFD API versions require both to be present
    in an update or they silently revert / reject the partial payload.
    """
    from azure.mgmt.cdn.models import (
        AFDOriginGroupUpdateParameters,
        HealthProbeParameters,
        LoadBalancingSettingsParameters,
    )
    client, _ = _get_afd_client(label)

    ogs = list(client.afd_origin_groups.list_by_profile(resource_group, profile_name))
    if not ogs:
        raise ValueError("No origin groups found in AFD profile")
    og = ogs[0]
    og_name = og.name

    # Preserve existing load balancing settings or fall back to safe defaults
    existing_lb = og.load_balancing_settings
    if existing_lb:
        lb = LoadBalancingSettingsParameters(
            sample_size=existing_lb.sample_size or 4,
            successful_samples_required=existing_lb.successful_samples_required or 3,
            additional_latency_in_milliseconds=existing_lb.additional_latency_in_milliseconds or 50,
        )
    else:
        lb = LoadBalancingSettingsParameters(
            sample_size=4,
            successful_samples_required=3,
            additional_latency_in_milliseconds=50,
        )

    client.afd_origin_groups.begin_update(
        resource_group, profile_name, og_name,
        AFDOriginGroupUpdateParameters(
            load_balancing_settings=lb,
            health_probe_settings=HealthProbeParameters(
                probe_path=probe_path or '/',
                probe_protocol=probe_protocol,   # 'NotSet' | 'Http' | 'Https'
                probe_interval_in_seconds=int(probe_interval or 100),
            ),
        ),
    ).wait()


def update_afd_origin(resource_group, profile_name, origin_host, origin_port, label='default'):
    """Update the origin host/port on an existing AFD profile (first origin found).

    Also updates the route's forwarding_protocol to match the new port so AFD
    connects via the right protocol (HttpsOnly for 443, HttpOnly for everything else).
    """
    from azure.mgmt.cdn.models import AFDOriginUpdateParameters
    client, _ = _get_afd_client(label)

    ogs = list(client.afd_origin_groups.list_by_profile(resource_group, profile_name))
    if not ogs:
        raise ValueError("No origin groups found in AFD profile")
    og_name = ogs[0].name

    origins = list(client.afd_origins.list_by_origin_group(resource_group, profile_name, og_name))
    if not origins:
        raise ValueError("No origins found in AFD origin group")
    origin_name = origins[0].name

    http_port  = origin_port if origin_port != 443 else 80
    https_port = origin_port if origin_port == 443 else 443
    client.afd_origins.begin_update(
        resource_group, profile_name, og_name, origin_name,
        AFDOriginUpdateParameters(
            host_name=origin_host,
            http_port=http_port,
            https_port=https_port,
            origin_host_header=origin_host,
            enforce_certificate_name_check=False,
        ),
    ).wait()

    # Update route forwarding_protocol to match new port
    forwarding_protocol = 'HttpsOnly' if origin_port == 443 else 'HttpOnly'
    try:
        from azure.mgmt.cdn.models import RouteUpdateParameters
        endpoints = list(client.afd_endpoints.list_by_profile(resource_group, profile_name))
        for ep in endpoints:
            try:
                routes = list(client.routes.list_by_endpoint(resource_group, profile_name, ep.name))
                for route in routes:
                    client.routes.begin_update(
                        resource_group, profile_name, ep.name, route.name,
                        RouteUpdateParameters(forwarding_protocol=forwarding_protocol),
                    ).wait()
            except Exception as exc:
                _log.warning("Could not update route forwarding_protocol: %s", exc)
    except ImportError:
        _log.warning("RouteUpdateParameters not available in SDK — skipping route protocol update")


def delete_afd_distribution(resource_group, profile_name, endpoint_name, label='default'):
    client, _ = _get_afd_client(label)
    # Delete the endpoint (origins/routes are deleted with it)
    try:
        poller = client.afd_endpoints.begin_delete(resource_group, profile_name, endpoint_name)
        poller.wait()
    except Exception as exc:
        _log.warning("AFD endpoint delete failed: %s", exc)
    return {'deleted': f"{resource_group}/{profile_name}/{endpoint_name}"}
