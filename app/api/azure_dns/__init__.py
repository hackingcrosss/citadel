from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import azure_dns_service
from app.services.credential_service import get_account_labels


def _zone_label(zone_name):
    """Resolve account label for a zone name."""
    cached = azure_dns_service._zone_account_cache.get(zone_name)
    if cached:
        return cached
    labels = get_account_labels('azure')
    return labels[0] if labels else 'default'


@api_bp.route('/azure-dns/zones', methods=['GET'])
@login_required
def azure_dns_list_zones():
    try:
        zones = azure_dns_service.list_zones_all_accounts()
        return jsonify({'zones': zones})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure-dns/zones/<rg>/<zone_name>/records', methods=['GET'])
@login_required
def azure_dns_list_records(rg, zone_name):
    record_type = request.args.get('type')
    label = _zone_label(zone_name)
    try:
        records = azure_dns_service.list_records(zone_name, rg, record_type=record_type, label=label)
        return jsonify({'records': records})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure-dns/zones/<rg>/<zone_name>/records', methods=['POST'])
@login_required
def azure_dns_create_record(rg, zone_name):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    record_type = data.get('type', '').upper().strip()
    name = data.get('name', '').strip()
    content = data.get('content', '').strip()
    ttl = int(data.get('ttl', 3600))
    if not record_type or not name or not content:
        return jsonify({'error': 'type, name, and content are required'}), 400
    label = _zone_label(zone_name)
    try:
        record = azure_dns_service.create_record(zone_name, rg, record_type, name, content, ttl=ttl, label=label)
        return jsonify({'record': record}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure-dns/zones/<rg>/<zone_name>/records/<record_type>/<name>', methods=['DELETE'])
@login_required
def azure_dns_delete_record(rg, zone_name, record_type, name):
    label = _zone_label(zone_name)
    try:
        result = azure_dns_service.delete_record(zone_name, rg, record_type, name, label=label)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400
