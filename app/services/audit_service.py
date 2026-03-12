"""Audit logging service.

Call audit_service.log() from any API endpoint to record an infrastructure
change. The function is intentionally safe — it never raises, so a logging
failure never breaks the actual operation.

Action naming convention:  <entity_type>.<verb>
Examples:
  domain.checkout       domain.release        domain.force_release
  dns.create            dns.delete
  project.create        project.archive       project.delete
  project.member_add    project.member_remove
  ec2.start             ec2.stop              ec2.terminate
  cs_listener.create    cs_listener.delete
  npm_proxy.create      npm_proxy.delete
  user.create           user.update           user.delete
  credential.update
  auth.login            auth.login_failed     auth.password_change
"""
import json
import logging

_log = logging.getLogger(__name__)


def log(action, entity_type='', entity_id='', entity_name='', details=None):
    """Record an audit trail entry. Never raises."""
    try:
        from flask import request
        from flask_login import current_user
        from app import db
        from app.models.audit_log import AuditLog

        try:
            user_id    = current_user.id    if current_user.is_authenticated else None
            user_email = current_user.email if current_user.is_authenticated else 'system'
            user_role  = current_user.role  if current_user.is_authenticated else None
        except Exception:
            user_id = None
            user_email = 'system'
            user_role  = None

        try:
            ip = request.remote_addr or ''
        except Exception:
            ip = ''

        entry = AuditLog(
            user_id     = user_id,
            user_email  = user_email,
            user_role   = user_role,
            action      = action,
            entity_type = entity_type or '',
            entity_id   = str(entity_id) if entity_id != '' else '',
            entity_name = entity_name or '',
            details     = json.dumps(details) if details is not None else None,
            ip_address  = ip,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as exc:
        _log.warning('audit_service.log failed for action=%r: %s', action, exc)
