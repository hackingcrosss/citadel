import logging
from flask import abort, session
from app.models.project import Project, ProjectMember
from app.models.project_resource import ProjectResource

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Membership helpers
# ---------------------------------------------------------------------------

def get_projects_for_user(user):
    """Return all projects visible to the user.

    Admins see all projects. Operators/white_team see only their memberships.
    """
    if user.is_admin:
        return Project.query.order_by(Project.name).all()
    memberships = ProjectMember.query.filter_by(user_id=user.id).all()
    project_ids = [m.project_id for m in memberships]
    if not project_ids:
        return []
    return Project.query.filter(Project.id.in_(project_ids)).order_by(Project.name).all()


def get_user_project_ids(user):
    """Return the set of project IDs the user can access.

    Admins get all project IDs. Others get only their memberships.
    """
    if user.is_admin:
        ids = Project.query.with_entities(Project.id).all()
        return {row[0] for row in ids}
    rows = ProjectMember.query.filter_by(user_id=user.id).with_entities(
        ProjectMember.project_id
    ).all()
    return {row[0] for row in rows}


def get_user_project_role(user_id, project_id):
    """Return the user's project_role string for this project, or None if not a member."""
    member = ProjectMember.query.filter_by(
        user_id=user_id, project_id=project_id
    ).first()
    return member.project_role if member else None


def can_write(user, project_id):
    """True if the user can perform write actions on this project."""
    if user.is_admin:
        return True
    return get_user_project_role(user.id, project_id) == 'operator'


def can_read(user, project_id):
    """True if the user has any membership (including white_team) in this project."""
    if user.is_admin:
        return True
    return get_user_project_role(user.id, project_id) is not None


# ---------------------------------------------------------------------------
# Domain access guard
# ---------------------------------------------------------------------------

def assert_domain_accessible(domain, user):
    """Abort 403 if the user cannot access this domain.

    - Admins can always access any domain.
    - Operators/white_team can only access domains checked out to their projects.
    - Available (un-checked-out) domains are not visible to non-admins outside of
      the checkout flow itself.
    """
    if user.is_admin:
        return
    if domain.checkout_project_id is None:
        abort(403)
    if domain.checkout_project_id not in get_user_project_ids(user):
        abort(403)


# ---------------------------------------------------------------------------
# Active project (session)
# ---------------------------------------------------------------------------

def get_active_project(user):
    """Return the currently active project for this user (stored in session), or None."""
    try:
        project_id = session.get('active_project_id')
        if not project_id:
            return None
        project = Project.query.get(project_id)
        if not project:
            session.pop('active_project_id', None)
            return None
        if not can_read(user, project_id):
            session.pop('active_project_id', None)
            return None
        return project
    except Exception:
        return None


def set_active_project(user, project_id):
    """Set the active project in session. Returns the project or raises 403/404."""
    project = Project.query.get_or_404(project_id)
    if not can_read(user, project_id):
        abort(403)
    session['active_project_id'] = project_id
    return project


def clear_active_project():
    session.pop('active_project_id', None)


# ---------------------------------------------------------------------------
# Resource tagging helpers
# ---------------------------------------------------------------------------

def tag_resource(project_id, resource_type, external_id, label, user_id):
    """Add a resource association to a project. Returns (resource, created)."""
    from app import db
    existing = ProjectResource.query.filter_by(
        project_id=project_id,
        resource_type=resource_type,
        external_id=external_id,
    ).first()
    if existing:
        return existing, False
    resource = ProjectResource(
        project_id=project_id,
        resource_type=resource_type,
        external_id=external_id,
        label=label or '',
        tagged_by_id=user_id,
    )
    db.session.add(resource)
    db.session.commit()
    return resource, True


def get_resource_project(resource_type, external_id):
    """Return the ProjectResource row for an external resource, or None."""
    return ProjectResource.query.filter_by(
        resource_type=resource_type,
        external_id=external_id,
    ).first()


def get_resources_by_project(project_id, resource_type=None):
    """Return all ProjectResource rows for a project, optionally filtered by type."""
    q = ProjectResource.query.filter_by(project_id=project_id)
    if resource_type:
        q = q.filter_by(resource_type=resource_type)
    return q.all()
