import logging
import re
from flask import abort, session
from app.models.project import Project, ProjectMember
from app.models.project_resource import ProjectResource

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Membership helpers
# ---------------------------------------------------------------------------

def get_projects_for_user(user):
    """Return all projects visible to the user.

    Admins and auditors see all projects.
    project_admin/operator/white_team see only their memberships.
    """
    if user.is_admin or user.is_auditor:
        return Project.query.order_by(Project.name).all()
    memberships = ProjectMember.query.filter_by(user_id=user.id).all()
    project_ids = [m.project_id for m in memberships]
    if not project_ids:
        return []
    return Project.query.filter(Project.id.in_(project_ids)).order_by(Project.name).all()


def get_user_project_ids(user):
    """Return the set of project IDs the user can access.

    Admins and auditors get all project IDs. Others get only their memberships.
    """
    if user.is_admin or user.is_auditor:
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
    if user.is_auditor or user.is_white_team:
        return False
    if user.is_admin:
        return True
    return get_user_project_role(user.id, project_id) in ('project_admin', 'operator')


def can_read(user, project_id):
    """True if the user has any membership (including white_team) in this project."""
    if user.is_admin or user.is_auditor:
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


def build_project_tag_map(resource_type, external_ids):
    """Bulk-fetch project tags for a list of external resource IDs.

    Returns {external_id: {'project_id': int, 'project_code': str}}.
    Single JOIN query — safe to call on large lists.
    """
    if not external_ids:
        return {}
    from app import db
    from app.models.project import Project
    rows = (
        db.session.query(ProjectResource, Project.code)
        .join(Project, ProjectResource.project_id == Project.id)
        .filter(
            ProjectResource.resource_type == resource_type,
            ProjectResource.external_id.in_(external_ids),
        )
        .all()
    )
    return {
        r.external_id: {'project_id': r.project_id, 'project_code': code, 'project_resource_id': r.id}
        for r, code in rows
    }


def filter_by_active_project(user, items, active_project):
    """Scope a list of enriched resource dicts to the active project.

    - Admins see everything regardless of active project.
    - Non-admins with an active project see only items whose project_id matches.
    - Non-admins with no active project see nothing (empty list).
    """
    if user.is_admin or user.is_auditor:
        return items
    if active_project is None:
        return []
    return [i for i in items if i.get('project_id') == active_project.id]


def get_project_domain_names(project_id):
    """Return the set of domain names checked out to a project."""
    from app.models.domain import Domain
    rows = Domain.query.filter_by(checkout_project_id=project_id).with_entities(Domain.name).all()
    return {row[0] for row in rows}


def get_project_resource_external_ids(project_id, resource_type):
    """Return the set of external_ids for a project's tagged resources of a given type."""
    rows = ProjectResource.query.filter_by(
        project_id=project_id,
        resource_type=resource_type,
    ).with_entities(ProjectResource.external_id).all()
    return {row[0] for row in rows}


def assert_record_accessible(obj, user, write=False):
    """Abort 403 if *user* cannot access a project-owned DB record.

    Authorization is based on the record's ``project_id`` and the user's
    membership — NOT the session's active-project.  This replaces the
    pattern where IA endpoints compared ``obj.project_id`` against
    ``get_active_project()`` (C-04).

    Rules:
        - Admins: always allowed.
        - Auditors: read-only access to any project.
        - Others: must hold a membership for ``obj.project_id``.
          Write access additionally requires an operator or project_admin
          role in that project.
    """
    if user.is_admin:
        return
    if user.is_auditor:
        if write:
            abort(403)
        return
    project_id = getattr(obj, 'project_id', None)
    if project_id is None:
        abort(403)
    if not can_read(user, project_id):
        abort(403)
    if write and not can_write(user, project_id):
        abort(403)


def assert_resource_writable(resource_type, external_id, user):
    """Abort 403 if the user cannot perform write actions on this external resource.

    Rules:
    - Admins: always allowed.
    - Pure white_team users (no operator memberships at all): always blocked.
    - Platform-core containers (citadel-web, citadel-postgres, …): always
      blocked for non-admins (K-02).
    - Operators: allowed ONLY if the resource has a ProjectResource row tagged
      to one of their own projects. Untagged resources are blocked — the read
      path tolerates untagged (K-03 workaround) but the write path must not.
    """
    if user.is_admin:
        return

    if not user.can_write_infra and not user.is_project_admin:
        abort(403, description='Operator or project-admin access is required for this action')

    # K-02: deny writes to platform-core containers for all non-admins
    if resource_type == 'container' and is_platform_core_container(external_id):
        abort(403, description='Platform containers can only be managed by administrators')

    resource = ProjectResource.query.filter_by(
        resource_type=resource_type, external_id=str(external_id)
    ).first()
    # K-02: untagged resources are NOT writable by non-admins.
    # This prevents operators from acting on platform containers or
    # cross-tenant website-generator containers that lack a tag.
    if resource is None:
        abort(403, description='Resource must be tagged to one of your projects before it can be modified')
    if resource.project_id not in get_user_project_ids(user) or not can_write(user, resource.project_id):
        abort(403, description='Resource is tagged to a project you cannot modify')


_CONTAINER_PLATFORM_CORE_RE = re.compile(
    r'^/?citadel-(web|celery|postgres|redis|nginx)$'
)


def is_platform_core_container(name_or_id):
    """True if the given docker container name matches the platform-core deny-list."""
    return bool(_CONTAINER_PLATFORM_CORE_RE.match(str(name_or_id or '')))


def assert_resource_readable(resource_type, external_id, user):
    """Abort 403 if the user cannot read this external resource.

    Rules:
    - Admins: always allowed.
    - Plain users: blocked.
    - Platform-core containers (citadel-web, citadel-postgres, etc.) are hidden
      from all non-admins.
    - Operators may read untagged containers as a temporary K-03 workaround
      because deploy flows do not auto-tag every container yet; tagged
      resources must belong to one of their projects.
    - Project-admin, white-team, and auditor reads are stricter: the resource
      must be tagged to a project they can read. This restores project-scoped
      container visibility without reopening the K-01 all-container read issue.
    """
    if user.is_admin:
        return
    if not (user.is_operator or user.is_project_admin or user.is_white_team or user.is_auditor):
        abort(403)
    if resource_type == 'container' and is_platform_core_container(external_id):
        abort(403)

    resource = ProjectResource.query.filter_by(
        resource_type=resource_type, external_id=str(external_id)
    ).first()
    if user.is_operator:
        if resource is not None and resource.project_id not in get_user_project_ids(user):
            abort(403)
        return

    if resource is None or resource.project_id not in get_user_project_ids(user):
        abort(403)
