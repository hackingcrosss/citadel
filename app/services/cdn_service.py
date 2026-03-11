import logging
import time
from app.services.credential_service import get_credential, get_account_labels

_log = logging.getLogger(__name__)

_INFRARED_TAG = 'infrared-managed'


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
    origin_id = f"infrared-{origin_host.replace('.', '-').replace(':', '-')}"
    caller_ref = f"infrared-{int(time.time())}"

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


def delete_cloudfront_distribution(dist_id, etag, label='default'):
    """Delete a CloudFront distribution. Must be disabled and Deployed first."""
    client = _get_cf_client(label)
    client.delete_distribution(Id=dist_id, IfMatch=etag)
    return {'deleted': dist_id}


# ---------------------------------------------------------------------------
# Azure Front Door helpers
# ---------------------------------------------------------------------------

_AFD_PROFILE_NAME = 'infrared-cdn'


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
            results.append({
                'external_id': f"{resource_group}/{profile_name}/{ep.name}",
                'domain': ep.host_name or '',
                'status': 'deployed' if str(ep.deployment_status or '').lower() == 'succeeded' else 'deploying',
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


def create_afd_distribution(resource_group, origin_host, origin_port, comment, label='default'):
    from azure.mgmt.cdn.models import (
        Profile, Sku,
        AFDEndpoint,
        AFDOriginGroup, LoadBalancingSettingsParameters, HealthProbeParameters,
        AFDOrigin,
        Route, DeploymentStatus,
    )
    client, _ = _get_afd_client(label)
    safe_name = origin_host.replace('.', '-').replace(':', '-')
    endpoint_name = f"ir-{safe_name[:40]}-{int(time.time()) % 10000}"
    origin_group_name = f"og-{safe_name[:40]}"
    origin_name = f"origin-{safe_name[:40]}"
    route_name = 'default-route'

    # 1. Ensure profile exists
    try:
        client.profiles.get(resource_group, _AFD_PROFILE_NAME)
    except Exception:
        poller = client.profiles.begin_create(
            resource_group, _AFD_PROFILE_NAME,
            Profile(location='global', sku=Sku(name='Standard_AzureFrontDoor')),
        )
        poller.wait()

    # 2. Create endpoint
    ep_poller = client.afd_endpoints.begin_create(
        resource_group, _AFD_PROFILE_NAME, endpoint_name,
        AFDEndpoint(location='global'),
    )
    ep = ep_poller.result()

    # 3. Create origin group
    og_poller = client.afd_origin_groups.begin_create(
        resource_group, _AFD_PROFILE_NAME, origin_group_name,
        AFDOriginGroup(
            load_balancing_settings=LoadBalancingSettingsParameters(
                sample_size=4,
                successful_samples_required=3,
                additional_latency_in_milliseconds=50,
            ),
            health_probe_settings=HealthProbeParameters(
                probe_path='/',
                probe_protocol='Https',
                probe_interval_in_seconds=100,
            ),
        ),
    )
    og_poller.wait()

    # 4. Create origin
    origin_protocol = 'Https' if origin_port == 443 else 'Http'
    o_poller = client.afd_origins.begin_create(
        resource_group, _AFD_PROFILE_NAME, origin_group_name, origin_name,
        AFDOrigin(
            host_name=origin_host,
            http_port=80,
            https_port=origin_port,
            origin_host_header=origin_host,
            priority=1,
            weight=1000,
            enabled_state='Enabled',
        ),
    )
    o_poller.wait()

    # 5. Create route
    r_poller = client.routes.begin_create(
        resource_group, _AFD_PROFILE_NAME, endpoint_name, route_name,
        Route(
            origin_group={'id': f'/subscriptions/placeholder/resourceGroups/{resource_group}/providers/Microsoft.Cdn/profiles/{_AFD_PROFILE_NAME}/originGroups/{origin_group_name}'},
            supported_protocols=['Http', 'Https'],
            patterns_to_match=['/*'],
            forwarding_protocol=f'{origin_protocol}Only',
            https_redirect='Enabled',
            enabled_state='Enabled',
        ),
    )
    r_poller.wait()

    return {
        'external_id': f"{resource_group}/{_AFD_PROFILE_NAME}/{endpoint_name}",
        'domain': ep.host_name or '',
        'status': 'deploying',
    }


def delete_afd_distribution(resource_group, profile_name, endpoint_name, label='default'):
    client, _ = _get_afd_client(label)
    # Delete the endpoint (origins/routes are deleted with it)
    try:
        poller = client.afd_endpoints.begin_delete(resource_group, profile_name, endpoint_name)
        poller.wait()
    except Exception as exc:
        _log.warning("AFD endpoint delete failed: %s", exc)
    return {'deleted': f"{resource_group}/{profile_name}/{endpoint_name}"}
