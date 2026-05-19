"""Target management API endpoints for Initial Access module."""

import logging
from flask import abort, request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import ia_target_service, ia_scan_service, audit_service
from app.services.project_service import can_write, get_active_project, assert_record_accessible
from app.utils.decorators import feature_required
from app.utils.errors import safe_error

_log = logging.getLogger(__name__)


def _require_active_project(write=False):
    project = get_active_project(current_user)
    if not project:
        return None
    if write and not can_write(current_user, project.id):
        abort(403)
    return project


@api_bp.route('/ia/targets', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_list_targets():
    """List targets for the active project, with optional search."""
    project = _require_active_project()
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    search = request.args.get('search', '').strip() or None
    targets = ia_target_service.list_targets(project.id, search=search)
    return jsonify({'targets': [t.to_dict() for t in targets]})


@api_bp.route('/ia/targets', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_create_target():
    """Create a single target."""
    project = _require_active_project(write=True)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    data = request.get_json(silent=True) or {}
    if not data.get('email'):
        return jsonify({'error': 'Email is required'}), 400

    try:
        target = ia_target_service.create_target(project.id, data, current_user.id)
    except Exception as e:
        if 'uq_ia_target_project_email' in str(e):
            return jsonify({'error': 'A target with this email already exists in the project'}), 409
        _log.exception('Failed to create target')
        return safe_error(e, 500)

    audit_service.log('ia.target_create', 'ia_target', target.id,
                      f'project:{project.code}', {'email': target.email})
    return jsonify(target.to_dict()), 201


@api_bp.route('/ia/targets/import', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_import_targets():
    """Import targets from CSV text."""
    project = _require_active_project(write=True)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    payload = request.get_json(silent=True) or {}
    csv_text = payload.get('csv_text', '')
    if not csv_text.strip():
        return jsonify({'error': 'No CSV data provided'}), 400

    result = ia_target_service.import_csv(project.id, csv_text, current_user.id)

    audit_service.log('ia.targets_import', 'ia_target', None,
                      f'project:{project.code}',
                      {'created': result['created'], 'skipped': result['skipped'],
                       'errors': result['errors']})
    return jsonify(result)


@api_bp.route('/ia/targets/<int:target_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_get_target(target_id):
    """Get a single target."""
    target = ia_target_service.get_target(target_id)
    if not target:
        return jsonify({'error': 'Target not found'}), 404

    # C-04: authorise via membership, not session active-project
    assert_record_accessible(target, current_user)
    return jsonify(target.to_dict())


@api_bp.route('/ia/targets/<int:target_id>/campaigns', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_target_campaigns(target_id):
    """List campaigns that include this target."""
    target = ia_target_service.get_target(target_id)
    if not target:
        return jsonify({'error': 'Target not found'}), 404

    # C-04: authorise via membership, not session active-project
    assert_record_accessible(target, current_user)

    campaigns = [
        {'id': c.id, 'name': c.name, 'vector': c.vector, 'status': c.status,
         'emails_sent': c.emails_sent, 'opens_count': c.opens_count,
         'clicks_count': c.clicks_count, 'creds_captured': c.creds_captured}
        for c in target.campaigns.all()
    ]
    return jsonify({'campaigns': campaigns})


@api_bp.route('/ia/targets/<int:target_id>', methods=['PATCH'])
@login_required
@feature_required('initial_access')
def ia_update_target(target_id):
    """Update a target's fields."""
    target = ia_target_service.get_target(target_id)
    if not target:
        return jsonify({'error': 'Target not found'}), 404

    # C-04: authorise via membership, not session active-project
    assert_record_accessible(target, current_user, write=True)

    data = request.get_json(silent=True) or {}
    try:
        updated = ia_target_service.update_target(target, data)
    except Exception as e:
        if 'uq_ia_target_project_email' in str(e):
            return jsonify({'error': 'A target with this email already exists in the project'}), 409
        _log.exception('Failed to update target')
        return safe_error(e, 500)

    return jsonify(updated.to_dict())


@api_bp.route('/ia/targets/<int:target_id>', methods=['DELETE'])
@login_required
@feature_required('initial_access')
def ia_delete_target(target_id):
    """Delete a target."""
    target = ia_target_service.get_target(target_id)
    if not target:
        return jsonify({'error': 'Target not found'}), 404

    # C-04: authorise via membership, not session active-project
    assert_record_accessible(target, current_user, write=True)

    project = target.project
    audit_service.log('ia.target_delete', 'ia_target', target.id,
                      f'project:{project.code}', {'email': target.email})
    ia_target_service.delete_target(target)
    return jsonify({'ok': True})


@api_bp.route('/ia/targets/<int:target_id>/enrich', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_enrich_target(target_id):
    """Enrich a target from the latest completed scan results."""
    from app.models.ia_scan_job import IAScanJob

    target = ia_target_service.get_target(target_id)
    if not target:
        return jsonify({'error': 'Target not found'}), 404

    # C-04: authorise via membership, not session active-project
    assert_record_accessible(target, current_user, write=True)

    # Find latest completed scan for the target's project
    latest_scan = (
        IAScanJob.query
        .filter_by(project_id=target.project_id, status='completed')
        .order_by(IAScanJob.completed_at.desc())
        .first()
    )
    if not latest_scan:
        return jsonify({'error': 'No completed scans available for enrichment'}), 404

    scan_results = ia_scan_service.get_scan_results(latest_scan.id)
    if not scan_results:
        return jsonify({'error': 'Scan has no results'}), 404

    enriched = ia_target_service.enrich_from_scan(target, scan_results)
    return jsonify({'enriched': enriched, 'target': target.to_dict()})
