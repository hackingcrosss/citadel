from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import gophish_service
from app.utils.decorators import feature_required


@api_bp.route('/gophish/profiles', methods=['GET'])
@login_required
@feature_required('gophish')
def list_gophish_profiles():
    try:
        profiles = gophish_service.list_sending_profiles()
        return jsonify({'profiles': profiles})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/profiles/<int:profile_id>', methods=['GET'])
@login_required
@feature_required('gophish')
def get_gophish_profile(profile_id):
    try:
        profile = gophish_service.get_sending_profile(profile_id)
        return jsonify({'profile': profile})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/profiles', methods=['POST'])
@login_required
@feature_required('gophish')
def create_gophish_profile():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    required = ['name', 'host', 'from_address', 'username', 'password']
    for field in required:
        if not data.get(field):
            return jsonify({'error': f'Missing required field: {field}'}), 400

    profile_data = {
        'name': data['name'],
        'host': data['host'],
        'from_address': data['from_address'],
        'username': data['username'],
        'password': data['password'],
        'interface_type': 'SMTP',
        'ignore_cert_errors': data.get('ignore_cert_errors', False),
    }

    try:
        result = gophish_service.create_sending_profile(profile_data)
        return jsonify({'profile': result}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/gophish/profiles/<int:profile_id>', methods=['DELETE'])
@login_required
@feature_required('gophish')
def delete_gophish_profile(profile_id):
    try:
        gophish_service.delete_sending_profile(profile_id)
        return jsonify({'deleted': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
