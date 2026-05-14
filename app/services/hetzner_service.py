import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app
from hcloud import Client
from hcloud.images.domain import Image
from hcloud.server_types.domain import ServerType
from hcloud.locations.domain import Location
from hcloud.ssh_keys.domain import SSHKey
from app.services.credential_service import get_credential, get_account_labels

_log = logging.getLogger(__name__)

# server_id (str) -> account_label, populated by list_servers_all_accounts()
_server_account_cache: dict = {}

# Common Hetzner Cloud locations (datacenter shortcodes)
HETZNER_LOCATIONS = [
    {'name': 'fsn1', 'description': 'Falkenstein, Germany'},
    {'name': 'nbg1', 'description': 'Nuremberg, Germany'},
    {'name': 'hel1', 'description': 'Helsinki, Finland'},
    {'name': 'ash',  'description': 'Ashburn, VA, USA'},
    {'name': 'hil',  'description': 'Hillsboro, OR, USA'},
    {'name': 'sin',  'description': 'Singapore'},
]

_ACTION_MAX_RETRIES = 120  # hcloud SDK default retry count for action polling


def _get_client(label='default'):
    token = get_credential('hetzner', 'api_token', label=label)
    if not token:
        raise ValueError(f"Hetzner credentials not configured for account '{label}'. Set them in Settings.")
    return Client(token=token, application_name='citadel-citadel')


# --- Verification ---

def verify_credentials(label='default'):
    """Cheap round-trip to confirm the API token works."""
    client = _get_client(label=label)
    locations = client.locations.get_all()
    return {
        'account_label': label,
        'location_count': len(locations),
        'status': 'ok',
    }


# --- Servers ---

def _format_server(server, detailed=False):
    """Serialize an hcloud BoundServer into a plain dict."""
    public_ip = ''
    ipv6 = ''
    private_ip = ''
    if server.public_net:
        if server.public_net.ipv4:
            public_ip = server.public_net.ipv4.ip or ''
        if server.public_net.ipv6:
            ipv6 = server.public_net.ipv6.ip or ''
    # Private networks attached to the server (separate from public_net)
    try:
        priv_nets = getattr(server, 'private_net', None) or []
        if priv_nets:
            private_ip = getattr(priv_nets[0], 'ip', '') or ''
    except (IndexError, AttributeError):
        private_ip = ''

    result = {
        'id': str(server.id),
        'name': server.name or '',
        'type': server.server_type.name if server.server_type else '',
        'state': (server.status or '').lower(),
        'location': server.datacenter.location.name if (server.datacenter and server.datacenter.location) else '',
        'datacenter': server.datacenter.name if server.datacenter else '',
        'public_ip': public_ip,
        'private_ip': private_ip,
        'ipv6': ipv6,
        'launch_time': server.created.isoformat() if server.created else '',
        'image': (server.image.name or server.image.description) if server.image else '',
    }

    if detailed:
        result['cores'] = server.server_type.cores if server.server_type else None
        result['memory_gb'] = server.server_type.memory if server.server_type else None
        result['disk_gb'] = server.server_type.disk if server.server_type else None
        result['rescue_enabled'] = bool(server.rescue_enabled)
        result['locked'] = bool(server.locked)
        result['labels'] = dict(server.labels) if server.labels else {}
        result['iso'] = server.iso.name if server.iso else ''
        result['volume_count'] = len(server.volumes) if server.volumes else 0
        result['primary_disk_size'] = server.primary_disk_size or 0

    return result


def list_servers(label='default'):
    client = _get_client(label=label)
    servers = client.servers.get_all()
    return [_format_server(s) for s in servers]


def _fetch_servers_for_account(lbl):
    servers = list_servers(label=lbl)
    for s in servers:
        s['account_label'] = lbl
    return servers


def list_servers_all_accounts():
    """Fetch servers from every configured Hetzner account in parallel."""
    labels = get_account_labels('hetzner')
    if not labels:
        return []

    all_servers = []

    if len(labels) == 1:
        try:
            all_servers = _fetch_servers_for_account(labels[0])
            _server_account_cache.update({s['id']: labels[0] for s in all_servers})
        except Exception as exc:
            _log.warning("Hetzner server fetch failed for account '%s': %s", labels[0], exc)
        return all_servers

    app = current_app._get_current_object()

    def _fetch_in_context(lbl):
        with app.app_context():
            return _fetch_servers_for_account(lbl)

    with ThreadPoolExecutor(max_workers=min(len(labels), 8)) as pool:
        futures = {pool.submit(_fetch_in_context, lbl): lbl for lbl in labels}
        for future in as_completed(futures):
            lbl = futures[future]
            try:
                all_servers.extend(future.result())
            except Exception as exc:
                _log.warning("Hetzner server fetch failed for account '%s': %s", lbl, exc)

    _server_account_cache.update({s['id']: s['account_label'] for s in all_servers})
    return all_servers


def get_server(server_id, label='default'):
    client = _get_client(label=label)
    server = client.servers.get_by_id(int(server_id))
    if not server:
        raise Exception(f"Server {server_id} not found")
    return _format_server(server, detailed=True)


def _wait(action):
    if action is None:
        return
    try:
        action.wait_until_finished(max_retries=_ACTION_MAX_RETRIES)
    except Exception as exc:
        _log.warning("Hetzner action %s did not complete cleanly: %s", getattr(action, 'id', '?'), exc)


def start_server(server_id, label='default'):
    client = _get_client(label=label)
    server = client.servers.get_by_id(int(server_id))
    if not server:
        raise Exception(f"Server {server_id} not found")
    _wait(server.power_on())
    return {'server_id': str(server_id), 'action': 'started'}


def stop_server(server_id, label='default'):
    client = _get_client(label=label)
    server = client.servers.get_by_id(int(server_id))
    if not server:
        raise Exception(f"Server {server_id} not found")
    # Graceful shutdown first, fall back to power_off if needed
    _wait(server.shutdown())
    return {'server_id': str(server_id), 'action': 'stopped'}


def reboot_server(server_id, label='default'):
    client = _get_client(label=label)
    server = client.servers.get_by_id(int(server_id))
    if not server:
        raise Exception(f"Server {server_id} not found")
    _wait(server.reboot())
    return {'server_id': str(server_id), 'action': 'rebooted'}


def delete_server(server_id, label='default'):
    client = _get_client(label=label)
    server = client.servers.get_by_id(int(server_id))
    if not server:
        raise Exception(f"Server {server_id} not found")
    _wait(server.delete())
    return {'server_id': str(server_id), 'action': 'deleted'}


def create_server(label='default', name=None, server_type=None, image=None,
                  location=None, ssh_keys=None, user_data=None, labels_dict=None):
    """Provision a new Hetzner Cloud server.

    Args:
        label: credential account label.
        name: server hostname (required, DNS-valid).
        server_type: shortcode such as 'cx22', 'cpx21'.
        image: image slug such as 'debian-12', 'ubuntu-22.04'.
        location: location shortcode such as 'fsn1', 'nbg1'.
        ssh_keys: list of SSH key IDs (ints) or names (strs) registered with the Hetzner project.
        user_data: optional cloud-init YAML blob.
        labels_dict: optional dict of Hetzner labels to attach.
    """
    if not name or not server_type or not image or not location:
        raise ValueError("name, server_type, image, and location are required")

    client = _get_client(label=label)

    ssh_key_objs = []
    for key in (ssh_keys or []):
        if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
            ssh_key_objs.append(SSHKey(id=int(key)))
        else:
            ssh_key_objs.append(SSHKey(name=key))

    response = client.servers.create(
        name=name,
        server_type=ServerType(name=server_type),
        image=Image(name=image),
        location=Location(name=location),
        ssh_keys=ssh_key_objs or None,
        user_data=user_data or None,
        labels=labels_dict or None,
    )

    _wait(response.action)
    for a in (response.next_actions or []):
        _wait(a)

    server = response.server
    root_password = getattr(response, 'root_password', None)
    result = _format_server(server, detailed=True)
    result['account_label'] = label
    if root_password:
        # Only returned by Hetzner when no SSH keys supplied — pass through once.
        result['root_password'] = root_password
    return result


# --- Server Types / Images / Locations ---

def list_server_types(label='default'):
    client = _get_client(label=label)
    types = client.server_types.get_all()
    return [
        {
            'name': t.name,
            'description': t.description or '',
            'cores': t.cores,
            'memory_gb': t.memory,
            'disk_gb': t.disk,
            'cpu_type': t.cpu_type or '',
            'architecture': getattr(t, 'architecture', 'x86') or 'x86',
            'storage_type': t.storage_type or '',
            'deprecated': bool(getattr(t, 'deprecated', False)),
        }
        for t in types
        if not getattr(t, 'deprecated', False)
    ]


def list_images(label='default', image_type='system'):
    """List available images. image_type: 'system', 'snapshot', 'backup', 'app'."""
    client = _get_client(label=label)
    images = client.images.get_all(type=image_type)
    return [
        {
            'id': img.id,
            'name': img.name or '',
            'description': img.description or '',
            'type': img.type or '',
            'os_flavor': img.os_flavor or '',
            'os_version': img.os_version or '',
            'architecture': getattr(img, 'architecture', 'x86') or 'x86',
        }
        for img in images
    ]


def list_locations(label='default'):
    client = _get_client(label=label)
    locs = client.locations.get_all()
    return [
        {
            'name': loc.name,
            'description': loc.description or '',
            'city': loc.city or '',
            'country': loc.country or '',
            'network_zone': loc.network_zone or '',
        }
        for loc in locs
    ]


# --- SSH Keys (managed inside the Hetzner project) ---

def list_ssh_keys(label='default'):
    client = _get_client(label=label)
    keys = client.ssh_keys.get_all()
    return [
        {
            'id': k.id,
            'name': k.name or '',
            'fingerprint': k.fingerprint or '',
            'public_key': k.public_key or '',
            'created': k.created.isoformat() if k.created else '',
        }
        for k in keys
    ]


def create_ssh_key(label='default', name=None, public_key=None, labels_dict=None):
    if not name or not public_key:
        raise ValueError("name and public_key are required")
    client = _get_client(label=label)
    key = client.ssh_keys.create(name=name, public_key=public_key.strip(), labels=labels_dict or None)
    return {
        'id': key.id,
        'name': key.name,
        'fingerprint': key.fingerprint or '',
    }


def delete_ssh_key(label='default', key_id=None):
    if not key_id:
        raise ValueError("key_id is required")
    client = _get_client(label=label)
    key = client.ssh_keys.get_by_id(int(key_id))
    if not key:
        raise Exception(f"SSH key {key_id} not found")
    client.ssh_keys.delete(key)
    return {'deleted': True, 'id': int(key_id)}
