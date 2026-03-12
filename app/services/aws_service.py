import logging
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app
from botocore.exceptions import ClientError, NoCredentialsError
from app.services.credential_service import get_credential, get_account_labels

_log = logging.getLogger(__name__)

# instance_id -> account_label, populated by list_instances_all_accounts()
_instance_account_cache: dict = {}

# Common EC2 regions
EC2_REGIONS = [
    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
    'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-central-1', 'eu-north-1',
    'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1', 'ap-northeast-2',
    'ap-south-1', 'sa-east-1', 'ca-central-1', 'me-south-1', 'af-south-1',
]


def _get_client(service='ec2', region=None, label='default'):
    access_key = get_credential('aws', 'access_key_id', label=label)
    secret_key = get_credential('aws', 'secret_access_key', label=label)
    if not access_key or not secret_key:
        raise ValueError(f"AWS credentials not configured for account '{label}'. Set them in Settings.")
    region = region or get_credential('aws', 'default_region', label=label) or 'eu-west-1'
    return boto3.client(
        service,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )


# --- Verification ---

def verify_credentials(label='default'):
    client = _get_client('sts', label=label)
    identity = client.get_caller_identity()
    return {
        'account': identity['Account'],
        'arn': identity['Arn'],
        'user_id': identity['UserId'],
    }


# --- Instances ---

def list_instances(region=None, label='default'):
    ec2 = _get_client('ec2', region, label=label)
    paginator = ec2.get_paginator('describe_instances')
    instances = []
    for page in paginator.paginate():
        for reservation in page['Reservations']:
            for inst in reservation['Instances']:
                instances.append(_format_instance(inst))
    return instances


def _fetch_instances_for_account(lbl, region=None):
    """Fetch instances for a single account and tag them with account_label."""
    instances = list_instances(region=region, label=lbl)
    for inst in instances:
        inst['account_label'] = lbl
    return instances


def list_instances_all_accounts(region=None):
    """Fetch instances from every configured AWS account in parallel.

    Each instance dict gets an extra ``account_label`` field.  Individual
    account errors are logged and skipped so one bad key does not block the rest.
    """
    labels = get_account_labels('aws')
    if not labels:
        return []

    all_instances = []

    if len(labels) == 1:
        try:
            all_instances = _fetch_instances_for_account(labels[0], region)
            _instance_account_cache.update({i['id']: labels[0] for i in all_instances})
        except Exception as exc:
            _log.warning("AWS instance fetch failed for account '%s': %s", labels[0], exc)
        return all_instances

    app = current_app._get_current_object()

    def _fetch_in_context(lbl):
        with app.app_context():
            return _fetch_instances_for_account(lbl, region)

    with ThreadPoolExecutor(max_workers=min(len(labels), 8)) as pool:
        futures = {pool.submit(_fetch_in_context, lbl): lbl for lbl in labels}
        for future in as_completed(futures):
            lbl = futures[future]
            try:
                all_instances.extend(future.result())
            except Exception as exc:
                _log.warning("AWS instance fetch failed for account '%s': %s", lbl, exc)

    _instance_account_cache.update({i['id']: i['account_label'] for i in all_instances})
    return all_instances


def get_instance_status_checks(instance_id, region=None, label='default'):
    """Return system, instance, and EBS status checks for one instance."""
    ec2 = _get_client('ec2', region, label=label)
    resp = ec2.describe_instance_status(
        InstanceIds=[instance_id],
        IncludeAllInstances=True,   # include stopped/pending instances
    )
    statuses = resp.get('InstanceStatuses', [])
    if not statuses:
        return {'instance_id': instance_id, 'state': 'unknown',
                'system': None, 'instance': None, 'ebs': None}

    s = statuses[0]
    state = s.get('InstanceState', {}).get('Name', 'unknown')

    def _fmt(block):
        if not block:
            return None
        details = [
            {'name': d.get('Name', ''), 'status': d.get('Status', '')}
            for d in block.get('Details', [])
        ]
        return {'status': block.get('Status', 'unknown'), 'details': details}

    ebs = _fmt(s.get('AttachedEbsStatus'))

    # Fallback: fetch volume status directly when AttachedEbsStatus is not in the response
    if ebs is None:
        try:
            inst_resp = ec2.describe_instances(InstanceIds=[instance_id])
            volume_ids = []
            for res in inst_resp.get('Reservations', []):
                for inst in res.get('Instances', []):
                    for bdm in inst.get('BlockDeviceMappings', []):
                        vol_id = bdm.get('Ebs', {}).get('VolumeId')
                        if vol_id:
                            volume_ids.append(vol_id)

            if volume_ids:
                vol_resp = ec2.describe_volume_status(VolumeIds=volume_ids)
                vol_statuses = vol_resp.get('VolumeStatuses', [])
                if vol_statuses:
                    per_vol = [
                        {'name': v.get('VolumeId', ''),
                         'status': v.get('VolumeStatus', {}).get('Status', 'unknown')}
                        for v in vol_statuses
                    ]
                    statuses_values = [v['status'] for v in per_vol]
                    if all(sv == 'ok' for sv in statuses_values):
                        overall = 'ok'
                    elif any(sv == 'impaired' for sv in statuses_values):
                        overall = 'impaired'
                    else:
                        overall = statuses_values[0]
                    ebs = {'status': overall, 'details': per_vol}
        except Exception as exc:
            _log.debug("EBS volume status fallback failed for %s: %s", instance_id, exc)

    return {
        'instance_id': instance_id,
        'state':       state,
        'system':      _fmt(s.get('SystemStatus')),
        'instance':    _fmt(s.get('InstanceStatus')),
        'ebs':         ebs,
    }


def get_instance(instance_id, region=None, label='default'):
    ec2 = _get_client('ec2', region, label=label)
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    for reservation in resp['Reservations']:
        for inst in reservation['Instances']:
            return _format_instance(inst, detailed=True)
    raise Exception(f"Instance {instance_id} not found")


def start_instances(instance_ids, region=None, label='default'):
    ec2 = _get_client('ec2', region, label=label)
    resp = ec2.start_instances(InstanceIds=instance_ids)
    return resp['StartingInstances']


def stop_instances(instance_ids, region=None, label='default'):
    ec2 = _get_client('ec2', region, label=label)
    resp = ec2.stop_instances(InstanceIds=instance_ids)
    return resp['StoppingInstances']


def reboot_instances(instance_ids, region=None, label='default'):
    ec2 = _get_client('ec2', region, label=label)
    ec2.reboot_instances(InstanceIds=instance_ids)
    return {'rebooted': instance_ids}


def terminate_instances(instance_ids, region=None, label='default'):
    ec2 = _get_client('ec2', region, label=label)
    resp = ec2.terminate_instances(InstanceIds=instance_ids)
    return resp['TerminatingInstances']


# --- Security Groups ---

def list_security_groups(region=None, label='default'):
    ec2 = _get_client('ec2', region, label=label)
    resp = ec2.describe_security_groups()
    groups = []
    for sg in resp['SecurityGroups']:
        groups.append({
            'id': sg['GroupId'],
            'name': sg['GroupName'],
            'description': sg.get('Description', ''),
            'vpc_id': sg.get('VpcId', ''),
            'inbound_rules': len(sg.get('IpPermissions', [])),
            'outbound_rules': len(sg.get('IpPermissionsEgress', [])),
        })
    return groups


def get_security_group(group_id, region=None, label='default'):
    ec2 = _get_client('ec2', region, label=label)
    resp = ec2.describe_security_groups(GroupIds=[group_id])
    if not resp['SecurityGroups']:
        raise Exception(f"Security group {group_id} not found")
    sg = resp['SecurityGroups'][0]
    return {
        'id': sg['GroupId'],
        'name': sg['GroupName'],
        'description': sg.get('Description', ''),
        'vpc_id': sg.get('VpcId', ''),
        'inbound_rules': _format_sg_rules(sg.get('IpPermissions', [])),
        'outbound_rules': _format_sg_rules(sg.get('IpPermissionsEgress', [])),
        'tags': _tags_to_dict(sg.get('Tags', [])),
    }


# --- Key Pairs ---

def list_key_pairs(region=None, label='default'):
    ec2 = _get_client('ec2', region, label=label)
    resp = ec2.describe_key_pairs()
    return [
        {
            'name': kp['KeyName'],
            'id': kp.get('KeyPairId', ''),
            'fingerprint': kp.get('KeyFingerprint', ''),
            'type': kp.get('KeyType', ''),
        }
        for kp in resp['KeyPairs']
    ]


# --- Regions ---

def list_regions(label='default'):
    ec2 = _get_client('ec2', label=label)
    resp = ec2.describe_regions()
    return [
        {'name': r['RegionName'], 'endpoint': r['Endpoint']}
        for r in resp['Regions']
    ]


# --- Helpers ---

def _format_instance(inst, detailed=False):
    tags = inst.get('Tags', [])
    name = ''
    for t in tags:
        if t['Key'] == 'Name':
            name = t['Value']
            break

    result = {
        'id': inst['InstanceId'],
        'name': name,
        'type': inst['InstanceType'],
        'state': inst['State']['Name'],
        'az': inst['Placement']['AvailabilityZone'],
        'public_ip': inst.get('PublicIpAddress', ''),
        'private_ip': inst.get('PrivateIpAddress', ''),
        'launch_time': inst['LaunchTime'].isoformat() if inst.get('LaunchTime') else '',
        'platform': inst.get('PlatformDetails', inst.get('Platform', 'linux')),
        'ami': inst.get('ImageId', ''),
    }

    if detailed:
        result['vpc_id'] = inst.get('VpcId', '')
        result['subnet_id'] = inst.get('SubnetId', '')
        result['key_name'] = inst.get('KeyName', '')
        result['security_groups'] = [
            {'id': sg['GroupId'], 'name': sg['GroupName']}
            for sg in inst.get('SecurityGroups', [])
        ]
        result['tags'] = _tags_to_dict(tags)
        result['architecture'] = inst.get('Architecture', '')
        result['root_device'] = inst.get('RootDeviceType', '')
        result['ebs_optimized'] = inst.get('EbsOptimized', False)
        result['monitoring'] = inst.get('Monitoring', {}).get('State', '')

    return result


def _tags_to_dict(tags):
    return {t['Key']: t['Value'] for t in tags}


def _format_sg_rules(permissions):
    rules = []
    for perm in permissions:
        protocol = perm.get('IpProtocol', '-1')
        from_port = perm.get('FromPort', 0)
        to_port = perm.get('ToPort', 0)
        for ip_range in perm.get('IpRanges', []):
            rules.append({
                'protocol': protocol,
                'from_port': from_port,
                'to_port': to_port,
                'cidr': ip_range['CidrIp'],
                'description': ip_range.get('Description', ''),
            })
        for ipv6 in perm.get('Ipv6Ranges', []):
            rules.append({
                'protocol': protocol,
                'from_port': from_port,
                'to_port': to_port,
                'cidr': ipv6['CidrIpv6'],
                'description': ipv6.get('Description', ''),
            })
    return rules
