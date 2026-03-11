import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app
from app.services.credential_service import get_credential, get_account_labels

_log = logging.getLogger(__name__)

# zone_name -> account_label, populated by list_zones_all_accounts()
_zone_account_cache: dict = {}


def _get_dns_client(label='default'):
    from azure.identity import ClientSecretCredential
    from azure.mgmt.dns import DnsManagementClient
    tenant_id = get_credential('azure', 'tenant_id', label=label)
    client_id = get_credential('azure', 'client_id', label=label)
    client_secret = get_credential('azure', 'client_secret', label=label)
    subscription_id = get_credential('azure', 'subscription_id', label=label)
    if not all([tenant_id, client_id, client_secret, subscription_id]):
        raise ValueError(f"Azure credentials not fully configured for account '{label}'. "
                         "Set tenant_id, client_id, client_secret, and subscription_id in Settings.")
    cred = ClientSecretCredential(tenant_id=tenant_id, client_id=client_id, client_secret=client_secret)
    return DnsManagementClient(cred, subscription_id)


def _rg_from_azure_id(azure_id):
    parts = azure_id.split('/resourceGroups/')
    if len(parts) > 1:
        return parts[1].split('/')[0]
    return ''


def _format_zone(zone, label):
    rg = _rg_from_azure_id(zone.id) if zone.id else ''
    return {
        'id': f"{rg}/{zone.name}",   # composite key used as zone selector value
        'name': zone.name,
        'resource_group': rg,
        'account_label': label,
        'record_count': zone.number_of_record_sets or 0,
        'name_servers': list(zone.name_servers or []),
    }


def _fetch_zones_for_account(lbl):
    client = _get_dns_client(lbl)
    zones = list(client.zones.list())
    result = [_format_zone(z, lbl) for z in zones]
    return result


def list_zones_all_accounts():
    """Fetch DNS zones from every configured Azure account in parallel."""
    labels = get_account_labels('azure')
    if not labels:
        return []

    all_zones = []

    if len(labels) == 1:
        try:
            all_zones = _fetch_zones_for_account(labels[0])
            _zone_account_cache.update({z['name']: labels[0] for z in all_zones})
        except Exception as exc:
            _log.warning("Azure DNS zone fetch failed for account '%s': %s", labels[0], exc)
        return all_zones

    app = current_app._get_current_object()

    def _fetch_in_context(lbl):
        with app.app_context():
            return _fetch_zones_for_account(lbl)

    with ThreadPoolExecutor(max_workers=min(len(labels), 8)) as pool:
        futures = {pool.submit(_fetch_in_context, lbl): lbl for lbl in labels}
        for future in as_completed(futures):
            lbl = futures[future]
            try:
                all_zones.extend(future.result())
            except Exception as exc:
                _log.warning("Azure DNS zone fetch failed for account '%s': %s", lbl, exc)

    _zone_account_cache.update({z['name']: z['account_label'] for z in all_zones})
    return all_zones


def _normalise_record(rs, zone_name):
    """Expand an Azure RecordSet into one dict per value (matching CF flat format)."""
    rtype = rs.type.split('/')[-1] if rs.type else ''
    ttl = rs.ttl or 3600
    name = rs.name

    records = []

    def _add(content):
        records.append({'type': rtype, 'name': name, 'content': content, 'ttl': ttl,
                        'azure_rs_name': rs.name})

    if rtype == 'A' and rs.a_records:
        for r in rs.a_records:
            _add(r.ipv4_address)
    elif rtype == 'AAAA' and rs.aaaa_records:
        for r in rs.aaaa_records:
            _add(r.ipv6_address)
    elif rtype == 'CNAME' and rs.cname_record:
        _add(rs.cname_record.cname)
    elif rtype == 'MX' and rs.mx_records:
        for r in rs.mx_records:
            _add(r.exchange)
    elif rtype == 'TXT' and rs.txt_records:
        for r in rs.txt_records:
            _add(' '.join(r.value))
    elif rtype == 'NS' and rs.ns_records:
        for r in rs.ns_records:
            _add(r.nsdname)
    elif rtype == 'SOA' and rs.soa_record:
        soa = rs.soa_record
        _add(f"{soa.host} {soa.email} {soa.serial_number} {soa.refresh_time} {soa.retry_time} {soa.expire_time} {soa.minimum_ttl}")
    elif rtype == 'SRV' and rs.srv_records:
        for r in rs.srv_records:
            _add(f"{r.priority} {r.weight} {r.port} {r.target}")
    elif rtype == 'CAA' and rs.caa_records:
        for r in rs.caa_records:
            _add(f"{r.flags} {r.tag} {r.value}")
    else:
        _add('')

    return records


def list_records(zone_name, resource_group, record_type=None, label='default'):
    """List records in a zone, normalised to flat {type, name, content, ttl} dicts."""
    client = _get_dns_client(label)
    record_sets = list(client.record_sets.list_by_dns_zone(resource_group, zone_name))
    result = []
    for rs in record_sets:
        rtype = rs.type.split('/')[-1] if rs.type else ''
        if record_type and rtype != record_type.upper():
            continue
        result.extend(_normalise_record(rs, zone_name))
    return result


def create_record(zone_name, resource_group, record_type, name, content, ttl=3600, label='default'):
    """Create or update a record set with a single value."""
    client = _get_dns_client(label)
    rtype = record_type.upper()

    # Build the record set parameters
    from azure.mgmt.dns.models import RecordSet, ARecord, AaaaRecord, CnameRecord, MxRecord, TxtRecord, NsRecord

    params = RecordSet(ttl=ttl)

    if rtype == 'A':
        params.a_records = [ARecord(ipv4_address=content)]
    elif rtype == 'AAAA':
        params.aaaa_records = [AaaaRecord(ipv6_address=content)]
    elif rtype == 'CNAME':
        params.cname_record = CnameRecord(cname=content)
    elif rtype == 'MX':
        # content: "10 mail.example.com"
        parts = content.split(None, 1)
        pref = int(parts[0]) if parts else 10
        exch = parts[1] if len(parts) > 1 else content
        from azure.mgmt.dns.models import MxRecord as _MX
        params.mx_records = [_MX(preference=pref, exchange=exch)]
    elif rtype == 'TXT':
        params.txt_records = [TxtRecord(value=[content])]
    elif rtype == 'NS':
        params.ns_records = [NsRecord(nsdname=content)]
    else:
        raise ValueError(f"Record type '{rtype}' is not supported for create.")

    rs = client.record_sets.create_or_update(resource_group, zone_name, name, rtype, params)
    return {'type': rtype, 'name': name, 'content': content, 'ttl': ttl}


def delete_record(zone_name, resource_group, record_type, name, label='default'):
    """Delete a record set by type and name."""
    client = _get_dns_client(label)
    client.record_sets.delete(resource_group, zone_name, name, record_type.upper())
    return {'deleted': True}
