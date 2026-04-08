import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import ia_business_intel_service, audit_service
from app.services.project_service import get_active_project
from app.utils.decorators import feature_required

_log = logging.getLogger(__name__)


@api_bp.route('/ia/intel', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_get_intel():
    """Get business intelligence for the active project."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    intel = ia_business_intel_service.get_or_create_intel(project.id)
    return jsonify({'intel': intel.to_dict()})


@api_bp.route('/ia/intel', methods=['PUT'])
@login_required
@feature_required('initial_access')
def ia_update_intel():
    """Upsert business intelligence fields for the active project."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    intel = ia_business_intel_service.update_intel(project.id, data, current_user.id)

    audit_service.log('ia.intel_update', 'ia_business_intel', intel.id,
                      f'project:{project.code}', {'fields': list(data.keys())})

    return jsonify({'intel': intel.to_dict()})


@api_bp.route('/ia/intel/extract', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_extract_intel():
    """Dispatch a Celery task to extract structured fields from pasted threat intel."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    data = request.get_json(silent=True) or {}
    raw_text = (data.get('raw_text') or '').strip()
    if not raw_text:
        return jsonify({'error': 'raw_text is required'}), 400

    # Save raw input immediately
    ia_business_intel_service.update_intel(project.id, {'raw_input': raw_text}, current_user.id)

    from app.tasks.initial_access_tasks import extract_intel_task
    result = extract_intel_task.delay(project.id, raw_text, current_user.id)

    audit_service.log('ia.intel_extract', 'ia_business_intel', project.id,
                      f'project:{project.code}', {'text_length': len(raw_text)})

    return jsonify({'task_id': result.id}), 202


@api_bp.route('/ia/intel/extract/status/<task_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_extract_intel_status(task_id):
    """Poll Celery task status for intel extraction."""
    from app.tasks.celery_app import celery

    result = celery.AsyncResult(task_id)
    response = {'task_id': task_id, 'state': result.state}

    if result.state == 'SUCCESS':
        response['result'] = result.result
    elif result.state == 'FAILURE':
        response['error'] = str(result.result)

    return jsonify(response)
