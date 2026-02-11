import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from app.services.credential_service import get_credential


# Common EC2 regions
EC2_REGIONS = [
    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
    'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-central-1', 'eu-north-1',
    'ap-southeast-1', 'ap-southeast-2', 'ap-northeast-1', 'ap-northeast-2',
    'ap-south-1', 'sa-east-1', 'ca-central-1', 'me-south-1', 'af-south-1',
]


def _get_client(service='ec2', region=None):
    access_key = get_credential('aws', 'access_key_id')
    secret_key = get_credential('aws', 'secret_access_key')
    if not access_key or not secret_key:
        raise ValueError("AWS credentials not configured. Set them in Settings.")
    region = region or get_credential('aws', 'default_region') or 'eu-west-1'
    return boto3.client(
        service,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )


# --- Verification ---

def verify_credentials():
    client = _get_client('sts')
    identity = client.get_caller_identity()
    return {
        'account': identity['Account'],
        'arn': identity['Arn'],
        'user_id': identity['UserId'],
    }


# --- Instances ---

def list_instances(region=None):
    ec2 = _get_client('ec2', region)
    paginator = ec2.get_paginator('describe_instances')
    instances = []
    for page in paginator.paginate():
        for reservation in page['Reservations']:
            for inst in reservation['Instances']:
                instances.append(_format_instance(inst))
    return instances


def get_instance(instance_id, region=None):
    ec2 = _get_client('ec2', region)
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    for reservation in resp['Reservations']:
        for inst in reservation['Instances']:
            return _format_instance(inst, detailed=True)
    raise Exception(f"Instance {instance_id} not found")


def start_instances(instance_ids, region=None):
    ec2 = _get_client('ec2', region)
    resp = ec2.start_instances(InstanceIds=instance_ids)
    return resp['StartingInstances']


def stop_instances(instance_ids, region=None):
    ec2 = _get_client('ec2', region)
    resp = ec2.stop_instances(InstanceIds=instance_ids)
    return resp['StoppingInstances']


def reboot_instances(instance_ids, region=None):
    ec2 = _get_client('ec2', region)
    ec2.reboot_instances(InstanceIds=instance_ids)
    return {'rebooted': instance_ids}


def terminate_instances(instance_ids, region=None):
    ec2 = _get_client('ec2', region)
    resp = ec2.terminate_instances(InstanceIds=instance_ids)
    return resp['TerminatingInstances']


# --- Security Groups ---

def list_security_groups(region=None):
    ec2 = _get_client('ec2', region)
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


def get_security_group(group_id, region=None):
    ec2 = _get_client('ec2', region)
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

def list_key_pairs(region=None):
    ec2 = _get_client('ec2', region)
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

def list_regions():
    ec2 = _get_client('ec2')
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
