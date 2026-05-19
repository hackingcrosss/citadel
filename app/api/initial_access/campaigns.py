"""Campaign management API endpoints for Initial Access module."""

import logging
from flask import abort, request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import ia_campaign_service, audit_service
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


def _get_campaign_or_404(campaign_id, write=False):
    campaign = ia_campaign_service.get_campaign(campaign_id)
    if not campaign:
        return None, jsonify({'error': 'Campaign not found'}), 404
    # C-04: authorise via membership, not session active-project
    assert_record_accessible(campaign, current_user, write=write)
    return campaign, None, None


# ── Campaign CRUD ───────────────────────────────────────────────────────

@api_bp.route('/ia/campaigns', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_list_campaigns():
    project = _require_active_project()
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    status = request.args.get('status')
    campaigns = ia_campaign_service.list_campaigns(project.id, status=status)
    return jsonify({'campaigns': [c.to_dict() for c in campaigns]})


@api_bp.route('/ia/campaigns', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_create_campaign():
    project = _require_active_project(write=True)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'error': 'Campaign name is required'}), 400

    try:
        campaign = ia_campaign_service.create_campaign(project.id, data, current_user.id)
    except ValueError as e:
        return safe_error(e, 400)

    audit_service.log('ia.campaign_create', 'ia_campaign', campaign.id,
                      f'project:{project.code}', {'name': campaign.name, 'vector': campaign.vector})
    return jsonify(campaign.to_dict()), 201


@api_bp.route('/ia/campaigns/<int:campaign_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_get_campaign(campaign_id):
    campaign, err, code = _get_campaign_or_404(campaign_id)
    if err:
        return err, code

    include_targets = request.args.get('include_targets', 'false').lower() == 'true'
    return jsonify(campaign.to_dict(include_targets=include_targets))


@api_bp.route('/ia/campaigns/<int:campaign_id>', methods=['PATCH'])
@login_required
@feature_required('initial_access')
def ia_update_campaign(campaign_id):
    campaign, err, code = _get_campaign_or_404(campaign_id, write=True)
    if err:
        return err, code
    data = request.get_json(silent=True) or {}
    try:
        updated = ia_campaign_service.update_campaign(campaign, data)
    except ValueError as e:
        return safe_error(e, 400)

    return jsonify(updated.to_dict())


@api_bp.route('/ia/campaigns/<int:campaign_id>', methods=['DELETE'])
@login_required
@feature_required('initial_access')
def ia_archive_campaign(campaign_id):
    campaign, err, code = _get_campaign_or_404(campaign_id, write=True)
    if err:
        return err, code
    audit_service.log('ia.campaign_archive', 'ia_campaign', campaign.id,
                      f'project:{campaign.project.code if campaign.project else "?"}', {'name': campaign.name})
    ia_campaign_service.archive_campaign(campaign)
    return jsonify({'ok': True})


# ── Launch + Sync ───────────────────────────────────────────────────────

@api_bp.route('/ia/campaigns/<int:campaign_id>/launch', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_launch_campaign(campaign_id):
    campaign, err, code = _get_campaign_or_404(campaign_id, write=True)
    if err:
        return err, code
    try:
        launched = ia_campaign_service.launch_campaign(campaign)
    except ValueError as e:
        return safe_error(e, 400)
    except Exception as e:
        _log.exception('Failed to launch campaign %s', campaign_id)
        return jsonify({'error': f'GoPhish error: {e}'}), 502

    audit_service.log('ia.campaign_launch', 'ia_campaign', campaign.id,
                      f'project:{campaign.project.code if campaign.project else "?"}',
                      {'gophish_id': launched.gophish_campaign_id})
    return jsonify(launched.to_dict())


@api_bp.route('/ia/campaigns/<int:campaign_id>/reschedule', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_reschedule_campaign(campaign_id):
    campaign, err, code = _get_campaign_or_404(campaign_id, write=True)
    if err:
        return err, code
    data = request.get_json(silent=True) or {}
    scheduled_start = data.get('scheduled_start')
    if not scheduled_start:
        return jsonify({'error': 'scheduled_start is required'}), 400

    try:
        updated = ia_campaign_service.reschedule_campaign(
            campaign, scheduled_start,
            scheduled_end=data.get('scheduled_end'),
        )
    except ValueError as e:
        return safe_error(e, 400)
    except Exception as e:
        _log.exception('Failed to reschedule campaign %s', campaign_id)
        return jsonify({'error': f'GoPhish error: {e}'}), 502

    audit_service.log('ia.campaign_reschedule', 'ia_campaign', campaign.id,
                      f'project:{campaign.project.code if campaign.project else "?"}',
                      {'scheduled_start': scheduled_start, 'gophish_id': updated.gophish_campaign_id})
    return jsonify(updated.to_dict())


@api_bp.route('/ia/campaigns/<int:campaign_id>/sync', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_sync_campaign(campaign_id):
    campaign, err, code = _get_campaign_or_404(campaign_id)
    if err:
        return err, code

    new_events = ia_campaign_service.sync_campaign_events(campaign)
    return jsonify({'new_events': new_events, 'campaign': campaign.to_dict()})


# ── Events ──────────────────────────────────────────────────────────────

@api_bp.route('/ia/campaigns/<int:campaign_id>/events', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_campaign_events(campaign_id):
    campaign, err, code = _get_campaign_or_404(campaign_id)
    if err:
        return err, code

    events = campaign.events  # already ordered desc by occurred_at
    return jsonify({'events': [e.to_dict() for e in events]})


@api_bp.route('/ia/campaigns/<int:campaign_id>/events', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_log_event(campaign_id):
    """Manually log a vishing/smishing/other event."""
    campaign, err, code = _get_campaign_or_404(campaign_id, write=True)
    if err:
        return err, code
    data = request.get_json(silent=True) or {}
    if not data.get('event_type'):
        return jsonify({'error': 'event_type is required'}), 400

    try:
        event = ia_campaign_service.log_manual_event(campaign, data)
    except ValueError as e:
        return safe_error(e, 400)

    return jsonify(event.to_dict()), 201


# ── Campaign targets ────────────────────────────────────────────────────

@api_bp.route('/ia/campaigns/<int:campaign_id>/targets', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_add_campaign_targets(campaign_id):
    campaign, err, code = _get_campaign_or_404(campaign_id, write=True)
    if err:
        return err, code
    data = request.get_json(silent=True) or {}
    target_ids = data.get('target_ids', [])
    if not target_ids:
        return jsonify({'error': 'target_ids list required'}), 400

    added = ia_campaign_service.add_targets(campaign, target_ids)
    return jsonify({'added': added, 'targets_count': campaign.targets_count})


@api_bp.route('/ia/campaigns/<int:campaign_id>/targets/<int:target_id>', methods=['DELETE'])
@login_required
@feature_required('initial_access')
def ia_remove_campaign_target(campaign_id, target_id):
    campaign, err, code = _get_campaign_or_404(campaign_id, write=True)
    if err:
        return err, code
    removed = ia_campaign_service.remove_target(campaign, target_id)
    if not removed:
        return jsonify({'error': 'Target not in campaign'}), 404
    return jsonify({'ok': True, 'targets_count': campaign.targets_count})


# ── Sender domains ─────────────────────────────────────────────────────

@api_bp.route('/ia/sender-domains', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_sender_domains():
    project = _require_active_project()
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    try:
        domains = ia_campaign_service.get_eligible_domains(project.id)
    except Exception as e:
        _log.warning('Failed to fetch sender domains: %s', e)
        domains = []

    return jsonify({'domains': domains})
