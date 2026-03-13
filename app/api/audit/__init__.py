from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app.models.audit_log import AuditLog
from app.utils.decorators import admin_required
from datetime import datetime, timedelta
import sqlalchemy as sa


def _admin_or_auditor():
    """Return True if current user is admin or auditor."""
    return current_user.is_admin or current_user.is_auditor


@api_bp.route('/audit', methods=['GET'])
@login_required
def list_audit_logs():
    if not _admin_or_auditor():
        return jsonify({'error': 'Admin or Auditor access required'}), 403
    page       = int(request.args.get('page', 1))
    per_page   = min(int(request.args.get('per_page', 50)), 200)
    action     = request.args.get('action', '').strip()
    entity_type = request.args.get('entity_type', '').strip()
    user_filter = request.args.get('user', '').strip()
    search     = request.args.get('search', '').strip()
    date_from  = request.args.get('date_from', '').strip()
    date_to    = request.args.get('date_to', '').strip()

    q = AuditLog.query.order_by(AuditLog.timestamp.desc())

    if action:
        q = q.filter(AuditLog.action == action)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    if user_filter:
        q = q.filter(AuditLog.user_email.ilike(f'%{user_filter}%'))
    if search:
        term = f'%{search}%'
        q = q.filter(
            sa.or_(
                AuditLog.entity_name.ilike(term),
                AuditLog.user_email.ilike(term),
                AuditLog.action.ilike(term),
                AuditLog.details.ilike(term),
            )
        )
    if date_from:
        try:
            q = q.filter(AuditLog.timestamp >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to) + timedelta(days=1)
            q = q.filter(AuditLog.timestamp < dt)
        except ValueError:
            pass

    total   = q.count()
    entries = q.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'entries':    [e.to_dict() for e in entries],
        'total':      total,
        'page':       page,
        'per_page':   per_page,
        'pages':      (total + per_page - 1) // per_page,
    })


@api_bp.route('/audit/meta', methods=['GET'])
@login_required
def audit_meta():
    if not _admin_or_auditor():
        return jsonify({'error': 'Admin or Auditor access required'}), 403
    """Return distinct action and entity_type values for filter dropdowns."""
    from app import db
    actions      = [r[0] for r in db.session.query(AuditLog.action).distinct().order_by(AuditLog.action).all()]
    entity_types = [r[0] for r in db.session.query(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type).all() if r[0]]
    return jsonify({'actions': actions, 'entity_types': entity_types})
