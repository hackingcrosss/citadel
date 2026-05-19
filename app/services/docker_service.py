import os
import tempfile

import docker
from docker.errors import NotFound, APIError
from app.services.credential_service import get_credential
from app.utils.url_validation import validate_docker_host

# Cap socket waits so an unreachable daemon fails fast instead of hanging the worker.
_DOCKER_TIMEOUT = 5


def _truthy(value):
    return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')


def _remote_docker_allowed():
    """Remote Docker is opt-in via secure admin setting or env override."""
    return _truthy(get_credential('docker', 'allow_remote')) or _truthy(os.getenv('CITADEL_ALLOW_REMOTE_DOCKER'))


def _get_client():
    """Get Docker client. Uses remote host from Settings if configured,
    otherwise falls back to local socket."""
    docker_host = (get_credential('docker', 'host') or '').strip()
    if docker_host:
        ok, reason = validate_docker_host(docker_host, allow_remote=_remote_docker_allowed())
        if not ok:
            raise ValueError(f'Invalid Docker host: {reason}')

        tls_config = None
        if docker_host.startswith(('tcp://', 'https://')):
            ca = get_credential('docker', 'tls_ca')
            cert = get_credential('docker', 'tls_cert')
            key = get_credential('docker', 'tls_key')
            if not (ca and cert and key):
                raise ValueError('Remote Docker host requires TLS CA, client certificate, and client key')
            ca_path = _write_temp(ca, 'ca.pem')
            cert_path = _write_temp(cert, 'cert.pem')
            key_path = _write_temp(key, 'key.pem')
            tls_config = docker.tls.TLSConfig(
                ca_cert=ca_path,
                client_cert=(cert_path, key_path),
                verify=True,
            )
        return docker.DockerClient(base_url=docker_host, tls=tls_config, timeout=_DOCKER_TIMEOUT)
    return docker.from_env(timeout=_DOCKER_TIMEOUT)


def _write_temp(content, name):
    """Write credential content to a private temp file and return the path."""
    suffix = '-' + ''.join(ch for ch in name if ch.isalnum() or ch in ('.', '-'))
    fd, path = tempfile.mkstemp(prefix='citadel-docker-', suffix=suffix)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(content)
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


# --- List / Get ---

def list_containers(all=True):
    """List containers. Set all=False for running only."""
    client = _get_client()
    containers = client.containers.list(all=all)
    return [_format_container(c) for c in containers]


def get_container(container_id):
    """Get detailed info for a single container."""
    client = _get_client()
    container = client.containers.get(container_id)
    return _format_container(container, detailed=True)


# --- Actions ---

def start_container(container_id):
    client = _get_client()
    container = client.containers.get(container_id)
    container.start()
    container.reload()
    return {'id': container.short_id, 'name': container.name, 'status': container.status}


def stop_container(container_id):
    client = _get_client()
    container = client.containers.get(container_id)
    container.stop(timeout=10)
    container.reload()
    return {'id': container.short_id, 'name': container.name, 'status': container.status}


def restart_container(container_id):
    client = _get_client()
    container = client.containers.get(container_id)
    container.restart(timeout=10)
    container.reload()
    return {'id': container.short_id, 'name': container.name, 'status': container.status}


def remove_container(container_id, force=False):
    client = _get_client()
    container = client.containers.get(container_id)
    name = container.name
    short_id = container.short_id
    container.remove(force=force)
    return {'id': short_id, 'name': name, 'removed': True}


# --- Logs ---

def get_container_logs(container_id, tail=100):
    client = _get_client()
    container = client.containers.get(container_id)
    logs = container.logs(tail=tail, timestamps=True).decode('utf-8', errors='replace')
    return {'id': container.short_id, 'name': container.name, 'logs': logs}


# --- Stats ---

def get_container_stats(container_id):
    """Get one-shot resource usage stats for a running container."""
    client = _get_client()
    container = client.containers.get(container_id)
    stats = container.stats(stream=False)
    return _format_stats(container, stats)


# --- Helpers ---

def _format_container(container, detailed=False):
    """Format a Docker container object into a plain dict."""
    ports_config = container.attrs.get('NetworkSettings', {}).get('Ports', {}) or {}
    ports = []
    for container_port, host_bindings in ports_config.items():
        if host_bindings:
            for binding in host_bindings:
                ports.append(f"{binding.get('HostIp', '0.0.0.0')}:{binding['HostPort']}->{container_port}")
        else:
            ports.append(container_port)

    image_tags = container.image.tags if container.image.tags else []
    image_name = image_tags[0] if image_tags else container.attrs.get('Config', {}).get('Image', 'unknown')

    # Extract network IPs (always included for Operations page container picker)
    net_settings = container.attrs.get('NetworkSettings', {}).get('Networks', {})
    networks = {}
    for net_name, net_info in net_settings.items():
        ip = net_info.get('IPAddress', '')
        if ip:
            networks[net_name] = ip

    result = {
        'id': container.id,
        'short_id': container.short_id,
        'name': container.name,
        'image': image_name,
        'status': container.status,
        'state': container.status,
        'ports': ports,
        'ports_display': ', '.join(ports) if ports else '-',
        'created': container.attrs.get('Created', ''),
        'networks': networks,
    }

    if detailed:
        config = container.attrs.get('Config', {})
        host_config = container.attrs.get('HostConfig', {})
        result['command'] = config.get('Cmd', [])
        result['entrypoint'] = config.get('Entrypoint', [])
        # K-01: NEVER expose Config.Env — it carries MASTER_ENCRYPTION_KEY,
        # SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD, DATABASE_URL etc. for
        # platform containers and per-deployment secrets for phishlet/website
        # containers. Defense-in-depth: this stays stripped regardless of which
        # role calls the endpoint, so an authz bug elsewhere can't leak the keys.
        result['labels'] = config.get('Labels', {})
        result['volumes'] = host_config.get('Binds', [])
        result['restart_policy'] = host_config.get('RestartPolicy', {})
        result['network_mode'] = host_config.get('NetworkMode', '')
        # Override with detailed format including full network info
        result['networks'] = {
            name: {'ip': net_info.get('IPAddress', '')}
            for name, net_info in net_settings.items()
        }

    return result


def _format_stats(container, stats):
    """Calculate CPU % and memory usage from Docker stats API response."""
    cpu_stats = stats.get('cpu_stats', {})
    precpu_stats = stats.get('precpu_stats', {})

    cpu_delta = cpu_stats.get('cpu_usage', {}).get('total_usage', 0) - \
                precpu_stats.get('cpu_usage', {}).get('total_usage', 0)
    system_delta = cpu_stats.get('system_cpu_usage', 0) - \
                   precpu_stats.get('system_cpu_usage', 0)
    num_cpus = cpu_stats.get('online_cpus',
               len(cpu_stats.get('cpu_usage', {}).get('percpu_usage', [1])))

    cpu_percent = 0.0
    if system_delta > 0 and cpu_delta > 0:
        cpu_percent = round((cpu_delta / system_delta) * num_cpus * 100.0, 2)

    mem_usage = stats.get('memory_stats', {}).get('usage', 0)
    mem_limit = stats.get('memory_stats', {}).get('limit', 0)
    mem_percent = round((mem_usage / mem_limit) * 100.0, 2) if mem_limit > 0 else 0.0

    networks = stats.get('networks', {})
    net_rx = sum(n.get('rx_bytes', 0) for n in networks.values())
    net_tx = sum(n.get('tx_bytes', 0) for n in networks.values())

    return {
        'id': container.short_id,
        'name': container.name,
        'cpu_percent': cpu_percent,
        'memory_usage': mem_usage,
        'memory_limit': mem_limit,
        'memory_percent': mem_percent,
        'memory_display': f"{_human_bytes(mem_usage)}/{_human_bytes(mem_limit)}",
        'network_rx': _human_bytes(net_rx),
        'network_tx': _human_bytes(net_tx),
    }


def _human_bytes(b):
    """Convert bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f"{b:.1f}{unit}"
        b /= 1024
    return f"{b:.1f}TB"
