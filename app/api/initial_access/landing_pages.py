"""Landing page management API endpoints for Initial Access module."""

import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services import ia_landing_service, audit_service
from app.services.project_service import get_active_project, assert_record_accessible
from app.utils.decorators import feature_required
from app.utils.errors import safe_error

_log = logging.getLogger(__name__)


def _require_active_project():
    project = get_active_project(current_user)
    if not project:
        return None
    return project


def _get_page_or_403(page_id, write=False):
    page = ia_landing_service.get_landing_page(page_id)
    if not page:
        return None, jsonify({'error': 'Landing page not found'}), 404
    # C-04: authorise via membership, not session active-project
    assert_record_accessible(page, current_user, write=write)
    return page, None, None


@api_bp.route('/ia/landing-pages', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_list_landing_pages():
    project = _require_active_project()
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    status = request.args.get('status')
    pages = ia_landing_service.list_landing_pages(project.id, status=status)
    return jsonify({'landing_pages': [p.to_dict() for p in pages]})


@api_bp.route('/ia/landing-pages', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_create_landing_page():
    project = _require_active_project()
    if not project:
        return jsonify({'error': 'No active project selected'}), 400
    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    data = request.get_json(silent=True) or {}
    if not data.get('name'):
        return jsonify({'error': 'Name is required'}), 400

    try:
        page = ia_landing_service.create_landing_page(project.id, data, current_user.id)
    except ValueError as e:
        return safe_error(e, 400)

    audit_service.log('ia.landing_create', 'ia_landing_page', page.id,
                      f'project:{project.code}', {'name': page.name, 'type': page.page_type})
    return jsonify(page.to_dict()), 201


@api_bp.route('/ia/landing-pages/<int:page_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_get_landing_page(page_id):
    page, err, code = _get_page_or_403(page_id)
    if err:
        return err, code
    return jsonify(page.to_dict())


@api_bp.route('/ia/landing-pages/<int:page_id>', methods=['PATCH'])
@login_required
@feature_required('initial_access')
def ia_update_landing_page(page_id):
    page, err, code = _get_page_or_403(page_id, write=True)
    if err:
        return err, code
    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    data = request.get_json(silent=True) or {}
    try:
        updated = ia_landing_service.update_landing_page(page, data)
    except ValueError as e:
        return safe_error(e, 400)

    return jsonify(updated.to_dict())


@api_bp.route('/ia/landing-pages/<int:page_id>/deploy', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_deploy_landing_page(page_id):
    page, err, code = _get_page_or_403(page_id, write=True)
    if err:
        return err, code
    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    try:
        steps = ia_landing_service.deploy_landing_page(page)
    except ValueError as e:
        return safe_error(e, 400)
    except Exception as e:
        _log.exception('Failed to deploy landing page %s', page_id)
        return jsonify({'error': f'Deploy error: {e}'}), 502

    project = _require_active_project()
    audit_service.log('ia.landing_deploy', 'ia_landing_page', page.id,
                      f'project:{project.code}',
                      {'fqdn': page.fqdn, 'status': page.status})
    return jsonify({'steps': steps, 'landing_page': page.to_dict()})


@api_bp.route('/ia/landing-pages/<int:page_id>', methods=['DELETE'])
@login_required
@feature_required('initial_access')
def ia_teardown_landing_page(page_id):
    page, err, code = _get_page_or_403(page_id, write=True)
    if err:
        return err, code
    if not current_user.can_write_infra:
        return jsonify({'error': 'Write access required'}), 403

    try:
        steps = ia_landing_service.teardown_landing_page(page)
    except Exception as e:
        _log.exception('Failed to teardown landing page %s', page_id)
        return jsonify({'error': f'Teardown error: {e}'}), 502

    project = _require_active_project()
    audit_service.log('ia.landing_teardown', 'ia_landing_page', page.id,
                      f'project:{project.code}', {'fqdn': page.fqdn})
    return jsonify({'steps': steps, 'landing_page': page.to_dict()})
