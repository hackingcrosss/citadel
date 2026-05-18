from flask import jsonify, abort
from flask_login import login_required, current_user
from app.api import api_bp
from app.utils.errors import safe_error


@api_bp.route('/task-log', methods=['GET'])
@login_required
def get_task_log():
    from app.services import task_log_service
    try:
        tasks = task_log_service.get_tasks(user=current_user)
        return jsonify({'tasks': tasks})
    except Exception as e:
        return safe_error(e, 500, tasks=[])


@api_bp.route('/task-log/completed', methods=['DELETE'])
@login_required
def clear_completed_tasks():
    from app.services import task_log_service
    try:
        task_log_service.clear_completed(user=current_user)
        return jsonify({'ok': True})
    except Exception as e:
        return safe_error(e, 500)


@api_bp.route('/task-log/<task_id>/revoke', methods=['POST'])
@login_required
def revoke_task(task_id):
    from app.services import task_log_service
    # API-IDOR-01: only the task owner or admin can revoke
    owner_id = task_log_service.get_task_owner(task_id)
    if owner_id is not None and owner_id != current_user.id \
            and not current_user.is_admin:
        abort(403)

    from app.tasks.celery_app import celery
    try:
        celery.control.revoke(task_id, terminate=True)
        # For PENDING tasks, control.revoke() never writes to the result backend,
        # so AsyncResult.status stays PENDING forever. Force it to REVOKED now.
        celery.backend.store_result(task_id, None, 'REVOKED')
        return jsonify({'ok': True})
    except Exception as e:
        return safe_error(e, 500)
