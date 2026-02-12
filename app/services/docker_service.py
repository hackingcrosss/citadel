import docker
from docker.errors import NotFound, APIError


def _get_client():
    """Get Docker client connected to local socket."""
    return docker.from_env()


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
    }

    if detailed:
        config = container.attrs.get('Config', {})
        host_config = container.attrs.get('HostConfig', {})
        result['command'] = config.get('Cmd', [])
        result['entrypoint'] = config.get('Entrypoint', [])
        result['environment'] = config.get('Env', [])
        result['labels'] = config.get('Labels', {})
        result['volumes'] = host_config.get('Binds', [])
        result['restart_policy'] = host_config.get('RestartPolicy', {})
        result['network_mode'] = host_config.get('NetworkMode', '')
        networks = container.attrs.get('NetworkSettings', {}).get('Networks', {})
        result['networks'] = {
            name: {'ip': net.get('IPAddress', '')}
            for name, net in networks.items()
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
