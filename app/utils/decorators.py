from functools import wraps
from flask import jsonify, redirect, url_for, flash, request, g
from flask_login import current_user


def admin_required(f):
    """Route decorator that restricts access to admin-role users only.

    For page routes: flashes a danger message and redirects to dashboard.
    For API routes (URL starts with /api/): returns a 403 JSON error.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Administrator access required'}), 403
            flash('Administrator access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


def project_member_required(write=False):
    """Decorator factory that gates a route to members of a project.

    Resolves the project from the `project_id` integer URL kwarg.
    On success, sets `g.project` and `g.project_role` for use in the view.

    write=True: additionally requires project_role in ('project_admin', 'operator').
                Blocks white_team members from mutation endpoints.

    Global admins bypass all checks and receive g.project_role='operator'.
    Auditors bypass membership check and receive g.project_role='auditor' (read-only).

    Usage:
        @api_bp.route('/projects/<int:project_id>/resources', methods=['POST'])
        @login_required
        @project_member_required(write=True)
        def tag_resource(project_id):
            ...  # g.project and g.project_role are available
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from app.models.project import Project
            from app.services.project_service import get_user_project_role

            project_id = kwargs.get('project_id')
            project = Project.query.get_or_404(project_id)

            if current_user.is_admin:
                g.project = project
                g.project_role = 'operator'
                return f(*args, **kwargs)

            # Auditors can read any project without membership
            if current_user.is_auditor:
                if write:
                    if request.path.startswith('/api/'):
                        return jsonify({'error': 'Auditors have read-only access'}), 403
                    flash('You have read-only access.', 'danger')
                    return redirect(url_for('dashboard'))
                g.project = project
                g.project_role = 'auditor'
                return f(*args, **kwargs)

            role = get_user_project_role(current_user.id, project_id)
            if not role:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Not a member of this project'}), 403
                flash('You are not a member of this project.', 'danger')
                return redirect(url_for('dashboard'))

            if write and role not in ('project_admin', 'operator'):
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Operator access required for this action'}), 403
                flash('You do not have write access to this project.', 'danger')
                return redirect(url_for('dashboard'))

            g.project = project
            g.project_role = role
            return f(*args, **kwargs)
        return decorated
    return decorator


def feature_required(feature_name):
    """Decorator factory that gates a route or API endpoint by plan feature.

    For page routes: flashes a warning and redirects to dashboard.
    For API routes (URL starts with /api/): returns a 402 JSON error with
      upgrade_required=True so the frontend can show an upgrade prompt.

    Usage:
        @app.route('/gophish')
        @login_required
        @feature_required('gophish')
        def gophish():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from app.services.plan_service import get_current_plan
            plan = get_current_plan()
            if not plan.is_enabled(feature_name):
                if request.path.startswith('/api/'):
                    return jsonify({
                        'error': f'Feature not available on {plan.display_name} plan',
                        'code': 'FEATURE_NOT_IN_PLAN',
                        'upgrade_required': True,
                    }), 402
                flash(
                    f'This feature is not available on your current plan '
                    f'({plan.display_name}). Upgrade to unlock it.',
                    'warning',
                )
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator
