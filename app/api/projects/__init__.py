import logging
from datetime import datetime
from flask import request, jsonify, session
from flask_login import login_required, current_user
from app.api import api_bp
from app import db
from app.models.project import Project, ProjectMember, PROJECT_ROLES
from app.models.project_resource import ProjectResource, RESOURCE_TYPES
from app.models.domain import Domain
from app.models.user import User
from app.utils.decorators import admin_required, project_member_required
from app.services.project_service import (
    get_projects_for_user,
    get_user_project_role,
    get_active_project,
    set_active_project,
    clear_active_project,
    get_resources_by_project,
    assert_domain_accessible,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Projects CRUD
# ---------------------------------------------------------------------------

@api_bp.route('/projects', methods=['GET'])
@login_required
def list_projects():
    projects = get_projects_for_user(current_user)
    return jsonify([p.to_dict() for p in projects])


@api_bp.route('/projects', methods=['POST'])
@login_required
@admin_required
def create_project():
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    code = (data.get('code') or '').strip().upper()
    description = (data.get('description') or '').strip() or None

    if not name:
        return jsonify({'error': 'Project name is required'}), 400
    if not code:
        return jsonify({'error': 'Project code is required'}), 400
    if len(code) > 30:
        return jsonify({'error': 'Project code must be 30 characters or fewer'}), 400

    if Project.query.filter_by(code=code).first():
        return jsonify({'error': f'Project code "{code}" is already in use'}), 409

    company_id = data.get('company_id') or None
    if company_id:
        from app.models.company import Company
        if not Company.query.get(company_id):
            return jsonify({'error': 'Company not found'}), 404

    project = Project(
        name=name,
        code=code,
        description=description,
        company_id=company_id,
        status='active',
        created_by_id=current_user.id,
    )
    db.session.add(project)
    db.session.flush()

    # Creator is automatically added as an operator member
    member = ProjectMember(
        project_id=project.id,
        user_id=current_user.id,
        project_role='operator',
        added_by_id=current_user.id,
    )
    db.session.add(member)
    db.session.commit()

    _log.info('Admin %s created project %s', current_user.email, code)
    return jsonify(project.to_dict(include_members=True)), 201


@api_bp.route('/projects/<int:project_id>', methods=['GET'])
@login_required
@project_member_required()
def get_project(project_id):
    from flask import g
    return jsonify(g.project.to_dict(include_members=True))


@api_bp.route('/projects/<int:project_id>', methods=['PATCH'])
@login_required
@admin_required
def update_project(project_id):
    project = Project.query.get_or_404(project_id)
    data = request.get_json(silent=True) or {}

    if 'name' in data:
        name = (data['name'] or '').strip()
        if not name:
            return jsonify({'error': 'Project name cannot be empty'}), 400
        project.name = name

    if 'description' in data:
        project.description = (data['description'] or '').strip() or None

    if 'status' in data:
        status = data['status']
        if status not in ('active', 'archived'):
            return jsonify({'error': 'Status must be "active" or "archived"'}), 400
        project.status = status

    if 'company_id' in data:
        cid = data['company_id']
        if cid is not None:
            from app.models.company import Company
            if not Company.query.get(cid):
                return jsonify({'error': 'Company not found'}), 404
        project.company_id = cid

    db.session.commit()
    _log.info('Admin %s updated project %s', current_user.email, project.code)
    return jsonify(project.to_dict())


@api_bp.route('/projects/<int:project_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_project(project_id):
    project = Project.query.get_or_404(project_id)

    # Block deletion if any domains are currently checked out
    checked_out = Domain.query.filter_by(checkout_project_id=project_id).count()
    if checked_out:
        return jsonify({
            'error': f'Cannot delete project: {checked_out} domain(s) are still checked out. '
                     'Release all domains first.',
        }), 409

    _log.info('Admin %s deleted project %s', current_user.email, project.code)
    db.session.delete(project)
    db.session.commit()
    return jsonify({'deleted': True})


# ---------------------------------------------------------------------------
# Project Members
# ---------------------------------------------------------------------------

@api_bp.route('/projects/<int:project_id>/members', methods=['GET'])
@login_required
@project_member_required()
def list_members(project_id):
    from flask import g
    members = ProjectMember.query.filter_by(project_id=project_id).all()
    return jsonify([m.to_dict() for m in members])


@api_bp.route('/projects/<int:project_id>/members', methods=['POST'])
@login_required
@admin_required
def add_member(project_id):
    project = Project.query.get_or_404(project_id)
    data = request.get_json(silent=True) or {}

    user_id = data.get('user_id')
    project_role = (data.get('project_role') or 'operator').strip()

    if not user_id:
        return jsonify({'error': 'user_id is required'}), 400
    if project_role not in PROJECT_ROLES:
        return jsonify({'error': f'project_role must be one of: {", ".join(PROJECT_ROLES)}'}), 400

    user = User.query.get_or_404(user_id)

    if ProjectMember.query.filter_by(project_id=project_id, user_id=user_id).first():
        return jsonify({'error': 'User is already a member of this project'}), 409

    member = ProjectMember(
        project_id=project_id,
        user_id=user_id,
        project_role=project_role,
        added_by_id=current_user.id,
    )
    db.session.add(member)
    db.session.commit()

    _log.info('Admin %s added user %s to project %s as %s',
              current_user.email, user.email, project.code, project_role)
    return jsonify(member.to_dict()), 201


@api_bp.route('/projects/<int:project_id>/members/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def update_member(project_id, user_id):
    Project.query.get_or_404(project_id)
    member = ProjectMember.query.filter_by(
        project_id=project_id, user_id=user_id
    ).first_or_404()
    data = request.get_json(silent=True) or {}

    project_role = (data.get('project_role') or '').strip()
    if not project_role:
        return jsonify({'error': 'project_role is required'}), 400
    if project_role not in PROJECT_ROLES:
        return jsonify({'error': f'project_role must be one of: {", ".join(PROJECT_ROLES)}'}), 400

    member.project_role = project_role
    db.session.commit()
    return jsonify(member.to_dict())


@api_bp.route('/projects/<int:project_id>/members/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def remove_member(project_id, user_id):
    Project.query.get_or_404(project_id)
    member = ProjectMember.query.filter_by(
        project_id=project_id, user_id=user_id
    ).first_or_404()

    db.session.delete(member)
    db.session.commit()
    return jsonify({'deleted': True})


# ---------------------------------------------------------------------------
# Domain Checkout / Release
# ---------------------------------------------------------------------------

@api_bp.route('/projects/<int:project_id>/domains', methods=['GET'])
@login_required
@project_member_required()
def list_project_domains(project_id):
    domains = Domain.query.filter_by(checkout_project_id=project_id).order_by(Domain.name).all()
    return jsonify([d.to_dict() for d in domains])


@api_bp.route('/projects/<int:project_id>/domains/<int:domain_id>/checkout', methods=['POST'])
@login_required
@project_member_required(write=True)
def checkout_domain(project_id, domain_id):
    from flask import g
    project = g.project
    if project.status == 'archived':
        return jsonify({'error': 'Cannot check out domains to an archived project'}), 409

    # SELECT FOR UPDATE prevents race conditions
    domain = Domain.query.with_for_update().get(domain_id)

    # If the domain record doesn't exist locally yet, auto-create it from the
    # request body. This allows operators to check out CF zones that haven't
    # been imported by an admin yet (the frontend passes name/cloudflare_zone_id).
    if domain is None:
        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip().lower()
        zone_id = (data.get('cloudflare_zone_id') or '').strip()
        if not name:
            return jsonify({'error': 'Domain not found and no name provided to create it'}), 404
        # Avoid duplicate by name
        domain = Domain.query.filter_by(name=name).first()
        if domain is None:
            domain = Domain(
                name=name,
                cloudflare_zone_id=zone_id or None,
                status='active',
                credential_label=data.get('credential_label', 'default') or 'default',
                provider=data.get('provider', 'cloudflare') or 'cloudflare',
            )
            db.session.add(domain)
            db.session.flush()  # get domain.id without committing yet

    if domain.checkout_project_id is not None:
        conflict_project = Project.query.get(domain.checkout_project_id)
        conflict_code = conflict_project.code if conflict_project else '?'
        return jsonify({
            'error': f'Domain is already checked out to project {conflict_code}',
            'checkout_project_id': domain.checkout_project_id,
        }), 409

    domain.checkout_project_id = project_id
    domain.checked_out_at = datetime.utcnow()
    domain.checked_out_by_id = current_user.id
    db.session.commit()

    _log.info('User %s checked out domain %s to project %s',
              current_user.email, domain.name, project.code)
    return jsonify(domain.to_dict())


@api_bp.route('/projects/<int:project_id>/domains/<int:domain_id>/release', methods=['POST'])
@login_required
@project_member_required(write=True)
def release_domain(project_id, domain_id):
    domain = Domain.query.get_or_404(domain_id)

    if domain.checkout_project_id != project_id:
        return jsonify({'error': 'Domain is not checked out to this project'}), 409

    domain.checkout_project_id = None
    domain.checked_out_at = None
    domain.checked_out_by_id = None
    db.session.commit()

    _log.info('User %s released domain %s from project %s',
              current_user.email, domain.name, project_id)
    return jsonify(domain.to_dict())


@api_bp.route('/admin/domains/<int:domain_id>/force-release', methods=['POST'])
@login_required
@admin_required
def force_release_domain(domain_id):
    domain = Domain.query.get_or_404(domain_id)

    if domain.checkout_project_id is None:
        return jsonify({'error': 'Domain is not checked out'}), 409

    prev_project_id = domain.checkout_project_id
    prev_project = Project.query.get(prev_project_id)
    domain.checkout_project_id = None
    domain.checked_out_at = None
    domain.checked_out_by_id = None
    db.session.commit()

    _log.warning('Admin %s force-released domain %s from project %s',
                 current_user.email, domain.name,
                 prev_project.code if prev_project else prev_project_id)
    return jsonify(domain.to_dict())


# ---------------------------------------------------------------------------
# Domain Readiness Checklist
# ---------------------------------------------------------------------------

@api_bp.route('/projects/<int:project_id>/domains/<int:domain_id>/readiness', methods=['GET'])
@login_required
@project_member_required()
def domain_readiness(project_id, domain_id):
    domain = Domain.query.get_or_404(domain_id)
    if domain.checkout_project_id != project_id:
        return jsonify({'error': 'Domain is not checked out to this project'}), 404
    from app.services.readiness_service import check_domain_readiness
    result = check_domain_readiness(domain)
    return jsonify(result)


# ---------------------------------------------------------------------------
# Project Resources (tagging non-domain infra)
# ---------------------------------------------------------------------------

@api_bp.route('/projects/<int:project_id>/resources', methods=['GET'])
@login_required
@project_member_required()
def list_resources(project_id):
    resource_type = request.args.get('type')
    resources = get_resources_by_project(project_id, resource_type)
    return jsonify([r.to_dict() for r in resources])


@api_bp.route('/projects/<int:project_id>/resources', methods=['POST'])
@login_required
@project_member_required(write=True)
def tag_resource(project_id):
    data = request.get_json(silent=True) or {}

    resource_type = (data.get('resource_type') or '').strip()
    external_id = (data.get('external_id') or '').strip()
    label = (data.get('label') or '').strip() or None

    if not resource_type:
        return jsonify({'error': 'resource_type is required'}), 400
    if resource_type not in RESOURCE_TYPES:
        return jsonify({'error': f'resource_type must be one of: {", ".join(RESOURCE_TYPES)}'}), 400
    if not external_id:
        return jsonify({'error': 'external_id is required'}), 400

    existing = ProjectResource.query.filter_by(
        project_id=project_id,
        resource_type=resource_type,
        external_id=external_id,
    ).first()
    if existing:
        return jsonify({'error': 'Resource is already tagged to this project'}), 409

    resource = ProjectResource(
        project_id=project_id,
        resource_type=resource_type,
        external_id=external_id,
        label=label,
        tagged_by_id=current_user.id,
    )
    db.session.add(resource)
    db.session.commit()

    _log.info('User %s tagged %s:%s to project %s',
              current_user.email, resource_type, external_id, project_id)
    return jsonify(resource.to_dict()), 201


@api_bp.route('/projects/<int:project_id>/resources/<int:resource_id>', methods=['DELETE'])
@login_required
@project_member_required(write=True)
def untag_resource(project_id, resource_id):
    resource = ProjectResource.query.filter_by(
        id=resource_id, project_id=project_id
    ).first_or_404()

    _log.info('User %s untagged %s:%s from project %s',
              current_user.email, resource.resource_type, resource.external_id, project_id)
    db.session.delete(resource)
    db.session.commit()
    return jsonify({'deleted': True})


# ---------------------------------------------------------------------------
# Active Project (session)
# ---------------------------------------------------------------------------

@api_bp.route('/projects/active', methods=['GET'])
@login_required
def get_active():
    project = get_active_project(current_user)
    if not project:
        return jsonify({'active_project': None})
    return jsonify({'active_project': project.to_dict()})


@api_bp.route('/projects/<int:project_id>/activate', methods=['POST'])
@login_required
def activate_project(project_id):
    project = set_active_project(current_user, project_id)
    return jsonify({'active_project': project.to_dict()})


@api_bp.route('/projects/active', methods=['DELETE'])
@login_required
def deactivate_project():
    clear_active_project()
    return jsonify({'active_project': None})
