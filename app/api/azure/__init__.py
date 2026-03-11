from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import azure_service
from app import db
from app.models.instance_tag import InstanceTag
from app.models.instance_ssh_config import InstanceSSHConfig
from app.services.credential_service import _get_fernet, get_account_labels
from app.services.project_service import build_project_tag_map, assert_resource_writable


def _vm_label(vm_id):
    """Resolve account label for a VM id (rg/name)."""
    cached = azure_service._vm_account_cache.get(vm_id)
    if cached:
        return cached
    labels = get_account_labels('azure')
    return labels[0] if labels else 'default'


# --- VM list ---

@api_bp.route('/azure/vms', methods=['GET'])
@login_required
def azure_list_vms():
    try:
        vms = azure_service.list_vms_all_accounts()
        vm_ids = [v['id'] for v in vms]

        # Enrich with local tags
        if vm_ids:
            tags = InstanceTag.query.filter(
                InstanceTag.provider == 'azure',
                InstanceTag.instance_id.in_(vm_ids)
            ).all()
            tag_map = {}
            for t in tags:
                tag_map.setdefault(t.instance_id, []).append(t.tag)
            for vm in vms:
                vm['local_tags'] = tag_map.get(vm['id'], [])
        else:
            for vm in vms:
                vm['local_tags'] = []

        # Enrich with SSH config status
        if vm_ids:
            ssh_configs = InstanceSSHConfig.query.filter(
                InstanceSSHConfig.provider == 'azure',
                InstanceSSHConfig.instance_id.in_(vm_ids)
            ).all()
            ssh_set = {c.instance_id for c in ssh_configs}
            for vm in vms:
                vm['ssh_configured'] = vm['id'] in ssh_set
        else:
            for vm in vms:
                vm['ssh_configured'] = False

        # Enrich with project tag
        proj_map = build_project_tag_map('azure', vm_ids)
        for vm in vms:
            tag = proj_map.get(vm['id'])
            vm['project_id'] = tag['project_id'] if tag else None
            vm['project_code'] = tag['project_code'] if tag else None
            vm['project_resource_id'] = tag['project_resource_id'] if tag else None

        return jsonify({'vms': vms})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure/vms/<rg>/<vm_name>', methods=['GET'])
@login_required
def azure_get_vm(rg, vm_name):
    vm_id = azure_service.vm_instance_id(rg, vm_name)
    label = _vm_label(vm_id)
    try:
        vm = azure_service.get_vm(rg, vm_name, label=label)
        return jsonify({'vm': vm})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure/vms/<rg>/<vm_name>/start', methods=['POST'])
@login_required
def azure_start_vm(rg, vm_name):
    vm_id = azure_service.vm_instance_id(rg, vm_name)
    assert_resource_writable('azure', vm_id, current_user)
    label = _vm_label(vm_id)
    try:
        result = azure_service.start_vm(rg, vm_name, label=label)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure/vms/<rg>/<vm_name>/stop', methods=['POST'])
@login_required
def azure_stop_vm(rg, vm_name):
    vm_id = azure_service.vm_instance_id(rg, vm_name)
    assert_resource_writable('azure', vm_id, current_user)
    label = _vm_label(vm_id)
    try:
        result = azure_service.stop_vm(rg, vm_name, label=label)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure/vms/<rg>/<vm_name>/restart', methods=['POST'])
@login_required
def azure_restart_vm(rg, vm_name):
    vm_id = azure_service.vm_instance_id(rg, vm_name)
    assert_resource_writable('azure', vm_id, current_user)
    label = _vm_label(vm_id)
    try:
        result = azure_service.restart_vm(rg, vm_name, label=label)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure/vms/<rg>/<vm_name>/delete', methods=['POST'])
@login_required
def azure_delete_vm(rg, vm_name):
    vm_id = azure_service.vm_instance_id(rg, vm_name)
    assert_resource_writable('azure', vm_id, current_user)
    label = _vm_label(vm_id)
    try:
        result = azure_service.delete_vm(rg, vm_name, label=label)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- SSH Configs ---

@api_bp.route('/azure/vms/<rg>/<vm_name>/ssh', methods=['GET'])
@login_required
def azure_get_ssh_config(rg, vm_name):
    vm_id = azure_service.vm_instance_id(rg, vm_name)
    try:
        config = InstanceSSHConfig.query.filter_by(provider='azure', instance_id=vm_id).first()
        return jsonify({'ssh_config': config.to_dict() if config else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure/vms/<rg>/<vm_name>/ssh', methods=['POST'])
@login_required
def azure_save_ssh_config(rg, vm_name):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    vm_id = azure_service.vm_instance_id(rg, vm_name)
    ssh_username = (data.get('ssh_username', '') or 'azureuser').strip()
    private_key = data.get('private_key', '').strip()
    use_public_ip = data.get('use_public_ip', True)
    key_label = data.get('key_label', '').strip()

    try:
        config = InstanceSSHConfig.query.filter_by(provider='azure', instance_id=vm_id).first()
        if config:
            config.ssh_username = ssh_username
            config.use_public_ip = use_public_ip
            config.key_label = key_label
            if private_key:
                f = _get_fernet()
                config.encrypted_private_key = f.encrypt(private_key.encode()).decode()
        else:
            if not private_key:
                return jsonify({'error': 'private_key is required for new configurations'}), 400
            f = _get_fernet()
            config = InstanceSSHConfig(
                provider='azure',
                instance_id=vm_id,
                ssh_username=ssh_username,
                encrypted_private_key=f.encrypt(private_key.encode()).decode(),
                use_public_ip=use_public_ip,
                key_label=key_label,
            )
            db.session.add(config)
        db.session.commit()
        return jsonify({'ssh_config': config.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure/vms/<rg>/<vm_name>/ssh', methods=['DELETE'])
@login_required
def azure_delete_ssh_config(rg, vm_name):
    vm_id = azure_service.vm_instance_id(rg, vm_name)
    try:
        config = InstanceSSHConfig.query.filter_by(provider='azure', instance_id=vm_id).first()
        if not config:
            return jsonify({'error': 'SSH config not found'}), 404
        db.session.delete(config)
        db.session.commit()
        return jsonify({'deleted': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


# --- Local Tags ---

@api_bp.route('/azure/tags', methods=['GET'])
@login_required
def azure_list_distinct_tags():
    try:
        rows = (db.session.query(InstanceTag.tag)
                .filter_by(provider='azure')
                .distinct()
                .order_by(InstanceTag.tag)
                .all())
        return jsonify({'tags': [r[0] for r in rows]})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure/vms/<rg>/<vm_name>/tags', methods=['GET'])
@login_required
def azure_get_vm_tags(rg, vm_name):
    vm_id = azure_service.vm_instance_id(rg, vm_name)
    try:
        tags = InstanceTag.query.filter_by(provider='azure', instance_id=vm_id).all()
        return jsonify({'tags': [t.to_dict() for t in tags]})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/azure/vms/<rg>/<vm_name>/tags', methods=['POST'])
@login_required
def azure_add_vm_tag(rg, vm_name):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    tag = (data.get('tag') or '').strip()
    if not tag:
        return jsonify({'error': 'tag is required'}), 400

    vm_id = azure_service.vm_instance_id(rg, vm_name)
    existing = InstanceTag.query.filter_by(provider='azure', instance_id=vm_id, tag=tag).first()
    if existing:
        return jsonify({'tag': existing.to_dict()}), 200

    new_tag = InstanceTag(provider='azure', instance_id=vm_id, tag=tag)
    db.session.add(new_tag)
    db.session.commit()
    return jsonify({'tag': new_tag.to_dict()}), 201


@api_bp.route('/azure/vms/<rg>/<vm_name>/tags/<tag>', methods=['DELETE'])
@login_required
def azure_remove_vm_tag(rg, vm_name, tag):
    vm_id = azure_service.vm_instance_id(rg, vm_name)
    existing = InstanceTag.query.filter_by(provider='azure', instance_id=vm_id, tag=tag).first()
    if not existing:
        return jsonify({'error': 'Tag not found'}), 404
    db.session.delete(existing)
    db.session.commit()
    return jsonify({'deleted': True})


# --- Resource Groups ---

@api_bp.route('/azure/resource-groups', methods=['GET'])
@login_required
def azure_list_resource_groups():
    label = request.args.get('label', 'default')
    try:
        rgs = azure_service.list_resource_groups(label=label)
        return jsonify({'resource_groups': rgs})
    except Exception as e:
        return jsonify({'error': str(e)}), 400
