from flask import request, jsonify, abort
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import docker_service
from app.services.project_service import (
    build_project_tag_map,
    assert_resource_writable,
    assert_resource_readable,
    get_user_project_ids,
    is_platform_core_container,
)
from app.utils.errors import safe_error


# --- List Containers ---

@api_bp.route('/containers', methods=['GET'])
@login_required
def list_containers():
    # K-01: only admin + operators see container listings. Other roles
    # (project_admin, auditor, white_team) have no operational need.
    if not current_user.is_admin and not current_user.is_operator:
        abort(403)
    try:
        show_all = request.args.get('all', 'true').lower() == 'true'
        containers = docker_service.list_containers(all=show_all)

        # Enrich containers with project tag
        container_ids = [c['id'] for c in containers]
        tag_map = build_project_tag_map('container', container_ids)
        for c in containers:
            tag = tag_map.get(c['id'])
            c['project_id'] = tag['project_id'] if tag else None
            c['project_code'] = tag['project_code'] if tag else None
            c['project_resource_id'] = tag['project_resource_id'] if tag else None

        # Non-admins: hide platform-core containers (infrared-web etc.) and
        # any container tagged to a project they're not a member of. Untagged
        # containers are visible — until K-03 (auto-tag at deploy) lands,
        # requiring a tag would hide every operator-deployed container.
        if not current_user.is_admin:
            allowed = get_user_project_ids(current_user)
            containers = [
                c for c in containers
                if not is_platform_core_container(c.get('name'))
                and (c.get('project_id') is None or c.get('project_id') in allowed)
            ]

        return jsonify({'containers': containers})
    except Exception as e:
        return safe_error(e, 400)


# --- Single Container ---

@api_bp.route('/containers/<container_id>', methods=['GET'])
@login_required
def get_container(container_id):
    assert_resource_readable('container', container_id, current_user)
    try:
        container = docker_service.get_container(container_id)
        return jsonify({'container': container})
    except Exception as e:
        return safe_error(e, 400)


# --- Container Actions ---

@api_bp.route('/containers/<container_id>/start', methods=['POST'])
@login_required
def start_container(container_id):
    assert_resource_writable('container', container_id, current_user)
    try:
        result = docker_service.start_container(container_id)
        return jsonify({'result': result})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/containers/<container_id>/stop', methods=['POST'])
@login_required
def stop_container(container_id):
    assert_resource_writable('container', container_id, current_user)
    try:
        result = docker_service.stop_container(container_id)
        return jsonify({'result': result})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/containers/<container_id>/restart', methods=['POST'])
@login_required
def restart_container(container_id):
    assert_resource_writable('container', container_id, current_user)
    try:
        result = docker_service.restart_container(container_id)
        return jsonify({'result': result})
    except Exception as e:
        return safe_error(e, 400)


@api_bp.route('/containers/<container_id>', methods=['DELETE'])
@login_required
def remove_container(container_id):
    assert_resource_writable('container', container_id, current_user)
    force = request.args.get('force', 'false').lower() == 'true'
    try:
        result = docker_service.remove_container(container_id, force=force)
        return jsonify({'result': result})
    except Exception as e:
        return safe_error(e, 400)


# --- Logs ---

@api_bp.route('/containers/<container_id>/logs', methods=['GET'])
@login_required
def get_container_logs(container_id):
    assert_resource_readable('container', container_id, current_user)
    tail = request.args.get('tail', 100, type=int)
    try:
        result = docker_service.get_container_logs(container_id, tail=tail)
        return jsonify(result)
    except Exception as e:
        return safe_error(e, 400)


# --- Stats ---

@api_bp.route('/containers/<container_id>/stats', methods=['GET'])
@login_required
def get_container_stats(container_id):
    assert_resource_readable('container', container_id, current_user)
    try:
        result = docker_service.get_container_stats(container_id)
        return jsonify(result)
    except Exception as e:
        return safe_error(e, 400)
