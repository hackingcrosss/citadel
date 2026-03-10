from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import cobaltstrike_service
from app.utils.decorators import feature_required
from app.services.project_service import build_project_tag_map, assert_resource_writable

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
@feature_required('cobaltstrike')
def list_cs_listeners():
    try:
        listeners = cobaltstrike_service.list_listeners()

        # Enrich listeners with project tag
        names = [l.get('name', '') for l in listeners if l.get('name')]
        tag_map = build_project_tag_map('cs_listener', names)
        for listener in listeners:
            tag = tag_map.get(listener.get('name', ''))
            listener['project_id'] = tag['project_id'] if tag else None
            listener['project_code'] = tag['project_code'] if tag else None
            listener['project_resource_id'] = tag['project_resource_id'] if tag else None

        return jsonify({'listeners': listeners})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/cobaltstrike/listeners/<path:listener_name>', methods=['GET'])
@login_required
@feature_required('cobaltstrike')
def get_cs_listener(listener_name):
    try:
        listener = cobaltstrike_service.get_listener(listener_name)
        return jsonify({'listener': listener})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/cobaltstrike/listeners', methods=['POST'])
@login_required
@feature_required('cobaltstrike')
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

    # Write guard — creating a listener is a write action
    assert_resource_writable('cs_listener', data.get('name', ''), current_user)

    try:
        result = cobaltstrike_service.create_listener(listener_type, data)
        return jsonify({'listener': result}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/cobaltstrike/listeners/<path:listener_name>', methods=['DELETE'])
@login_required
@feature_required('cobaltstrike')
def delete_cs_listener(listener_name):
    assert_resource_writable('cs_listener', listener_name, current_user)
    try:
        cobaltstrike_service.delete_listener(listener_name)
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
