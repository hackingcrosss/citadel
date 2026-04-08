import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app import db
from app.api import api_bp
from app.models.ia_email_template import (
    IAEmailTemplateBatch, IAEmailTemplate, TEMPLATE_EDITABLE_FIELDS,
)
from app.services import audit_service
from app.services.project_service import get_active_project
from app.utils.decorators import feature_required

_log = logging.getLogger(__name__)


# ── Batches ─────────────────────────────────────────────────────────────

@api_bp.route('/ia/email-templates/batches', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_list_template_batches():
    """List email template batches for the active project."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    batches = (
        IAEmailTemplateBatch.query
        .filter_by(project_id=project.id)
        .order_by(IAEmailTemplateBatch.generated_at.desc())
        .all()
    )
    return jsonify({'batches': [b.to_dict() for b in batches]})


@api_bp.route('/ia/email-templates/batches/<int:batch_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_get_template_batch(batch_id):
    """Get a batch with its templates."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    batch = IAEmailTemplateBatch.query.get(batch_id)
    if not batch or batch.project_id != project.id:
        return jsonify({'error': 'Batch not found'}), 404

    return jsonify({'batch': batch.to_dict(include_templates=True)})


@api_bp.route('/ia/email-templates/batches/<int:batch_id>', methods=['DELETE'])
@login_required
@feature_required('initial_access')
def ia_delete_template_batch(batch_id):
    """Delete a batch and its templates (cascade)."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    batch = IAEmailTemplateBatch.query.get(batch_id)
    if not batch or batch.project_id != project.id:
        return jsonify({'error': 'Batch not found'}), 404

    audit_service.log('ia.email_batch_delete', 'ia_email_template_batch', batch.id,
                      f'project:{project.code}', {'template_count': len(batch.templates)})

    db.session.delete(batch)
    db.session.commit()
    return jsonify({'ok': True})


# ── Generation ──────────────────────────────────────────────────────────

@api_bp.route('/ia/email-templates/generate', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_generate_templates():
    """Create a batch and dispatch the Celery generation task."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    data = request.get_json(silent=True) or {}
    scan_job_id = data.get('scan_job_id')

    batch = IAEmailTemplateBatch(
        project_id=project.id,
        scan_job_id=scan_job_id,
        status='pending',
        generated_by_id=current_user.id,
    )
    db.session.add(batch)
    db.session.commit()

    audit_service.log('ia.email_generate', 'ia_email_template_batch', batch.id,
                      f'project:{project.code}', {'scan_job_id': scan_job_id})

    # Dispatch Celery task
    from app.tasks.initial_access_tasks import generate_email_templates_task
    result = generate_email_templates_task.delay(batch.id, project.id, scan_job_id)

    return jsonify({
        'batch_id': batch.id,
        'task_id': result.id,
    }), 202


@api_bp.route('/ia/email-templates/status/<task_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_template_generation_status(task_id):
    """Poll Celery task status."""
    from app.tasks.celery_app import celery

    result = celery.AsyncResult(task_id)
    response = {'task_id': task_id, 'state': result.state}

    if result.state == 'SUCCESS':
        response['result'] = result.result
    elif result.state == 'FAILURE':
        response['error'] = str(result.result)

    return jsonify(response)


# ── Individual templates ────────────────────────────────────────────────

@api_bp.route('/ia/email-templates/<int:template_id>', methods=['PATCH'])
@login_required
@feature_required('initial_access')
def ia_update_template(template_id):
    """Edit whitelisted fields on a template."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    tpl = IAEmailTemplate.query.get(template_id)
    if not tpl or tpl.project_id != project.id:
        return jsonify({'error': 'Template not found'}), 404

    data = request.get_json(silent=True) or {}
    updated = []
    for key, value in data.items():
        if key in TEMPLATE_EDITABLE_FIELDS:
            setattr(tpl, key, value)
            updated.append(key)

    if not updated:
        return jsonify({'error': 'No valid fields to update'}), 400

    db.session.commit()
    return jsonify({'template': tpl.to_dict()})


@api_bp.route('/ia/email-templates/<int:template_id>/push', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_push_template_to_gophish(template_id):
    """Push a template to GoPhish."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    tpl = IAEmailTemplate.query.get(template_id)
    if not tpl or tpl.project_id != project.id:
        return jsonify({'error': 'Template not found'}), 404

    try:
        from app.services.email_template_service import push_template_to_gophish
        result = push_template_to_gophish(template_id)
    except Exception as e:
        _log.exception('Failed to push template %s to GoPhish', template_id)
        return jsonify({'error': str(e)}), 502

    audit_service.log('ia.email_push_gophish', 'ia_email_template', tpl.id,
                      f'project:{project.code}',
                      {'gophish_template_id': tpl.gophish_template_id})

    return jsonify({'template': tpl.to_dict(), 'gophish_result': result})
