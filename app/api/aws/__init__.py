from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import aws_service
from app import db
from app.models.instance_tag import InstanceTag
from app.models.instance_ssh_config import InstanceSSHConfig
from app.services.credential_service import _get_fernet
from app.services import ssh_service


# --- Instances ---

@api_bp.route('/aws/instances', methods=['GET'])
@login_required
def aws_list_instances():
    region = request.args.get('region')
    try:
        instances = aws_service.list_instances(region)

        # Enrich instances with local tags
        instance_ids = [i['id'] for i in instances]
        if instance_ids:
            tags = InstanceTag.query.filter(InstanceTag.instance_id.in_(instance_ids)).all()
            tag_map = {}
            for t in tags:
                tag_map.setdefault(t.instance_id, []).append(t.tag)
            for inst in instances:
                inst['local_tags'] = tag_map.get(inst['id'], [])
        else:
            for inst in instances:
                inst['local_tags'] = []

        # Enrich instances with SSH config status
        if instance_ids:
            ssh_configs = InstanceSSHConfig.query.filter(
                InstanceSSHConfig.instance_id.in_(instance_ids)
            ).all()
            ssh_set = {c.instance_id for c in ssh_configs}
            for inst in instances:
                inst['ssh_configured'] = inst['id'] in ssh_set
        else:
            for inst in instances:
                inst['ssh_configured'] = False

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


# --- Instance Tags (Local) ---

@api_bp.route('/aws/tags', methods=['GET'])
@login_required
def aws_list_tags():
    instance_id = request.args.get('instance_id')
    try:
        if instance_id:
            tags = InstanceTag.query.filter_by(instance_id=instance_id).all()
            return jsonify({'tags': [t.to_dict() for t in tags]})
        else:
            # Return distinct tag values
            rows = db.session.query(InstanceTag.tag).distinct().order_by(InstanceTag.tag).all()
            return jsonify({'tags': [r[0] for r in rows]})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/tags', methods=['POST'])
@login_required
def aws_add_tag():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    instance_id = data.get('instance_id', '').strip()
    tag = data.get('tag', '').strip()

    if not instance_id or not tag:
        return jsonify({'error': 'instance_id and tag are required'}), 400

    existing = InstanceTag.query.filter_by(instance_id=instance_id, tag=tag).first()
    if existing:
        return jsonify({'tag': existing.to_dict()}), 200

    new_tag = InstanceTag(instance_id=instance_id, tag=tag)
    db.session.add(new_tag)
    db.session.commit()
    return jsonify({'tag': new_tag.to_dict()}), 201


@api_bp.route('/aws/tags', methods=['DELETE'])
@login_required
def aws_remove_tag():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    instance_id = data.get('instance_id', '').strip()
    tag = data.get('tag', '').strip()

    if not instance_id or not tag:
        return jsonify({'error': 'instance_id and tag are required'}), 400

    existing = InstanceTag.query.filter_by(instance_id=instance_id, tag=tag).first()
    if not existing:
        return jsonify({'error': 'Tag not found'}), 404

    db.session.delete(existing)
    db.session.commit()
    return jsonify({'deleted': True})


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


# --- SSH Configs ---

@api_bp.route('/aws/ssh-configs', methods=['GET'])
@login_required
def aws_list_ssh_configs():
    try:
        configs = InstanceSSHConfig.query.all()
        return jsonify({'ssh_configs': [c.to_dict() for c in configs]})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/ssh-configs/<instance_id>', methods=['GET'])
@login_required
def aws_get_ssh_config(instance_id):
    try:
        config = InstanceSSHConfig.query.filter_by(instance_id=instance_id).first()
        if not config:
            return jsonify({'ssh_config': None})
        return jsonify({'ssh_config': config.to_dict()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/ssh-configs', methods=['POST'])
@login_required
def aws_save_ssh_config():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    instance_id = data.get('instance_id', '').strip()
    ssh_username = data.get('ssh_username', 'ec2-user').strip()
    private_key = data.get('private_key', '').strip()
    use_public_ip = data.get('use_public_ip', True)
    key_label = data.get('key_label', '').strip()

    if not instance_id:
        return jsonify({'error': 'instance_id is required'}), 400
    if not ssh_username:
        return jsonify({'error': 'ssh_username is required'}), 400

    try:
        config = InstanceSSHConfig.query.filter_by(instance_id=instance_id).first()

        if config:
            # Update existing
            config.ssh_username = ssh_username
            config.use_public_ip = use_public_ip
            config.key_label = key_label
            if private_key:
                f = _get_fernet()
                config.encrypted_private_key = f.encrypt(private_key.encode()).decode()
        else:
            # Create new — private_key is required for new configs
            if not private_key:
                return jsonify({'error': 'private_key is required for new configurations'}), 400
            f = _get_fernet()
            encrypted = f.encrypt(private_key.encode()).decode()
            config = InstanceSSHConfig(
                instance_id=instance_id,
                ssh_username=ssh_username,
                encrypted_private_key=encrypted,
                use_public_ip=use_public_ip,
                key_label=key_label,
            )
            db.session.add(config)

        db.session.commit()
        return jsonify({'ssh_config': config.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/ssh-configs/<instance_id>', methods=['DELETE'])
@login_required
def aws_delete_ssh_config(instance_id):
    try:
        config = InstanceSSHConfig.query.filter_by(instance_id=instance_id).first()
        if not config:
            return jsonify({'error': 'SSH config not found'}), 404
        db.session.delete(config)
        db.session.commit()
        return jsonify({'deleted': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# --- Instance Services (via SSH) ---

@api_bp.route('/aws/instances/<instance_id>/services', methods=['GET'])
@login_required
def aws_list_services(instance_id):
    region = request.args.get('region')
    try:
        services = ssh_service.list_services(instance_id, region)
        return jsonify({'services': services})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/instances/<instance_id>/services/<service_name>', methods=['GET'])
@login_required
def aws_get_service_status(instance_id, service_name):
    region = request.args.get('region')
    try:
        status = ssh_service.get_service_status(instance_id, service_name, region)
        return jsonify({'service': status})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/aws/instances/<instance_id>/services/<service_name>/<action>', methods=['POST'])
@login_required
def aws_service_action(instance_id, service_name, action):
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'error': 'Invalid action. Must be start, stop, or restart'}), 400
    region = request.args.get('region') or (request.get_json() or {}).get('region')
    try:
        result = ssh_service.service_action(instance_id, service_name, action, region)
        return jsonify({'result': result})
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
