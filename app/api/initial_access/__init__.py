import json
import logging
from flask import abort, request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import ia_scan_service, audit_service
from app.services.project_service import can_write, get_active_project, assert_record_accessible
from app.utils.decorators import feature_required
from app.utils.errors import safe_error

_log = logging.getLogger(__name__)


def _require_active_project(write=False):
    """Return the active project and enforce membership/project write access."""
    project = get_active_project(current_user)
    if not project:
        return None
    if write and not can_write(current_user, project.id):
        abort(403)
    return project


# ── Scan Jobs ────────────────────────────────────────────────────────────

@api_bp.route('/ia/scans', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_list_scans():
    """List scan jobs for the active project."""
    from app.models.ia_scan_job import IAScanJob

    project = _require_active_project()
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    jobs = (
        IAScanJob.query
        .filter_by(project_id=project.id)
        .order_by(IAScanJob.triggered_at.desc())
        .all()
    )
    return jsonify({'scans': [j.to_dict() for j in jobs]})


@api_bp.route('/ia/scans', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_trigger_scan():
    """Trigger a new scan on the external scanner."""
    project = _require_active_project(write=True)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    payload = request.get_json(silent=True) or {}
    scope = payload.get('scope', {})

    domains = scope.get('domains', [])
    ip_ranges = scope.get('ip_ranges', [])
    if not domains and not ip_ranges:
        return jsonify({'error': 'Scope must include at least one domain or IP range'}), 400

    scope_config = {'domains': domains, 'ip_ranges': ip_ranges}

    try:
        job = ia_scan_service.trigger_scan(project.id, scope_config, current_user.id)
    except ValueError as e:
        return safe_error(e, 400)
    except Exception as e:
        _log.exception('Failed to trigger scan')
        return jsonify({'error': f'Scanner API error: {e}'}), 502

    audit_service.log('ia.scan_trigger', 'ia_scan_job', job.id, f'project:{project.code}',
                      {'scope': scope_config})

    # Enqueue background poll task
    try:
        from app.tasks.initial_access_tasks import scan_poll_job
        scan_poll_job.delay(job.id)
    except Exception:
        _log.warning('Failed to enqueue scan poll task for job %s', job.id)

    return jsonify(job.to_dict()), 201


@api_bp.route('/ia/scans/<int:job_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_get_scan(job_id):
    """Get a scan job with its results."""
    from app.models.ia_scan_job import IAScanJob

    job = IAScanJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Scan job not found'}), 404

    # C-04: authorise via membership, not session active-project
    assert_record_accessible(job, current_user)
    include_raw = request.args.get('include_raw', 'false').lower() == 'true'
    return jsonify(job.to_dict(include_raw=include_raw))


@api_bp.route('/ia/scans/<int:job_id>/poll', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_poll_scan(job_id):
    """Manually poll a scan job for updated status."""
    from app.models.ia_scan_job import IAScanJob

    job = IAScanJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Scan job not found'}), 404

    # C-04: authorise via membership, not session active-project
    assert_record_accessible(job, current_user, write=True)

    try:
        updated = ia_scan_service.poll_scan_job(job_id)
        return jsonify(updated.to_dict())
    except ValueError as e:
        return safe_error(e, 400)
    except Exception as e:
        _log.exception('Failed to poll scan job %s', job_id)
        return jsonify({'error': f'Scanner API error: {e}'}), 502


@api_bp.route('/ia/scans/<int:job_id>/results', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_scan_results(job_id):
    """Get the full raw results for a completed scan."""
    from app.models.ia_scan_job import IAScanJob

    job = IAScanJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Scan job not found'}), 404

    # C-04: authorise via membership, not session active-project
    assert_record_accessible(job, current_user)

    results = ia_scan_service.get_scan_results(job_id)
    if results is None:
        return jsonify({'error': 'No results available'}), 404

    return jsonify({'results': results})


# Register sub-modules
from app.api.initial_access import targets          # noqa: F401, E402
from app.api.initial_access import campaigns        # noqa: F401, E402
from app.api.initial_access import landing_pages    # noqa: F401, E402
from app.api.initial_access import business_intel   # noqa: F401, E402
from app.api.initial_access import email_templates  # noqa: F401, E402
from app.api.initial_access import fofa             # noqa: F401, E402
from app.api.initial_access import discoveries      # noqa: F401, E402
