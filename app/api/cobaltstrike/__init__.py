from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import cobaltstrike_service


@api_bp.route('/cobaltstrike/listeners', methods=['GET'])
@login_required
def list_cs_listeners():
    try:
        listeners = cobaltstrike_service.list_listeners()
        return jsonify({'listeners': listeners})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/cobaltstrike/listeners/<path:listener_name>', methods=['GET'])
@login_required
def get_cs_listener(listener_name):
    try:
        listener = cobaltstrike_service.get_listener(listener_name)
        return jsonify({'listener': listener})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/cobaltstrike/listeners', methods=['POST'])
@login_required
def create_cs_listener():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    listener_type = data.get('type', '').lower()
    if not listener_type:
        return jsonify({'error': 'Missing required field: type'}), 400
    if not data.get('name'):
        return jsonify({'error': 'Missing required field: name'}), 400

    type_required = {
        'http':    ['host', 'httpPort'],
        'https':   ['host', 'httpPort'],
        'dns':     ['host', 'dnsPort'],
        'smb':     ['pipeName'],
        'tcp':     ['host', 'port'],
        'foreign': ['host', 'port'],
    }

    required = type_required.get(listener_type, [])
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Missing required field for {listener_type}: {field}'}), 400

    # Map our type selector to the CS REST API payload string
    payload_map = {
        'http':    'windows/beacon_http/reverse_http',
        'https':   'windows/beacon_https/reverse_https',
        'dns':     'windows/beacon_dns/reverse_dns_txt',
        'smb':     'windows/beacon_smb/bind_pipe',
        'tcp':     'windows/beacon_tcp/bind_tcp',
        'foreign': 'windows/foreign/reverse_https',
    }

    # Build the CS API payload — replace 'type' with 'payload'
    cs_data = {k: v for k, v in data.items() if k != 'type'}
    cs_data['payload'] = payload_map.get(listener_type, listener_type)

    try:
        result = cobaltstrike_service.create_listener(cs_data)
        return jsonify({'listener': result}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/cobaltstrike/listeners/<path:listener_name>', methods=['DELETE'])
@login_required
def delete_cs_listener(listener_name):
    try:
        cobaltstrike_service.delete_listener(listener_name)
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
