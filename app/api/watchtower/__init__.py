"""Watchtower API — project-scoped IOC portal for white-team users."""

from flask import Response, jsonify
from flask_login import login_required, current_user

from app.api import api_bp
from app.services import watchtower_service


def _white_team_or_403():
    if not current_user.is_authenticated or not current_user.is_white_team:
        return jsonify({'error': 'White team access required'}), 403
    if not current_user.company_id:
        return jsonify({'error': 'White team user is not assigned to a company'}), 403
    return None


@api_bp.route('/watchtower/projects', methods=['GET'])
@login_required
def watchtower_projects():
    denied = _white_team_or_403()
    if denied:
        return denied
    projects = watchtower_service.list_watchtower_projects(current_user)
    return jsonify({
        'projects': [watchtower_service.project_summary(p) for p in projects],
        'generated_at': watchtower_service.generated_at(),
    })


@api_bp.route('/watchtower/projects/<int:project_id>/iocs', methods=['GET'])
@login_required
def watchtower_project_iocs(project_id):
    denied = _white_team_or_403()
    if denied:
        return denied
    project = watchtower_service.assert_watchtower_project(current_user, project_id)
    iocs = watchtower_service.collect_project_iocs(project)
    return jsonify({
        'project': watchtower_service.project_summary(project, iocs=iocs),
        'iocs': iocs,
        'generated_at': watchtower_service.generated_at(),
    })


@api_bp.route('/watchtower/projects/<int:project_id>/iocs.csv', methods=['GET'])
@login_required
def watchtower_project_iocs_csv(project_id):
    denied = _white_team_or_403()
    if denied:
        return denied
    project = watchtower_service.assert_watchtower_project(current_user, project_id)
    iocs = watchtower_service.collect_project_iocs(project)
    csv_body = watchtower_service.iocs_to_csv(iocs)
    filename = f'watchtower-{project.code}-iocs.csv'
    return Response(
        csv_body,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
