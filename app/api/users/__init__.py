import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app import db
from app.models.user import User, VALID_ROLES
from app.services.plan_service import TIERS
from app.services.plan_service import get_current_plan
from app.utils.decorators import admin_required
from app.services import audit_service

_log = logging.getLogger(__name__)


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

    email = (data.get('email') or '').strip().lower()
    display_name = (data.get('display_name') or '').strip()
    role = (data.get('role') or 'operator').strip()
    password = data.get('password') or ''

    if not email:
        return jsonify({'error': 'Email is required'}), 400
    if role not in VALID_ROLES:
        return jsonify({'error': f'Role must be one of: {", ".join(VALID_ROLES)}'}), 400
    if not password:
        return jsonify({'error': 'Password is required'}), 400
    if len(password) < 12:
        return jsonify({'error': 'Password must be at least 12 characters'}), 400

    # white_team users must be bound to a company
    company_id = data.get('company_id') or None
    if role == 'white_team':
        if not company_id:
            return jsonify({'error': 'white_team users must be assigned a company'}), 400
        from app.models.company import Company
        if not Company.query.get(company_id):
            return jsonify({'error': 'Company not found'}), 404

    # Enforce plan user limit
    plan = get_current_plan()
    current_count = User.query.count()
    if plan.at_user_limit(current_count):
        limit_str = str(plan.max_users)
        return jsonify({
            'error': f'User limit reached ({limit_str} users on {plan.display_name} plan). Upgrade your plan to add more users.',
            'code': 'PLAN_LIMIT_EXCEEDED',
            'upgrade_required': True,
        }), 402

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'A user with that email already exists'}), 409

    user = User(
        email=email,
        display_name=display_name or None,
        role=role,
        company_id=company_id if role == 'white_team' else None,
        must_change_password=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    _log.info('Admin %s created user %s (role=%s)', current_user.email, email, role)
    audit_service.log('user.create', 'user', user.id, email, {'role': role})
    return jsonify(_user_dict(user)), 201


@api_bp.route('/users/<int:user_id>', methods=['PUT'])
@login_required
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    if 'display_name' in data:
        user.display_name = (data['display_name'] or '').strip() or None

    if 'role' in data:
        new_role = data['role']
        if new_role not in VALID_ROLES:
            return jsonify({'error': f'Role must be one of: {", ".join(VALID_ROLES)}'}), 400
        # Prevent demoting the last admin
        if user.role == 'admin' and new_role != 'admin':
            admin_count = User.query.filter_by(role='admin').count()
            if admin_count <= 1:
                return jsonify({'error': 'Cannot demote the last admin user'}), 400
        user.role = new_role
        # Clear company_id when switching away from white_team
        if new_role != 'white_team':
            user.company_id = None

    if 'company_id' in data:
        company_id = data['company_id'] or None
        if company_id is not None:
            from app.models.company import Company
            if not Company.query.get(company_id):
                return jsonify({'error': 'Company not found'}), 404
        if user.role != 'white_team' and company_id is not None:
            return jsonify({'error': 'Only white_team users can be assigned a company'}), 400
        user.company_id = company_id

    if 'is_active' in data:
        # Cannot deactivate self
        if user.id == current_user.id and not data['is_active']:
            return jsonify({'error': 'Cannot deactivate your own account'}), 400
        user.is_active = bool(data['is_active'])

    if 'must_change_password' in data:
        user.must_change_password = bool(data['must_change_password'])

    if 'plan_override' in data:
        override = (data['plan_override'] or '').strip() or None
        if override and override not in TIERS:
            return jsonify({'error': f'Invalid plan tier. Must be one of: {", ".join(TIERS)}'}), 400
        # Admins cannot have a plan override — they always get enterprise
        if user.role == 'admin' and override:
            return jsonify({'error': 'Admin users always have enterprise access; plan override is not applicable'}), 400
        user.plan_override = override

    db.session.commit()
    _log.info('Admin %s updated user %s', current_user.email, user.email)
    audit_service.log('user.update', 'user', user.id, user.email,
                      {k: v for k, v in data.items() if k != 'password'})
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
    import re
    data = request.get_json(silent=True) or {}
    current_pw = data.get('current_password', '')
    new_pw = data.get('new_password', '')

    if not current_user.check_password(current_pw):
        return jsonify({'error': 'Current password is incorrect'}), 400

    # Complexity checks
    if len(new_pw) < 12:
        return jsonify({'error': 'New password must be at least 12 characters long'}), 400
    if not re.search(r'[A-Z]', new_pw):
        return jsonify({'error': 'New password must contain at least one uppercase letter'}), 400
    if not re.search(r'[a-z]', new_pw):
        return jsonify({'error': 'New password must contain at least one lowercase letter'}), 400
    if not re.search(r'[0-9]', new_pw):
        return jsonify({'error': 'New password must contain at least one digit'}), 400
    if current_user.check_password(new_pw):
        return jsonify({'error': 'New password must be different from current password'}), 400

    current_user.set_password(new_pw)
    current_user.must_change_password = False
    db.session.commit()

    audit_service.log('auth.password_change', 'user', current_user.id, current_user.email)
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
