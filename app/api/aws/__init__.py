from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import aws_service


# --- Instances ---

@api_bp.route('/aws/instances', methods=['GET'])
@login_required
def aws_list_instances():
    region = request.args.get('region')
    try:
        instances = aws_service.list_instances(region)
        return jsonify({'instances': instances})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/instances/<instance_id>', methods=['GET'])
@login_required
def aws_get_instance(instance_id):
    region = request.args.get('region')
    try:
        instance = aws_service.get_instance(instance_id, region)
        return jsonify({'instance': instance})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/instances/start', methods=['POST'])
@login_required
def aws_start_instances():
    data = request.get_json()
    ids = data.get('instance_ids', [])
    region = data.get('region')
    if not ids:
        return jsonify({'error': 'No instance IDs provided'}), 400
    try:
        result = aws_service.start_instances(ids, region)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/instances/stop', methods=['POST'])
@login_required
def aws_stop_instances():
    data = request.get_json()
    ids = data.get('instance_ids', [])
    region = data.get('region')
    if not ids:
        return jsonify({'error': 'No instance IDs provided'}), 400
    try:
        result = aws_service.stop_instances(ids, region)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/instances/reboot', methods=['POST'])
@login_required
def aws_reboot_instances():
    data = request.get_json()
    ids = data.get('instance_ids', [])
    region = data.get('region')
    if not ids:
        return jsonify({'error': 'No instance IDs provided'}), 400
    try:
        result = aws_service.reboot_instances(ids, region)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/instances/terminate', methods=['POST'])
@login_required
def aws_terminate_instances():
    data = request.get_json()
    ids = data.get('instance_ids', [])
    region = data.get('region')
    if not ids:
        return jsonify({'error': 'No instance IDs provided'}), 400
    try:
        result = aws_service.terminate_instances(ids, region)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Security Groups ---

@api_bp.route('/aws/security-groups', methods=['GET'])
@login_required
def aws_list_security_groups():
    region = request.args.get('region')
    try:
        groups = aws_service.list_security_groups(region)
        return jsonify({'security_groups': groups})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/security-groups/<group_id>', methods=['GET'])
@login_required
def aws_get_security_group(group_id):
    region = request.args.get('region')
    try:
        group = aws_service.get_security_group(group_id, region)
        return jsonify({'security_group': group})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Key Pairs ---

@api_bp.route('/aws/key-pairs', methods=['GET'])
@login_required
def aws_list_key_pairs():
    region = request.args.get('region')
    try:
        pairs = aws_service.list_key_pairs(region)
        return jsonify({'key_pairs': pairs})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Regions ---

@api_bp.route('/aws/regions', methods=['GET'])
@login_required
def aws_list_regions():
    try:
        regions = aws_service.list_regions()
        return jsonify({'regions': regions})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
