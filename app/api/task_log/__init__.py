from flask import jsonify
from flask_login import login_required
from app.api import api_bp


@api_bp.route('/task-log', methods=['GET'])
@login_required
def get_task_log():
    from app.services import task_log_service
    try:
        tasks = task_log_service.get_tasks()
        return jsonify({'tasks': tasks})
    except Exception as e:
        return jsonify({'error': str(e), 'tasks': []}), 500


@api_bp.route('/task-log/completed', methods=['DELETE'])
@login_required
def clear_completed_tasks():
    from app.services import task_log_service
    try:
        task_log_service.clear_completed()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
