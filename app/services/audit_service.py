"""Audit logging service.

Call audit_service.log() from any API endpoint to record an infrastructure
change.

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
  credential.update     credential.delete
  auth.login            auth.login_failed     auth.password_change
  container.start       container.stop        container.restart  container.delete
  website_generator.generate  website_generator.deploy
  license.update
"""
import json
import logging
import re

_log = logging.getLogger(__name__)

# D-03: strip control characters and truncate entity_name to prevent
# log injection / CSV formula injection / search pollution.
_CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_MAX_ENTITY_NAME = 120
_MAX_DETAILS_BYTES = 16 * 1024


def _sanitise_text(value, max_len=_MAX_ENTITY_NAME):
    """Strip control chars, CSV-formula prefixes, and truncate."""
    if not value:
        return ''
    value = str(value)
    # Strip CR/LF/control bytes
    value = _CONTROL_RE.sub('', value).replace('\r', '').replace('\n', ' ')
    # CSV formula injection guard: prefix dangerous leading chars
    if value and value[0] in ('=', '+', '-', '@', '\t'):
        value = "'" + value
    return value[:max_len]


def _serialise_details(details):
    """JSON-serialise details with a hard size cap (L-09)."""
    if details is None:
        return None
    try:
        encoded = json.dumps(details, default=str)
    except Exception:
        encoded = json.dumps({'unserialisable': True, 'repr': repr(details)[:1000]})
    if len(encoded.encode('utf-8')) <= _MAX_DETAILS_BYTES:
        return encoded
    preview = encoded[:_MAX_DETAILS_BYTES]
    return json.dumps({
        'truncated': True,
        'original_bytes_min': len(encoded.encode('utf-8')),
        'preview': preview,
    })


def log(action, entity_type='', entity_id='', entity_name='', details=None,
        session=None):
    """Record an audit trail entry.

    If *session* is provided the entry is added to that SQLAlchemy session
    (L-02: caller controls the commit so audit participates in the same
    transaction). If *session* is ``None`` the function creates its own
    commit — this is the legacy path for callsites that haven't been
    migrated yet.

    On failure the exception is logged at WARNING level but never
    re-raised, so a logging failure never breaks the actual operation.
    """
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

        # D-03: sanitise user-influenced fields
        clean_name = _sanitise_text(entity_name)
        clean_eid  = _sanitise_text(str(entity_id) if entity_id != '' else '', max_len=80)

        entry = AuditLog(
            user_id     = user_id,
            user_email  = user_email,
            user_role   = user_role,
            action      = action,
            entity_type = str(entity_type or '')[:40],
            entity_id   = clean_eid,
            entity_name = clean_name,
            details     = _serialise_details(details),
            ip_address  = ip,
        )

        # L-02: if caller provides a session, add to it (same-txn audit).
        # Otherwise fall back to an independent commit.
        sess = session or db.session
        sess.add(entry)
        if session is None:
            db.session.commit()
    except Exception as exc:
        _log.warning('audit_service.log failed for action=%r: %s', action, exc)
        # L-02: attempt a rollback so the session isn't left dirty
        try:
            from app import db as _db
            _db.session.rollback()
        except Exception:
            pass
