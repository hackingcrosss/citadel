from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import cobaltstrike_service

# Valid listener types — these are the exact URL slugs for POST /api/v1/listeners/{type}
VALID_TYPES = {'http', 'https', 'dns', 'smb', 'tcp', 'foreignHttp', 'foreignHttps', 'externalC2', 'userDefinedC2'}

# Required fields per listener type (validated before sending to CS)
TYPE_REQUIRED = {
    'http':           ['name', 'host'],
    'https':          ['name', 'host'],
    'dns':            ['name', 'host'],
    'smb':            ['name', 'pipename'],
    'tcp':            ['name', 'port'],
    'foreignHttp':    ['name', 'host', 'port'],
    'foreignHttps':   ['name', 'host', 'port'],
    'externalC2':     ['name', 'port'],
    'userDefinedC2':  ['name', 'port'],
}


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

    listener_type = data.pop('type', '')
    if not listener_type:
        return jsonify({'error': 'Missing required field: type'}), 400
    if listener_type not in VALID_TYPES:
        return jsonify({'error': f'Unknown listener type: {listener_type}. Valid: {", ".join(sorted(VALID_TYPES))}'}), 400

    required = TYPE_REQUIRED.get(listener_type, ['name'])
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Missing required field for {listener_type}: {field}'}), 400

    try:
        result = cobaltstrike_service.create_listener(listener_type, data)
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
