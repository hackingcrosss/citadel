from functools import wraps
from flask import jsonify, redirect, url_for, flash, request
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
