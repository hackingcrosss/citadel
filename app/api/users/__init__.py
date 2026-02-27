import logging
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app import db
from app.models.user import User, VALID_ROLES
from app.services.plan_service import get_current_plan
from app.utils.decorators import admin_required

_log = logging.getLogger(__name__)


@api_bp.route('/users', methods=['GET'])
@login_required
@admin_required
def list_users():
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
        must_change_password=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    _log.info('Admin %s created user %s (role=%s)', current_user.email, email, role)
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

    if 'is_active' in data:
        # Cannot deactivate self
        if user.id == current_user.id and not data['is_active']:
            return jsonify({'error': 'Cannot deactivate your own account'}), 400
        user.is_active = bool(data['is_active'])

    db.session.commit()
    _log.info('Admin %s updated user %s', current_user.email, user.email)
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
    db.session.delete(user)
    db.session.commit()
    return jsonify({'deleted': True})


def _user_dict(user):
    return {
        'id': user.id,
        'email': user.email,
        'display_name': user.display_name,
        'role': user.role,
        'is_active': user.is_active,
        'must_change_password': user.must_change_password,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'last_login': user.last_login.isoformat() if user.last_login else None,
    }
