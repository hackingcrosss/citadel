import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app import db
from app.api import api_bp
from app.models.ia_email_template import (
    IAEmailTemplateBatch, IAEmailTemplate, TEMPLATE_EDITABLE_FIELDS,
    ia_template_target_assignments,
)
from app.models.ia_target import IATarget
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


# ── Data-source summary (pre-generation check) ────────────────────────

@api_bp.route('/ia/email-templates/sources', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_template_data_sources():
    """Return which recon sources have data for the active project."""
    from app.services import discovery_service

    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    data = discovery_service.aggregate_assets(project.id)
    return jsonify({
        'sources': data['sources'],
        'summary': data['summary'],
    })


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

    batch = IAEmailTemplateBatch(
        project_id=project.id,
        status='pending',
        generated_by_id=current_user.id,
    )
    db.session.add(batch)
    db.session.commit()

    audit_service.log('ia.email_generate', 'ia_email_template_batch', batch.id,
                      f'project:{project.code}', {})

    # Dispatch Celery task
    from app.tasks.initial_access_tasks import generate_email_templates_task
    result = generate_email_templates_task.delay(batch.id, project.id)

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

@api_bp.route('/ia/email-templates/<int:template_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_get_template(template_id):
    """Get a single email template."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    tpl = IAEmailTemplate.query.get(template_id)
    if not tpl or tpl.project_id != project.id:
        return jsonify({'error': 'Template not found'}), 404

    return jsonify({'template': tpl.to_dict()})


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
        result = push_template_to_gophish(template_id, user_id=current_user.id)
    except Exception as e:
        _log.exception('Failed to push template %s to GoPhish', template_id)
        return jsonify({'error': str(e)}), 502

    campaign_data = result.get('campaign')
    audit_service.log('ia.email_push_gophish', 'ia_email_template', tpl.id,
                      f'project:{project.code}',
                      {'gophish_template_id': tpl.gophish_template_id,
                       'gophish_group_id': tpl.gophish_group_id,
                       'campaign_id': campaign_data.get('id') if campaign_data else None})

    return jsonify({'template': tpl.to_dict(), 'gophish_result': result})


# ── Target assignments ─────────────────────────────────────────────────

@api_bp.route('/ia/email-templates/<int:template_id>/targets', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_list_template_targets(template_id):
    """List targets assigned to a template."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    tpl = IAEmailTemplate.query.get(template_id)
    if not tpl or tpl.project_id != project.id:
        return jsonify({'error': 'Template not found'}), 404

    targets = tpl.assigned_targets.all()
    return jsonify({'targets': [t.to_dict() for t in targets]})


@api_bp.route('/ia/email-templates/<int:template_id>/targets', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_assign_template_targets(template_id):
    """Assign targets to a template. Body: {target_ids: [int]}"""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    tpl = IAEmailTemplate.query.get(template_id)
    if not tpl or tpl.project_id != project.id:
        return jsonify({'error': 'Template not found'}), 404

    data = request.get_json(silent=True) or {}
    target_ids = data.get('target_ids', [])
    if not target_ids:
        return jsonify({'error': 'No target_ids provided'}), 400

    existing = set(t.id for t in tpl.assigned_targets.all())
    added = 0

    for tid in target_ids:
        if tid in existing:
            continue
        target = IATarget.query.get(tid)
        if not target or target.project_id != project.id:
            continue
        tpl.assigned_targets.append(target)
        existing.add(tid)
        added += 1

    if added:
        db.session.commit()
        audit_service.log('ia.template_assign_targets', 'ia_email_template', tpl.id,
                          f'project:{project.code}', {'added': added})

    return jsonify({'added': added, 'assigned_targets_count': tpl.assigned_targets.count()})


@api_bp.route('/ia/email-templates/<int:template_id>/targets/<int:target_id>', methods=['DELETE'])
@login_required
@feature_required('initial_access')
def ia_unassign_template_target(template_id, target_id):
    """Unassign a target from a template."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    tpl = IAEmailTemplate.query.get(template_id)
    if not tpl or tpl.project_id != project.id:
        return jsonify({'error': 'Template not found'}), 404

    target = IATarget.query.get(target_id)
    if not target or target not in tpl.assigned_targets.all():
        return jsonify({'error': 'Target not assigned'}), 404

    tpl.assigned_targets.remove(target)
    db.session.commit()

    return jsonify({'ok': True, 'assigned_targets_count': tpl.assigned_targets.count()})


def _compute_role_match(target, roles):
    """Score how well a target matches the template's target_roles."""
    score = 0
    reasons = []
    title = (target.job_title or '').lower()
    dept = (target.department or '').lower()

    for role in roles:
        role_lower = role.lower()
        role_words = [w for w in role_lower.split() if len(w) > 2]

        if role_lower == dept:
            score += 3
            reasons.append(f'Department matches "{role}"')
        elif role_lower in dept or dept and dept in role_lower:
            score += 2
            reasons.append(f'Department contains "{role}"')

        if role_lower in title:
            score += 2
            reasons.append(f'Title contains "{role}"')
        else:
            for word in role_words:
                if word in title:
                    score += 1
                    reasons.append(f'Title contains "{word}" from "{role}"')
                    break

    return score, reasons


@api_bp.route('/ia/email-templates/<int:template_id>/suggest-targets', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_suggest_template_targets(template_id):
    """Auto-suggest target assignments based on target_roles matching."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    tpl = IAEmailTemplate.query.get(template_id)
    if not tpl or tpl.project_id != project.id:
        return jsonify({'error': 'Template not found'}), 404

    roles = tpl.parsed_target_roles
    if not roles:
        return jsonify({'suggestions': [], 'message': 'Template has no target_roles to match against'})

    already_assigned = set(t.id for t in tpl.assigned_targets.all())
    targets = IATarget.query.filter_by(project_id=project.id).all()

    suggestions = []
    for target in targets:
        if target.id in already_assigned:
            continue
        score, reasons = _compute_role_match(target, roles)
        if score > 0:
            suggestions.append({
                'target': target.to_dict(),
                'match_score': score,
                'match_reasons': reasons,
            })

    suggestions.sort(key=lambda s: s['match_score'], reverse=True)
    return jsonify({'suggestions': suggestions})
