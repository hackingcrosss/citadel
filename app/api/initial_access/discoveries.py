"""Discoveries API — unified view of assets found by all recon sources."""

import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.services.project_service import get_active_project
from app.utils.decorators import feature_required

_log = logging.getLogger(__name__)


@api_bp.route('/ia/discoveries', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_discoveries():
    """Return a unified, deduplicated asset list from all recon sources.

    Query params:
        source  - filter: 'scanner', 'fofa', or omit for all
    """
    from app.services import discovery_service

    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    source_filter = request.args.get('source', '').lower()

    data = discovery_service.aggregate_assets(project.id, source_filter)

    return jsonify({
        'assets': data['assets'],
        'sources': data['sources'],
        'summary': data['summary'],
    })
