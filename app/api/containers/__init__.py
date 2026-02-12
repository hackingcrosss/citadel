from flask import request, jsonify
from flask_login import login_required
from app.api import api_bp
from app.services import docker_service


# --- List Containers ---

@api_bp.route('/containers', methods=['GET'])
@login_required
def list_containers():
    try:
        show_all = request.args.get('all', 'true').lower() == 'true'
        containers = docker_service.list_containers(all=show_all)
        return jsonify({'containers': containers})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Single Container ---

@api_bp.route('/containers/<container_id>', methods=['GET'])
@login_required
def get_container(container_id):
    try:
        container = docker_service.get_container(container_id)
        return jsonify({'container': container})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Container Actions ---

@api_bp.route('/containers/<container_id>/start', methods=['POST'])
@login_required
def start_container(container_id):
    try:
        result = docker_service.start_container(container_id)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/containers/<container_id>/stop', methods=['POST'])
@login_required
def stop_container(container_id):
    try:
        result = docker_service.stop_container(container_id)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@api_bp.route('/containers/<container_id>/restart', methods=['POST'])
@login_required
def restart_container(container_id):
    try:
        result = docker_service.restart_container(container_id)
        return jsonify({'result': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Logs ---

@api_bp.route('/containers/<container_id>/logs', methods=['GET'])
@login_required
def get_container_logs(container_id):
    tail = request.args.get('tail', 100, type=int)
    try:
        result = docker_service.get_container_logs(container_id, tail=tail)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# --- Stats ---

@api_bp.route('/containers/<container_id>/stats', methods=['GET'])
@login_required
def get_container_stats(container_id):
    try:
        result = docker_service.get_container_stats(container_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 400
