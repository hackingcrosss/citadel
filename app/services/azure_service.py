import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app
from app.services.credential_service import get_credential, get_account_labels

_log = logging.getLogger(__name__)

# vm_id (rg/name) -> account_label, populated by list_vms_all_accounts()
_vm_account_cache: dict = {}


def _get_compute_client(label='default'):
    from azure.identity import ClientSecretCredential
    from azure.mgmt.compute import ComputeManagementClient
    tenant_id = get_credential('azure', 'tenant_id', label=label)
    client_id = get_credential('azure', 'client_id', label=label)
    client_secret = get_credential('azure', 'client_secret', label=label)
    subscription_id = get_credential('azure', 'subscription_id', label=label)
    if not all([tenant_id, client_id, client_secret, subscription_id]):
        raise ValueError(f"Azure credentials not fully configured for account '{label}'. "
                         "Set tenant_id, client_id, client_secret, and subscription_id in Settings.")
    cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    return ComputeManagementClient(cred, subscription_id), subscription_id


def _get_network_client(label='default'):
    from azure.identity import ClientSecretCredential
    from azure.mgmt.network import NetworkManagementClient
    tenant_id = get_credential('azure', 'tenant_id', label=label)
    client_id = get_credential('azure', 'client_id', label=label)
    client_secret = get_credential('azure', 'client_secret', label=label)
    subscription_id = get_credential('azure', 'subscription_id', label=label)
    if not all([tenant_id, client_id, client_secret, subscription_id]):
        raise ValueError(f"Azure credentials not fully configured for account '{label}'.")
    cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    return NetworkManagementClient(cred, subscription_id)


def verify_credentials(label='default'):
    from azure.identity import ClientSecretCredential
    from azure.mgmt.resource import ResourceManagementClient
    tenant_id = get_credential('azure', 'tenant_id', label=label)
    client_id = get_credential('azure', 'client_id', label=label)
    client_secret = get_credential('azure', 'client_secret', label=label)
    subscription_id = get_credential('azure', 'subscription_id', label=label)
    if not all([tenant_id, client_id, client_secret, subscription_id]):
        raise ValueError(f"Azure credentials not fully configured for account '{label}'.")
    cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    rm_client = ResourceManagementClient(cred, subscription_id)
    groups = list(rm_client.resource_groups.list())
    return {'subscription_id': subscription_id, 'resource_group_count': len(groups)}


def vm_instance_id(resource_group, vm_name):
    """Stable local key for a VM used in InstanceTag / InstanceSSHConfig."""
    return f"{resource_group}/{vm_name}"


def _rg_from_azure_id(azure_id):
    """Extract resource group name from an Azure resource ID string."""
    parts = azure_id.split('/resourceGroups/')
    if len(parts) > 1:
        return parts[1].split('/')[0]
    return ''


def _resolve_ips(vm, nc_client):
    """Resolve public and private IPs for a VM from its NIC list."""
    public_ip = ''
    private_ip = ''
    if not (vm.network_profile and vm.network_profile.network_interfaces):
        return public_ip, private_ip
    for nic_ref in vm.network_profile.network_interfaces:
        nic_id = nic_ref.id
        nic_rg = _rg_from_azure_id(nic_id)
        nic_name = nic_id.split('/')[-1]
        try:
            nic = nc_client.network_interfaces.get(nic_rg, nic_name)
            for ip_config in (nic.ip_configurations or []):
                if ip_config.private_ip_address and not private_ip:
                    private_ip = ip_config.private_ip_address
                if ip_config.public_ip_address and not public_ip:
                    pip_id = ip_config.public_ip_address.id
                    pip_rg = _rg_from_azure_id(pip_id)
                    pip_name = pip_id.split('/')[-1]
                    try:
                        pip = nc_client.public_ip_addresses.get(pip_rg, pip_name)
                        public_ip = pip.ip_address or ''
                    except Exception:
                        pass
        except Exception:
            pass
        if private_ip:
            break
    return public_ip, private_ip


def _format_vm(vm, public_ip='', private_ip=''):
    """Normalise an Azure VM SDK object to a plain dict."""
    state = 'unknown'
    if vm.instance_view and vm.instance_view.statuses:
        for s in vm.instance_view.statuses:
            if s.code and s.code.startswith('PowerState/'):
                raw = s.code.split('/')[-1]
                state = {
                    'running': 'running',
                    'deallocated': 'stopped',
                    'deallocating': 'stopping',
                    'stopped': 'stopped',
                    'starting': 'pending',
                }.get(raw, raw)
                break

    rg = _rg_from_azure_id(vm.id) if vm.id else ''
    os_type = ''
    if vm.storage_profile and vm.storage_profile.os_disk:
        os_type = str(vm.storage_profile.os_disk.os_type or '')

    return {
        'id': vm_instance_id(rg, vm.name),
        'vm_name': vm.name,
        'resource_group': rg,
        'location': vm.location or '',
        'size': (vm.hardware_profile.vm_size if vm.hardware_profile else ''),
        'state': state,
        'public_ip': public_ip,
        'private_ip': private_ip,
        'os_type': os_type,
        'tags': dict(vm.tags or {}),
    }


def list_vms(resource_group=None, label='default'):
    compute, _ = _get_compute_client(label)
    nc = _get_network_client(label)
    raw_vms = (
        list(compute.virtual_machines.list(resource_group))
        if resource_group
        else list(compute.virtual_machines.list_all())
    )
    if not raw_vms:
        return []

    # Fetch instanceView + resolve IPs for all VMs in parallel
    def _enrich(vm):
        rg = _rg_from_azure_id(vm.id)
        try:
            vm_iv = compute.virtual_machines.get(rg, vm.name, expand='instanceView')
        except Exception:
            vm_iv = vm
        pub, priv = _resolve_ips(vm_iv, nc)
        return _format_vm(vm_iv, pub, priv)

    results = []
    with ThreadPoolExecutor(max_workers=min(len(raw_vms), 10)) as pool:
        futures = {pool.submit(_enrich, vm): vm for vm in raw_vms}
        for future in as_completed(futures):
            try:
                results.append(future.result(timeout=30))
            except Exception as exc:
                vm = futures[future]
                _log.warning("Failed to enrich VM '%s': %s", vm.name, exc)
                results.append(_format_vm(vm))
    return results


def _fetch_vms_for_account(lbl):
    vms = list_vms(label=lbl)
    for vm in vms:
        vm['account_label'] = lbl
    return vms


def list_vms_all_accounts():
    """Fetch VMs from every configured Azure account in parallel."""
    labels = get_account_labels('azure')
    if not labels:
        return []

    all_vms = []

    if len(labels) == 1:
        try:
            all_vms = _fetch_vms_for_account(labels[0])
            _vm_account_cache.update({v['id']: labels[0] for v in all_vms})
        except Exception as exc:
            _log.warning("Azure VM fetch failed for account '%s': %s", labels[0], exc)
        return all_vms

    app = current_app._get_current_object()

    def _fetch_in_context(lbl):
        with app.app_context():
            return _fetch_vms_for_account(lbl)

    with ThreadPoolExecutor(max_workers=min(len(labels), 8)) as pool:
        futures = {pool.submit(_fetch_in_context, lbl): lbl for lbl in labels}
        try:
            for future in as_completed(futures, timeout=60):
                lbl = futures[future]
                try:
                    all_vms.extend(future.result())
                except Exception as exc:
                    _log.warning("Azure VM fetch failed for account '%s': %s", lbl, exc)
        except TimeoutError:
            _log.warning("Azure VM fetch timed out waiting for all accounts")

    _vm_account_cache.update({v['id']: v['account_label'] for v in all_vms})
    return all_vms


def get_vm(resource_group, vm_name, label='default'):
    compute, _ = _get_compute_client(label)
    nc = _get_network_client(label)
    vm = compute.virtual_machines.get(resource_group, vm_name, expand='instanceView')
    pub, priv = _resolve_ips(vm, nc)
    return _format_vm(vm, pub, priv)


def start_vm(resource_group, vm_name, label='default'):
    compute, _ = _get_compute_client(label)
    compute.virtual_machines.begin_start(resource_group, vm_name)
    return {'started': vm_name}


def stop_vm(resource_group, vm_name, label='default'):
    compute, _ = _get_compute_client(label)
    compute.virtual_machines.begin_deallocate(resource_group, vm_name)
    return {'stopped': vm_name}


def restart_vm(resource_group, vm_name, label='default'):
    compute, _ = _get_compute_client(label)
    compute.virtual_machines.begin_restart(resource_group, vm_name)
    return {'restarted': vm_name}


def delete_vm(resource_group, vm_name, label='default'):
    compute, _ = _get_compute_client(label)
    compute.virtual_machines.begin_delete(resource_group, vm_name)
    return {'deleted': vm_name}


def list_resource_groups(label='default'):
    from azure.identity import ClientSecretCredential
    from azure.mgmt.resource import ResourceManagementClient
    tenant_id = get_credential('azure', 'tenant_id', label=label)
    client_id = get_credential('azure', 'client_id', label=label)
    client_secret = get_credential('azure', 'client_secret', label=label)
    subscription_id = get_credential('azure', 'subscription_id', label=label)
    if not all([tenant_id, client_id, client_secret, subscription_id]):
        raise ValueError(f"Azure credentials not configured for account '{label}'.")
    cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    rm_client = ResourceManagementClient(cred, subscription_id)
    return [rg.name for rg in rm_client.resource_groups.list()]
