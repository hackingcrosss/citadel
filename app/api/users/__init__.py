import logging
from flask import request, jsonify, session
from flask_login import login_required, current_user, login_user
from app.api import api_bp
from app import db
from app.models.user import User, VALID_ROLES, validate_password_strength
from app.services.plan_service import TIERS
from app.services.plan_service import get_current_plan
from app.utils.decorators import admin_required
from app.services import audit_service

_log = logging.getLogger(__name__)

_CREATE_USER_FIELDS = frozenset({'email', 'display_name', 'password'})
_UPDATE_USER_FIELDS = frozenset({'display_name', 'is_active', 'must_change_password'})
_ROLE_UPDATE_FIELDS = frozenset({'role', 'company_id'})
_PLAN_OVERRIDE_FIELDS = frozenset({'plan_override'})


def _unknown_fields(data, allowed):
    return sorted(set(data.keys()) - set(allowed))


def _reject_unknown_fields(data, allowed):
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON object body is required'}), 400
    unknown = _unknown_fields(data, allowed)
    if unknown:
        return jsonify({'error': f'Unsupported field(s): {", ".join(unknown)}'}), 400
    return None


def _load_company(company_id):
    if company_id is None:
        return None, None
    from app.models.company import Company
    company = Company.query.get(company_id)
    if not company:
        return None, (jsonify({'error': 'Company not found'}), 404)
    return company, None


def _apply_user_role(user, new_role, company_id=None):
    """Apply a role change after validation. Caller must be admin-gated."""
    if new_role not in VALID_ROLES:
        return jsonify({'error': f'Role must be one of: {", ".join(VALID_ROLES)}'}), 400

    # Prevent demoting the last admin.
    if user.role == 'admin' and new_role != 'admin':
        admin_count = User.query.filter_by(role='admin').count()
        if admin_count <= 1:
            return jsonify({'error': 'Cannot demote the last admin user'}), 400

    if new_role == 'white_team':
        if not company_id:
            return jsonify({'error': 'white_team users must be assigned a company'}), 400
        _, err = _load_company(company_id)
        if err:
            return err
        user.company_id = company_id
    else:
        user.company_id = None

    user.role = new_role

    # Admins always derive enterprise access from role; no per-user override.
    if new_role == 'admin':
        user.plan_override = None

    return None


@api_bp.route('/users', methods=['GET'])
@login_required
def list_users():
    # Admins and project_admins can list users (project_admins need this to assign members)
    if not current_user.can_manage_projects:
        return jsonify({'error': 'Admin or Project Admin role required'}), 403
    users = User.query.order_by(User.created_at).all()
    return jsonify([_user_dict(u) for u in users])


@api_bp.route('/users', methods=['POST'])
@login_required
@admin_required
def create_user():
    data = request.get_json(silent=True) or {}
    rejected = _reject_unknown_fields(data, _CREATE_USER_FIELDS)
    if rejected:
        return rejected

    email = (data.get('email') or '').strip().lower()
    display_name = (data.get('display_name') or '').strip()
    password = data.get('password') or ''

    if not email:
        return jsonify({'error': 'Email is required'}), 400
    if not password:
        return jsonify({'error': 'Password is required'}), 400
    password_error = validate_password_strength(password)
    if password_error:
        return jsonify({'error': password_error}), 400

    # Enforce plan user limit against active seats only. Inactive users should
    # not continue consuming seats after deactivation (A-09 follow-up).
    plan = get_current_plan()
    current_count = User.query.filter_by(is_active=True).count()
    if plan.at_user_limit(current_count):
        limit_str = str(plan.max_users)
        return jsonify({
            'error': f'User limit reached ({limit_str} users on {plan.display_name} plan). Upgrade your plan to add more users.',
            'code': 'PLAN_LIMIT_EXCEEDED',
            'upgrade_required': True,
        }), 402

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'A user with that email already exists'}), 409

    # MASS-01: user creation is intentionally non-privileged-by-default. Role
    # and plan_override changes require their dedicated endpoints so they are
    # explicit, separately audited actions rather than create/update mass-assignment.
    user = User(
        email=email,
        display_name=display_name or None,
        role='operator',
        company_id=None,
        must_change_password=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    _log.info('Admin %s created user %s (role=operator)', current_user.email, email)
    audit_service.log('user.create', 'user', user.id, email, {'role': 'operator'})
    return jsonify(_user_dict(user)), 201


@api_bp.route('/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    rejected = _reject_unknown_fields(data, _UPDATE_USER_FIELDS)
    if rejected:
        return rejected

    changes = {}

    if 'display_name' in data:
        new_value = (data['display_name'] or '').strip() or None
        if user.display_name != new_value:
            changes['display_name'] = {'old': user.display_name, 'new': new_value}
            user.display_name = new_value

    if 'is_active' in data:
        new_active = bool(data['is_active'])
        # Cannot deactivate self
        if user.id == current_user.id and not new_active:
            return jsonify({'error': 'Cannot deactivate your own account'}), 400
        if user.is_active != new_active:
            changes['is_active'] = {'old': user.is_active, 'new': new_active}
            user.is_active = new_active

    if 'must_change_password' in data:
        # Admin endpoint may only force a reset. Clearing the flag is reserved
        # for the user's successful password-change flow.
        new_must_change = bool(data['must_change_password'])
        if not new_must_change:
            return jsonify({'error': 'must_change_password can only be set to true by administrators'}), 400
        if user.must_change_password != new_must_change:
            changes['must_change_password'] = {'old': user.must_change_password, 'new': new_must_change}
            user.must_change_password = new_must_change

    db.session.commit()
    _log.info('Admin %s updated user %s', current_user.email, user.email)
    if changes:
        audit_service.log('user.update', 'user', user.id, user.email, changes)
    return jsonify(_user_dict(user))


@api_bp.route('/users/<int:user_id>/role', methods=['PUT'])
@login_required
@admin_required
def update_user_role(user_id):
    """Dedicated role-management endpoint (MASS-01/C-08)."""
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    rejected = _reject_unknown_fields(data, _ROLE_UPDATE_FIELDS)
    if rejected:
        return rejected

    if 'role' not in data:
        return jsonify({'error': 'role is required'}), 400

    new_role = (data.get('role') or '').strip()
    company_id = data.get('company_id') or None
    if company_id is not None:
        try:
            company_id = int(company_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'company_id must be an integer'}), 400

    old = {'role': user.role, 'company_id': user.company_id, 'plan_override': user.plan_override}
    err = _apply_user_role(user, new_role, company_id=company_id)
    if err:
        return err

    db.session.commit()
    new = {'role': user.role, 'company_id': user.company_id, 'plan_override': user.plan_override}
    audit_service.log('user.role.update', 'user', user.id, user.email, {'old': old, 'new': new})
    return jsonify(_user_dict(user))


@api_bp.route('/users/<int:user_id>/plan-override', methods=['PUT'])
@login_required
@admin_required
def update_user_plan_override(user_id):
    """Dedicated, explicitly audited per-user plan override endpoint (B-04/C-08)."""
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}
    rejected = _reject_unknown_fields(data, _PLAN_OVERRIDE_FIELDS)
    if rejected:
        return rejected

    override = (data.get('plan_override') or '').strip() or None
    if override and override not in TIERS:
        return jsonify({'error': f'Invalid plan tier. Must be one of: {", ".join(TIERS)}'}), 400
    if user.role == 'admin' and override:
        return jsonify({'error': 'Admin users always have enterprise access; plan override is not applicable'}), 400

    old = user.plan_override
    user.plan_override = override
    db.session.commit()
    audit_service.log('user.plan_override.update', 'user', user.id, user.email, {'old': old, 'new': override})
    return jsonify(_user_dict(user))


@api_bp.route('/users/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete your own account'}), 400

    if user.role == 'admin':
        admin_count = User.query.filter_by(role='admin').count()
        if admin_count <= 1:
            return jsonify({'error': 'Cannot delete the last admin user'}), 400

    _log.info('Admin %s deleted user %s', current_user.email, user.email)
    audit_service.log('user.delete', 'user', user.id, user.email, {'role': user.role})
    db.session.delete(user)
    db.session.commit()
    return jsonify({'deleted': True})


# ---------------------------------------------------------------------------
# Self-service profile endpoints (any authenticated user)
# ---------------------------------------------------------------------------

@api_bp.route('/users/me', methods=['GET'])
@login_required
def get_me():
    return jsonify(_user_dict(current_user))


@api_bp.route('/users/me', methods=['PATCH'])
@login_required
def update_me():
    data = request.get_json(silent=True) or {}
    if 'display_name' in data:
        current_user.display_name = (data['display_name'] or '').strip() or None
    db.session.commit()
    return jsonify(_user_dict(current_user))


@api_bp.route('/users/me/password', methods=['POST'])
@login_required
def change_my_password():
    data = request.get_json(silent=True) or {}
    current_pw = data.get('current_password', '')
    new_pw = data.get('new_password', '')

    if not current_user.check_password(current_pw):
        return jsonify({'error': 'Current password is incorrect'}), 400

    # Complexity checks
    password_error = validate_password_strength(new_pw)
    if password_error:
        return jsonify({'error': password_error.replace('Password', 'New password', 1)}), 400
    if current_user.check_password(new_pw):
        return jsonify({'error': 'New password must be different from current password'}), 400

    user = current_user._get_current_object()
    user.set_password(new_pw)
    user.must_change_password = False
    db.session.commit()

    # Rotate the signed session cookie after a credential change.
    session.clear()
    session.permanent = True
    login_user(user, fresh=True)

    audit_service.log('auth.password_change', 'user', user.id, user.email)
    return jsonify({'ok': True})


def _user_dict(user):
    return {
        'id': user.id,
        'email': user.email,
        'display_name': user.display_name,
        'role': user.role,
        'company_id': user.company_id,
        'company_name': user.company.name if user.company else None,
        'plan_override': user.plan_override,
        'is_active': user.is_active,
        'must_change_password': user.must_change_password,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'last_login': user.last_login.isoformat() if user.last_login else None,
    }
