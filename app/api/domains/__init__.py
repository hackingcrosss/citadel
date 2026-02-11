from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import dns_service


# --- Zones ---

@api_bp.route('/domains/zones', methods=['GET'])
@login_required
def list_zones():
    try:
        name_filter = request.args.get('name')
        page = request.args.get('page', 1, type=int)
        zones, page_info = dns_service.list_zones(name_filter=name_filter, page=page)
        return jsonify({'zones': zones, 'page_info': page_info})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>', methods=['GET'])
@login_required
def get_zone(zone_id):
    try:
        zone = dns_service.get_zone(zone_id)
        return jsonify({'zone': zone})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- DNS Records ---

@api_bp.route('/domains/zones/<zone_id>/records', methods=['GET'])
@login_required
def list_dns_records(zone_id):
    try:
        record_type = request.args.get('type')
        name = request.args.get('name')
        records = dns_service.list_dns_records(zone_id, record_type=record_type, name=name)
        return jsonify({'records': records})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/records', methods=['POST'])
@login_required
def create_dns_record(zone_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    for field in ('type', 'name', 'content'):
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    try:
        record = dns_service.create_dns_record(
            zone_id,
            record_type=data['type'],
            name=data['name'],
            content=data['content'],
            ttl=data.get('ttl', 1),
            proxied=data.get('proxied', False),
            priority=data.get('priority')
        )
        return jsonify({'record': record}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/records/<record_id>', methods=['PUT'])
@login_required
def update_dns_record(zone_id, record_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    for field in ('type', 'name', 'content'):
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400

    try:
        record = dns_service.update_dns_record(
            zone_id, record_id,
            record_type=data['type'],
            name=data['name'],
            content=data['content'],
            ttl=data.get('ttl', 1),
            proxied=data.get('proxied', False),
            priority=data.get('priority')
        )
        return jsonify({'record': record})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/records/<record_id>', methods=['DELETE'])
@login_required
def delete_dns_record(zone_id, record_id):
    try:
        dns_service.delete_dns_record(zone_id, record_id)
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- SSL ---

@api_bp.route('/domains/zones/<zone_id>/ssl', methods=['GET'])
@login_required
def get_ssl(zone_id):
    try:
        result = dns_service.get_ssl_setting(zone_id)
        return jsonify({'ssl': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/domains/zones/<zone_id>/ssl', methods=['PATCH'])
@login_required
def set_ssl(zone_id):
    data = request.get_json()
    value = data.get('value') if data else None
    if value not in ('off', 'flexible', 'full', 'strict'):
        return jsonify({'error': 'Invalid SSL value. Use: off, flexible, full, strict'}), 400

    try:
        result = dns_service.set_ssl_setting(zone_id, value)
        return jsonify({'ssl': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
