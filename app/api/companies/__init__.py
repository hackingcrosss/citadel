import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app import db
from app.models.company import Company, COMPANY_STRUCTURAL_FIELDS, COMPANY_PROFILE_FIELDS
from app.models.project import Project, ProjectMember
from app.utils.decorators import admin_required
from app.services.plan_service import get_current_plan

_log = logging.getLogger(__name__)


@api_bp.before_request
def _enforce_companies_plan_feature():
    """Mirror /citadel/companies plan gating on the companies API."""
    if not request.path.startswith('/api/companies'):
        return None
    if not current_user.is_authenticated:
        return None
    plan = get_current_plan()
    if not plan.is_enabled('companies'):
        return jsonify({
            'error': f'Feature not available on {plan.display_name} plan',
            'code': 'FEATURE_NOT_IN_PLAN',
            'upgrade_required': True,
        }), 402
    return None


def _can_access_company(company_id):
    """Return True if the current user may read this company.

    Admins and auditors always can.
    project_admin/operator: via any project membership linked to this company.
    white_team: via direct company_id match OR project membership.
    """
    if current_user.is_admin or current_user.is_auditor:
        return True
    # white_team: direct company binding
    if current_user.is_white_team and current_user.company_id == company_id:
        return True
    # Any user with project membership linked to this company
    return (
        Project.query
        .filter_by(company_id=company_id, status='active')
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .filter(ProjectMember.user_id == current_user.id)
        .first() is not None
    )


@api_bp.route('/companies', methods=['GET'])
@login_required
def list_companies():
    """List companies.

    Admins: all companies.
    Operators / white_team: only companies linked to their active projects,
    enriched with per-company role and project list.
    """
    # C-06: org-level project_admin used to get the full company table here,
    # leaking unrelated tenants. Drop them from the unrestricted branch — the
    # membership-based filter below handles them like any other user.
    if current_user.is_admin or current_user.is_auditor:
        companies = Company.query.order_by(Company.name).all()
        return jsonify({'companies': [c.to_dict() for c in companies]})

    # Non-admin: companies reachable via any of the user's project memberships
    memberships = (
        ProjectMember.query
        .filter_by(user_id=current_user.id)
        .join(Project, Project.id == ProjectMember.project_id)
        .filter(Project.status == 'active', Project.company_id.isnot(None))
        .add_columns(Project.company_id, Project.code, ProjectMember.project_role)
        .all()
    )

    # Group by company_id, collect projects + determine best role per company
    from collections import defaultdict
    company_projects = defaultdict(list)
    company_best_role = {}
    for _, company_id, project_code, role in memberships:
        company_projects[company_id].append({'code': project_code, 'role': role})
        # operator beats white_team
        if company_best_role.get(company_id) != 'operator':
            company_best_role[company_id] = role

    if not company_projects:
        return jsonify({'companies': []})

    companies = Company.query.filter(
        Company.id.in_(company_projects.keys())
    ).order_by(Company.name).all()

    result = []
    for c in companies:
        d = c.to_dict()
        d['user_role'] = company_best_role.get(c.id)
        d['user_projects'] = company_projects.get(c.id, [])
        result.append(d)

    return jsonify({'companies': result})


@api_bp.route('/companies', methods=['POST'])
@login_required
@admin_required
def create_company():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    name = (data.get('name') or '').strip()
    code = (data.get('code') or '').strip().upper()
    if not name:
        return jsonify({'error': 'Company name is required'}), 400
    if not code:
        return jsonify({'error': 'Company code is required'}), 400
    if len(code) > 30:
        return jsonify({'error': 'Code must be 30 characters or fewer'}), 400

    if Company.query.filter_by(name=name).first():
        return jsonify({'error': 'A company with that name already exists'}), 409
    if Company.query.filter_by(code=code).first():
        return jsonify({'error': 'A company with that code already exists'}), 409

    company = Company(
        name=name,
        code=code,
        description=data.get('description'),
        industry=data.get('industry'),
        status='active',
        created_by_id=current_user.id,
    )
    db.session.add(company)
    db.session.commit()

    _log.info('Admin %s created company %s', current_user.email, code)
    return jsonify({'company': company.to_dict()}), 201


@api_bp.route('/companies/<int:company_id>', methods=['GET'])
@login_required
def get_company(company_id):
    company = Company.query.get_or_404(company_id)
    if not _can_access_company(company_id):
        return jsonify({'error': 'Access denied'}), 403
    include_projects = request.args.get('include_projects') == 'true'
    return jsonify({'company': company.to_dict(include_projects=include_projects)})


@api_bp.route('/companies/<int:company_id>', methods=['PATCH'])
@login_required
def update_company(company_id):
    company = Company.query.get_or_404(company_id)
    if not _can_access_company(company_id):
        return jsonify({'error': 'Access denied'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    # Non-admins may only update profile fields
    if not current_user.is_admin:
        attempted_structural = set(data.keys()) & COMPANY_STRUCTURAL_FIELDS
        if attempted_structural:
            return jsonify({
                'error': f'Only admins may update: {", ".join(sorted(attempted_structural))}',
            }), 403
        # white_team can only edit companies they are associated with
        if current_user.is_white_team and not _can_access_company(company_id):
            return jsonify({'error': 'White team users can only edit their own company profile'}), 403
        # auditors are read-only
        if current_user.is_auditor:
            return jsonify({'error': 'Auditors have read-only access'}), 403

    # Apply structural fields (admin only — already guarded above)
    for field in COMPANY_STRUCTURAL_FIELDS:
        if field in data:
            if field == 'name':
                name = (data['name'] or '').strip()
                if not name:
                    return jsonify({'error': 'Name cannot be empty'}), 400
                existing = Company.query.filter_by(name=name).first()
                if existing and existing.id != company_id:
                    return jsonify({'error': 'A company with that name already exists'}), 409
                company.name = name
            elif field == 'code':
                code = (data['code'] or '').strip().upper()
                if not code:
                    return jsonify({'error': 'Code cannot be empty'}), 400
                existing = Company.query.filter_by(code=code).first()
                if existing and existing.id != company_id:
                    return jsonify({'error': 'A company with that code already exists'}), 409
                company.code = code
            elif field == 'status':
                if data['status'] not in ('active', 'archived'):
                    return jsonify({'error': 'status must be active or archived'}), 400
                company.status = data['status']
            else:
                setattr(company, field, data[field])

    # Apply profile fields. Re-check access immediately before mutation so
    # future refactors cannot bypass the read gate by falling through to the
    # profile-field loop (B-12).
    if not current_user.is_admin and not _can_access_company(company_id):
        return jsonify({'error': 'Access denied'}), 403
    for field in COMPANY_PROFILE_FIELDS:
        if field in data:
            setattr(company, field, data[field])

    db.session.commit()
    return jsonify({'company': company.to_dict()})


@api_bp.route('/companies/<int:company_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_company(company_id):
    company = Company.query.get_or_404(company_id)

    active_count = Project.query.filter_by(company_id=company_id, status='active').count()
    if active_count:
        return jsonify({
            'error': f'Cannot delete company with {active_count} active project(s). '
                     'Archive or reassign projects first.',
            'active_project_count': active_count,
        }), 409

    db.session.delete(company)
    db.session.commit()
    _log.info('Admin %s deleted company %s', current_user.email, company.code)
    return jsonify({'deleted': True})


@api_bp.route('/companies/<int:company_id>/projects', methods=['GET'])
@login_required
@admin_required
def list_company_projects(company_id):
    company = Company.query.get_or_404(company_id)
    projects = company.projects.order_by(Project.name).all()
    return jsonify({'projects': [p.to_dict() for p in projects]})
