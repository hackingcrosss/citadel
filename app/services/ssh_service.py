import paramiko
from io import StringIO
from app.models.instance_ssh_config import InstanceSSHConfig
from app.services.credential_service import _get_fernet
from app.services import aws_service


# Default system services to filter out
DEFAULT_SERVICES = {
    # Init / SysV / core OS
    'init', 'inittab', 'rc', 'rc-local', 'rcS', 'rc.local',
    'rescue', 'emergency', 'halt', 'reboot', 'poweroff', 'shutdown',
    'systemd-ask-password', 'systemd-binfmt', 'systemd-fsck',
    'systemd-initctl', 'systemd-journal', 'systemd-logind',
    'systemd-machine-id-commit', 'systemd-modules-load',
    'systemd-networkd', 'systemd-random-seed', 'systemd-remount-fs',
    'systemd-resolved', 'systemd-sysctl', 'systemd-sysusers',
    'systemd-timesyncd', 'systemd-tmpfiles', 'systemd-udev',
    'systemd-update-done', 'systemd-update-utmp',
    'systemd-user-sessions', 'systemd-vconsole-setup',
    # SSH / remote access
    'ssh', 'sshd', 'openssh-server', 'regenerate-ssh-host-keys',
    # Package managers / updates
    'apt-daily', 'apt-daily-upgrade', 'unattended-upgrades',
    'dpkg', 'dnf-makecache', 'packagekit', 'snapd', 'update-notifier',
    # Time sync
    'chrony', 'chronyd', 'ntp', 'ntpd', 'timedatex',
    # Logging / syslog
    'rsyslog', 'syslog', 'syslog-ng', 'sysstat',
    'journald', 'systemd-journald', 'logrotate',
    # Monitoring / Elastic beats
    'filebeat', 'metricbeat', 'auditbeat', 'packetbeat',
    'heartbeat-elastic', 'functionbeat', 'winlogbeat',
    # AWS agents
    'amazon-cloudwatch-agent', 'cloudwatch-agent', 'aws-cloudwatch-agent',
    'amazon-ssm-agent', 'ssm-agent',
    # Hardware / devices
    'acpid', 'irqbalance', 'ModemManager', 'multipathd',
    'udisks2', 'upower', 'blk-availability',
    # Kernel modules
    'kmod', 'modprobe', 'modules', 'modules-load', 'ldconfig',
    # Networking
    'NetworkManager', 'networkd-dispatcher', 'network', 'networking',
    'nftables', 'firewalld', 'ufw', 'iptables', 'ip6tables',
    'iscsid', 'iSCSI', 'ifup', 'ifupdown', 'ifplugd',
    'dhcpcd', 'dhclient', 'isc-dhcp-server', 'isc-dhcp-client',
    'avahi-daemon', 'mdns',
    # Storage
    'lvm2', 'lvm2-monitor', 'dm-event', 'e2scrub_reap', 'e2scrub_all', 'fstrim',
    # Security / auth
    'apparmor', 'selinux-autorelabel-mark', 'sssd', 'polkit',
    'auditd', 'audit',
    # Scheduling
    'cron', 'crond', 'atd',
    # D-Bus
    'dbus', 'dbus-org.freedesktop',
    # Console / TTY / getty
    'getty@', 'serial-getty@', 'agetty',
    'console-setup', 'console-getty', 'console-screen',
    'keyboard-setup', 'setvtrgb',
    # Plymouth / boot splash
    'plymouth', 'plymouth-quit', 'plymouth-quit-wait',
    'plymouth-read-write', 'plymouth-start',
    # Boot / grub
    'grub-common', 'grub-initrd-fallback', 'apport',
    # Docker / container runtime
    'docker', 'dockerd', 'docker-compose', 'containerd',
    'podman', 'cri-o', 'crio',
    # Proc / procps
    'procps', 'proc',
    # Mail / exim
    'exim', 'exim4', 'postfix', 'sendmail', 'mta',
    # Rsync daemon
    'rsync',
    # Swap
    'swap',
    # udev
    'udev', 'udevd',
    # autovt
    'autovt',
    # Misc system
    'debug-shell', 'tuned', 'user@', 'user-runtime-dir@',
}

# Prefixes that indicate system/default services
DEFAULT_PREFIXES = (
    'systemd-', 'cloud-', 'snap.', 'snapd.',
    'getty@', 'getty-', 'serial-getty@', 'autovt@',
    'user@', 'user-runtime-dir@',
    'dbus-org.freedesktop.', 'plymouth-',
    'apt-', 'dnf-', 'yum-', 'dpkg-',
    'amazon-', 'aws-',
    'docker-', 'containerd-',
    'rc.', 'rc-',
    'ifup@', 'ifdown@', 'ifupdown-',
    'sshd-',
    'initrd-',
    'exim4-',
    'chrony-', 'chronyd-',
    'kmod-',
    'udev-',
)


def _get_ssh_config(instance_id):
    config = InstanceSSHConfig.query.filter_by(instance_id=instance_id).first()
    if not config:
        raise ValueError(f'No SSH configuration found for instance {instance_id}')
    return config


def _decrypt_key(config):
    f = _get_fernet()
    return f.decrypt(config.encrypted_private_key.encode()).decode()


def _get_target_ip(config, region=None):
    instance = aws_service.get_instance(config.instance_id, region)
    if config.use_public_ip:
        ip = instance.get('public_ip')
        if not ip:
            raise ValueError(f'Instance {config.instance_id} has no public IP')
    else:
        ip = instance.get('private_ip')
        if not ip:
            raise ValueError(f'Instance {config.instance_id} has no private IP')
    return ip


def _parse_private_key(key_str):
    key_file = StringIO(key_str)
    # Try RSA first, then Ed25519, then ECDSA
    for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
        try:
            key_file.seek(0)
            return key_class.from_private_key(key_file)
        except (paramiko.ssh_exception.SSHException, ValueError):
            continue
    raise ValueError('Unsupported private key format. Supported: RSA, Ed25519, ECDSA')


def execute_command(instance_id, command, region=None, timeout=30):
    config = _get_ssh_config(instance_id)
    key_str = _decrypt_key(config)
    ip = _get_target_ip(config, region)
    pkey = _parse_private_key(key_str)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=ip,
            username=config.ssh_username,
            pkey=pkey,
            timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        return {
            'stdout': stdout.read().decode('utf-8', errors='replace'),
            'stderr': stderr.read().decode('utf-8', errors='replace'),
            'exit_code': exit_code,
        }
    finally:
        client.close()


def _is_default_service(name):
    bare = name.replace('.service', '')
    if bare in DEFAULT_SERVICES:
        return True
    # Template instances: sshd@something → check base name sshd
    base = bare.split('@')[0]
    if base != bare and base in DEFAULT_SERVICES:
        return True
    for prefix in DEFAULT_PREFIXES:
        if bare.startswith(prefix):
            return True
    return False


def list_services(instance_id, region=None):
    # Get active units with their status
    result = execute_command(
        instance_id,
        'systemctl list-units --type=service --all --no-pager --no-legend',
        region,
    )
    if result['exit_code'] != 0:
        raise RuntimeError(f"Failed to list services: {result['stderr']}")

    # Get unit file states (enabled/disabled)
    uf_result = execute_command(
        instance_id,
        'systemctl list-unit-files --type=service --no-pager --no-legend',
        region,
    )
    unit_file_states = {}
    for line in uf_result['stdout'].strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            name = parts[0].replace('.service', '')
            unit_file_states[name] = parts[1]  # enabled, disabled, static, masked, etc.

    services = []
    for line in result['stdout'].strip().splitlines():
        # Format: UNIT LOAD ACTIVE SUB DESCRIPTION...
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit = parts[0].strip()
        # Remove leading bullet character if present
        if unit and not unit[0].isalpha() and not unit[0] == '-':
            unit = unit.lstrip('\u25cf').lstrip()
            parts = unit.split(None, 4) if unit else parts
            if not parts or len(parts) < 4:
                continue
            unit = parts[0]

        name = unit.replace('.service', '')
        if not name or not name[0].isalnum():
            continue
        if _is_default_service(name):
            continue

        load_state = parts[1]  # loaded, not-found, masked
        active_state = parts[2]  # active, inactive, failed, activating, deactivating
        sub_state = parts[3]    # running, dead, exited, failed, waiting
        description = parts[4] if len(parts) > 4 else ''

        services.append({
            'name': name,
            'unit': unit,
            'load': load_state,
            'active': active_state,
            'sub': sub_state,
            'enabled': unit_file_states.get(name, 'unknown'),
            'description': description,
        })

    # Also add unit files that aren't currently loaded but are enabled/disabled
    loaded_names = {s['name'] for s in services}
    for name, state in unit_file_states.items():
        if name in loaded_names:
            continue
        if _is_default_service(name):
            continue
        if state in ('static', 'masked'):
            continue
        services.append({
            'name': name,
            'unit': name + '.service',
            'load': 'not-loaded',
            'active': 'inactive',
            'sub': 'dead',
            'enabled': state,
            'description': '',
        })

    services.sort(key=lambda s: s['name'])
    return services


def get_service_status(instance_id, service_name, region=None):
    # Validate service name to prevent command injection
    if not all(c.isalnum() or c in '-_@.' for c in service_name):
        raise ValueError('Invalid service name')

    status_result = execute_command(
        instance_id,
        f'systemctl status {service_name}.service 2>&1 || true',
        region,
    )

    config_result = execute_command(
        instance_id,
        f'systemctl cat {service_name}.service 2>&1 || true',
        region,
    )

    return {
        'name': service_name,
        'status_output': status_result['stdout'],
        'config_output': config_result['stdout'],
    }


def service_action(instance_id, service_name, action, region=None):
    if action not in ('start', 'stop', 'restart', 'enable', 'disable'):
        raise ValueError(f'Invalid action: {action}')

    # Validate service name to prevent command injection
    if not all(c.isalnum() or c in '-_@.' for c in service_name):
        raise ValueError('Invalid service name')

    result = execute_command(
        instance_id,
        f'sudo systemctl {action} {service_name}.service',
        region,
    )

    if result['exit_code'] != 0:
        raise RuntimeError(
            f"Failed to {action} {service_name}: {result['stderr'] or result['stdout']}"
        )

    return {'success': True, 'action': action, 'service': service_name}
