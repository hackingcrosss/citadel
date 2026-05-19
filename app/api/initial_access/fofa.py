import logging
from flask import abort, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.api import api_bp
from app.models.ia_fofa_search import IAFofaSearch
from app.services import fofa_service, audit_service
from app.services.project_service import can_write, get_active_project, assert_record_accessible
from app.utils.decorators import feature_required

_log = logging.getLogger(__name__)


@api_bp.route('/ia/fofa/searches', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_fofa_list_searches():
    """List FOFA searches for the active project."""
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400

    searches = (
        IAFofaSearch.query
        .filter_by(project_id=project.id)
        .order_by(IAFofaSearch.created_at.desc())
        .all()
    )
    return jsonify({'searches': [s.to_dict() for s in searches]})


@api_bp.route('/ia/fofa/searches/<int:search_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_fofa_get_search(search_id):
    """Get a FOFA search with results."""
    record = IAFofaSearch.query.get(search_id)
    if not record:
        return jsonify({'error': 'Search not found'}), 404
    # C-04: authorise via membership, not session active-project
    assert_record_accessible(record, current_user)
    return jsonify({'search': record.to_dict(include_results=True)})


@api_bp.route('/ia/fofa/searches/<int:search_id>', methods=['DELETE'])
@login_required
@feature_required('initial_access')
def ia_fofa_delete_search(search_id):
    """Delete a FOFA search record."""
    record = IAFofaSearch.query.get(search_id)
    if not record:
        return jsonify({'error': 'Search not found'}), 404
    # C-04: authorise via membership, not session active-project
    assert_record_accessible(record, current_user, write=True)

    db.session.delete(record)
    db.session.commit()
    return jsonify({'ok': True})


@api_bp.route('/ia/fofa/search', methods=['POST'])
@login_required
@feature_required('initial_access')
def ia_fofa_start_search():
    """Create FOFA search records and dispatch Celery task.

    Body: {scope_items?: [{type, value}], custom_query?: str}
    If neither provided, uses all items from project scope.
    """
    project = get_active_project(current_user)
    if not project:
        return jsonify({'error': 'No active project selected'}), 400
    if not can_write(current_user, project.id):
        abort(403)

    data = request.get_json(silent=True) or {}
    scope_items = data.get('scope_items', [])
    custom_query = (data.get('custom_query') or '').strip()

    # Build search items
    items = []
    if custom_query:
        items.append({'type': 'custom', 'value': custom_query, 'query': custom_query})
    elif scope_items:
        for item in scope_items:
            t = item.get('type', '')
            v = item.get('value', '')
            if t and v:
                items.append({'type': t, 'value': v, 'query': fofa_service.build_query(t, v)})
    else:
        # Use full project scope — try project JSON first, then company scope_notes
        scope = project.parsed_scope
        has_scope = any(scope.get(k) for k in ('domains', 'ips', 'cidrs'))

        if has_scope:
            for d in (scope.get('domains') or []):
                items.append({'type': 'domain', 'value': d, 'query': fofa_service.build_query('domain', d)})
            for ip in (scope.get('ips') or []):
                items.append({'type': 'ip', 'value': ip, 'query': fofa_service.build_query('ip', ip)})
            for cidr in (scope.get('cidrs') or []):
                items.append({'type': 'cidr', 'value': cidr, 'query': fofa_service.build_query('cidr', cidr)})
        elif project.company and project.company.scope_notes:
            import re
            for line in project.company.scope_notes.split('\n'):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if re.match(r'/\d{1,2}$', line):
                    items.append({'type': 'cidr', 'value': line, 'query': fofa_service.build_query('cidr', line)})
                elif re.match(r'^\d{1,3}(\.\d{1,3}){3}$', line):
                    items.append({'type': 'ip', 'value': line, 'query': fofa_service.build_query('ip', line)})
                elif re.match(r'^(\*\.)?[a-z0-9]([a-z0-9-]*\.)+[a-z]{2,}$', line, re.I):
                    val = line.lstrip('*.')
                    items.append({'type': 'domain', 'value': val, 'query': fofa_service.build_query('domain', val)})

    if not items:
        return jsonify({'error': 'No scope items to search. Add domains/IPs to your project scope.'}), 400

    # Create search records
    search_ids = []
    for item in items:
        record = IAFofaSearch(
            project_id=project.id,
            search_query=item['query'],
            scope_type=item['type'],
            scope_value=item['value'],
            status='pending',
            searched_by_id=current_user.id,
        )
        db.session.add(record)
        db.session.flush()
        search_ids.append(record.id)

    db.session.commit()

    audit_service.log('ia.fofa_search', 'ia_fofa_search', search_ids[0],
                      f'project:{project.code}', {'count': len(search_ids)})

    # Dispatch Celery task
    from app.tasks.initial_access_tasks import fofa_search_task
    result = fofa_search_task.delay(search_ids, project.id)

    return jsonify({
        'task_id': result.id,
        'search_ids': search_ids,
    }), 202


@api_bp.route('/ia/fofa/search/status/<task_id>', methods=['GET'])
@login_required
@feature_required('initial_access')
def ia_fofa_search_status(task_id):
    """Poll Celery task status for FOFA search."""
    from app.tasks.celery_app import celery

    result = celery.AsyncResult(task_id)
    response = {'task_id': task_id, 'state': result.state}

    if result.state == 'SUCCESS':
        response['result'] = result.result
    elif result.state == 'FAILURE':
        response['error'] = str(result.result)

    return jsonify(response)
