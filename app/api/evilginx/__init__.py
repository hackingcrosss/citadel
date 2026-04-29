"""Evilginx phishlet management API endpoints."""

import logging
import re

from flask import jsonify, request
from flask_login import current_user, login_required

from app.api import api_bp
from app.models.domain import Domain
from app.services import audit_service, evilginx_service
from app.services.project_service import get_active_project
from app.utils.decorators import feature_required

_log = logging.getLogger(__name__)

_IPV4_RE = re.compile(
    r'^(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}'
    r'(?:25[0-5]|2[0-4]\d|[01]?\d?\d)$'
)


def _require_active_project():
    project = get_active_project(current_user)
    return project


def _get_phishlet_or_403(phishlet_id):
    p = evilginx_service.get_phishlet(phishlet_id)
    if not p:
        return None, jsonify({'error': 'Phishlet not found'}), 404
    project = _require_active_project()
    if not current_user.is_admin and (not project or p.project_id != project.id):
        return None, jsonify({'error': 'Access denied'}), 403
    return p, None, None


def _can_write():
    return current_user.is_admin or getattr(current_user, 'can_write_infra', False)


# ── Parse / preview ─────────────────────────────────────────────────────

@api_bp.route('/evilginx/parse', methods=['POST'])
@login_required
@feature_required('evilginx')
def evilginx_parse():
    """Parse a phishlet YAML and return a preview (no persistence, no CF calls)."""
    data = request.get_json(silent=True) or {}
    raw = data.get('yaml')
    if not isinstance(raw, str) or not raw.strip():
        return jsonify({'error': 'yaml field is required'}), 400
    try:
        parsed = evilginx_service.parse_phishlet_yaml(raw)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'phishlet': parsed})


# ── List / read ─────────────────────────────────────────────────────────

@api_bp.route('/evilginx/phishlets', methods=['GET'])
@login_required
@feature_required('evilginx')
def evilginx_list():
    project = _require_active_project()
    if not project:
        return jsonify({'error': 'No active project selected'}), 400
    phishlets = evilginx_service.list_phishlets(project.id)
    return jsonify({'phishlets': [p.to_dict() for p in phishlets]})


@api_bp.route('/evilginx/phishlets/<int:phishlet_id>', methods=['GET'])
@login_required
@feature_required('evilginx')
def evilginx_get(phishlet_id):
    p, err, code = _get_phishlet_or_403(phishlet_id)
    if err:
        return err, code
    include_yaml = request.args.get('include_yaml', 'false').lower() == 'true'
    return jsonify({'phishlet': p.to_dict(include_yaml=include_yaml)})


# ── Create ──────────────────────────────────────────────────────────────

@api_bp.route('/evilginx/phishlets', methods=['POST'])
@login_required
@feature_required('evilginx')
def evilginx_create():
    project = _require_active_project()
    if not project:
        return jsonify({'error': 'No active project selected'}), 400
    if not _can_write():
        return jsonify({'error': 'Write access required'}), 403

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    yaml_content = data.get('yaml')
    domain_id = data.get('domain_id')
    target_ip = (data.get('target_ip') or '').strip()
    bot_protection = bool(data.get('bot_protection', True))

    if not name:
        return jsonify({'error': 'name is required'}), 400
    if not isinstance(yaml_content, str) or not yaml_content.strip():
        return jsonify({'error': 'yaml is required'}), 400
    if not isinstance(domain_id, int):
        return jsonify({'error': 'domain_id is required'}), 400
    if not target_ip:
        return jsonify({'error': 'target_ip is required'}), 400
    if not _IPV4_RE.match(target_ip):
        return jsonify({'error': 'target_ip must be a valid IPv4 address'}), 400

    domain = Domain.query.get(domain_id)
    if not domain:
        return jsonify({'error': 'Domain not found'}), 404
    if not domain.cloudflare_zone_id:
        return jsonify({'error': 'Domain is not bound to a Cloudflare zone'}), 400

    # Domain access: admins bypass; everyone else must have it checked out to the active project.
    if not current_user.is_admin and domain.checkout_project_id != project.id:
        return jsonify({'error': 'Domain is not checked out to the active project'}), 403

    try:
        phishlet, parsed = evilginx_service.create_phishlet(
            project_id=project.id,
            name=name,
            yaml_content=yaml_content,
            domain=domain,
            target_ip=target_ip,
            bot_protection=bot_protection,
            user_id=current_user.id,
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    audit_service.log(
        'evilginx.create', 'phishlet', phishlet.id, f'project:{project.code}',
        {
            'name': phishlet.name,
            'phishlet_name': phishlet.phishlet_name,
            'domain': domain.name,
            'subs': len(parsed['phish_subs']),
            'bot_protection': phishlet.bot_protection_enabled,
        },
    )
    return jsonify({'phishlet': phishlet.to_dict(), 'parsed': parsed}), 201


# ── Deploy ──────────────────────────────────────────────────────────────

@api_bp.route('/evilginx/phishlets/<int:phishlet_id>/deploy', methods=['POST'])
@login_required
@feature_required('evilginx')
def evilginx_deploy(phishlet_id):
    p, err, code = _get_phishlet_or_403(phishlet_id)
    if err:
        return err, code
    if not _can_write():
        return jsonify({'error': 'Write access required'}), 403

    try:
        steps = evilginx_service.deploy_phishlet(p)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        _log.exception('Phishlet deploy failed (id=%s)', phishlet_id)
        return jsonify({'error': f'Deploy failed: {e}'}), 500

    audit_service.log(
        'evilginx.deploy', 'phishlet', p.id,
        f'project:{p.project.code}' if p.project else '',
        {'status': p.status, 'steps': steps},
    )
    return jsonify({'phishlet': p.to_dict(), 'steps': steps})


# ── Teardown ────────────────────────────────────────────────────────────

@api_bp.route('/evilginx/phishlets/<int:phishlet_id>/teardown', methods=['POST'])
@login_required
@feature_required('evilginx')
def evilginx_teardown(phishlet_id):
    p, err, code = _get_phishlet_or_403(phishlet_id)
    if err:
        return err, code
    if not _can_write():
        return jsonify({'error': 'Write access required'}), 403

    try:
        steps = evilginx_service.teardown_phishlet(p)
    except Exception as e:
        _log.exception('Phishlet teardown failed (id=%s)', phishlet_id)
        return jsonify({'error': f'Teardown failed: {e}'}), 500

    audit_service.log(
        'evilginx.teardown', 'phishlet', p.id,
        f'project:{p.project.code}' if p.project else '',
        {'steps': steps},
    )
    return jsonify({'phishlet': p.to_dict(), 'steps': steps})


# ── Delete ──────────────────────────────────────────────────────────────

@api_bp.route('/evilginx/phishlets/<int:phishlet_id>', methods=['DELETE'])
@login_required
@feature_required('evilginx')
def evilginx_delete(phishlet_id):
    p, err, code = _get_phishlet_or_403(phishlet_id)
    if err:
        return err, code
    if not _can_write():
        return jsonify({'error': 'Write access required'}), 403

    force = request.args.get('force', 'false').lower() == 'true'
    project_code = p.project.code if p.project else ''
    name = p.name

    try:
        evilginx_service.delete_phishlet(p, force=force)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    audit_service.log(
        'evilginx.delete', 'phishlet', phishlet_id,
        f'project:{project_code}',
        {'name': name, 'force': force},
    )
    return jsonify({'deleted': True})
