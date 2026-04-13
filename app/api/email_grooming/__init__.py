import re
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app import db
from app.models.domain import Domain
from app.models.email_grooming import EmailGroomingConfig
from app.models.email_grooming_log import EmailGroomingLog
from app.services.project_service import get_active_project, assert_domain_accessible

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
_OUTLOOK_DOMAINS = {
    'outlook.com', 'hotmail.com', 'live.com', 'msn.com',
    'outlook.fr', 'outlook.de', 'outlook.co.uk', 'hotmail.co.uk',
    'hotmail.fr', 'hotmail.de', 'live.co.uk', 'live.fr',
}


def _is_outlook(email):
    domain = email.rsplit('@', 1)[-1].lower()
    return domain in _OUTLOOK_DOMAINS


def _project_domain_ids():
    """Return set of domain IDs belonging to the active project, or None if unscoped (admin/auditor)."""
    _auditor_unscoped = current_user.is_auditor and get_active_project(current_user) is None
    if current_user.is_admin or _auditor_unscoped:
        return None  # no filtering
    active_project = get_active_project(current_user)
    if active_project is None:
        return set()  # no project → empty
    ids = {d.id for d in Domain.query.filter_by(checkout_project_id=active_project.id).with_entities(Domain.id).all()}
    return ids


# ---------------------------------------------------------------------------
# List all configs (with optional domain filter)
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming', methods=['GET'])
@login_required
def list_email_grooming():
    domain_id = request.args.get('domain_id', type=int)
    q = EmailGroomingConfig.query
    if domain_id:
        q = q.filter_by(domain_id=domain_id)

    # Scope to active project's domains
    allowed_ids = _project_domain_ids()
    if allowed_ids is not None:
        q = q.filter(EmailGroomingConfig.domain_id.in_(allowed_ids)) if allowed_ids else q.filter(db.false())

    configs = q.order_by(EmailGroomingConfig.created_at.desc()).all()

    # Aggregate stats
    total_configs = len(configs)
    total_sent = sum(c.emails_sent for c in configs)
    active_count = sum(1 for c in configs if c.status == 'active')

    # Enrich with GoPhish profile from_address for pinned profiles
    profile_map = {}
    pinned_ids = {c.gophish_profile_id for c in configs if c.gophish_profile_id}
    if pinned_ids:
        try:
            from app.services import gophish_service
            all_profiles = gophish_service.list_sending_profiles()
            if isinstance(all_profiles, list):
                for p in all_profiles:
                    if p.get('id') in pinned_ids:
                        profile_map[p['id']] = p.get('from_address', '')
        except Exception:
            pass

    result = []
    for c in configs:
        d = c.to_dict()
        d['gophish_profile_from'] = profile_map.get(c.gophish_profile_id, '')
        result.append(d)

    return jsonify({
        'configs': result,
        'stats': {
            'total_configs': total_configs,
            'active_configs': active_count,
            'total_emails_sent': total_sent,
        },
    })


# ---------------------------------------------------------------------------
# Create configs (one domain, multiple target emails)
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming', methods=['POST'])
@login_required
def create_email_grooming():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    domain_id = data.get('domain_id')
    if not domain_id:
        return jsonify({'error': 'domain_id is required'}), 400

    domain = Domain.query.get(domain_id)
    if not domain:
        return jsonify({'error': 'Domain not found'}), 404

    if not current_user.is_admin:
        try:
            assert_domain_accessible(domain_id, current_user, write=True)
        except Exception:
            return jsonify({'error': 'You do not have write access to this domain'}), 403

    targets = data.get('targets') or []
    if not targets:
        return jsonify({'error': 'At least one target email is required'}), 400

    emails_per_day = data.get('emails_per_day', 10)
    if not isinstance(emails_per_day, int) or emails_per_day < 1 or emails_per_day > 50:
        return jsonify({'error': 'emails_per_day must be between 1 and 50'}), 400

    # Optional: pin to a specific GoPhish sending profile (null = rotate all)
    gophish_profile_id = data.get('gophish_profile_id')
    if gophish_profile_id is not None:
        gophish_profile_id = int(gophish_profile_id) if gophish_profile_id else None

    created = []
    skipped = []
    warnings = []

    for raw in targets:
        email = str(raw).strip().lower()
        if not email or not _EMAIL_RE.match(email):
            skipped.append({'email': raw, 'reason': 'invalid email format'})
            continue

        if not _is_outlook(email):
            warnings.append(f'{email} is not an Outlook/Hotmail address — deliverability warming may be less effective')

        existing = EmailGroomingConfig.query.filter_by(
            domain_id=domain_id, target_email=email
        ).first()
        if existing:
            skipped.append({'email': email, 'reason': 'already configured'})
            continue

        config = EmailGroomingConfig(
            domain_id=domain_id,
            target_email=email,
            emails_per_day=emails_per_day,
            gophish_profile_id=gophish_profile_id,
            status='active',
        )
        db.session.add(config)
        created.append(email)

    db.session.commit()

    return jsonify({
        'created': created,
        'skipped': skipped,
        'warnings': warnings,
        'count': len(created),
    }), 201 if created else 200


# ---------------------------------------------------------------------------
# Update config (pause/resume/change rate)
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming/<int:config_id>', methods=['PATCH'])
@login_required
def update_email_grooming(config_id):
    config = EmailGroomingConfig.query.get(config_id)
    if not config:
        return jsonify({'error': 'Config not found'}), 404
    if not current_user.is_admin:
        try:
            assert_domain_accessible(config.domain_id, current_user, write=True)
        except Exception:
            return jsonify({'error': 'You do not have write access to this domain'}), 403
    data = request.get_json(silent=True) or {}

    if 'status' in data:
        if data['status'] not in ('active', 'paused'):
            return jsonify({'error': 'Status must be "active" or "paused"'}), 400
        config.status = data['status']

    if 'emails_per_day' in data:
        epd = data['emails_per_day']
        if not isinstance(epd, int) or epd < 1 or epd > 50:
            return jsonify({'error': 'emails_per_day must be between 1 and 50'}), 400
        config.emails_per_day = epd

    if 'gophish_profile_id' in data:
        val = data['gophish_profile_id']
        config.gophish_profile_id = int(val) if val else None

    db.session.commit()
    return jsonify(config.to_dict())


# ---------------------------------------------------------------------------
# Delete config
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming/<int:config_id>', methods=['DELETE'])
@login_required
def delete_email_grooming(config_id):
    config = EmailGroomingConfig.query.get(config_id)
    if not config:
        return jsonify({'error': 'Config not found'}), 404
    if not current_user.is_admin:
        try:
            assert_domain_accessible(config.domain_id, current_user, write=True)
        except Exception:
            return jsonify({'error': 'You do not have write access to this domain'}), 403
    try:
        # Delete associated logs first (in case CASCADE isn't set at DB level)
        EmailGroomingLog.query.filter_by(config_id=config_id).delete()
        db.session.delete(config)
        db.session.commit()
        return jsonify({'deleted': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Bulk delete by domain
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming/domain/<int:domain_id>', methods=['DELETE'])
@login_required
def delete_email_grooming_by_domain(domain_id):
    try:
        config_ids = [c.id for c in EmailGroomingConfig.query.filter_by(domain_id=domain_id).all()]
        if config_ids:
            EmailGroomingLog.query.filter(EmailGroomingLog.config_id.in_(config_ids)).delete(synchronize_session=False)
        count = EmailGroomingConfig.query.filter_by(domain_id=domain_id).delete()
        db.session.commit()
        return jsonify({'deleted': count})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Send now (manual trigger for a single config)
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming/<int:config_id>/send', methods=['POST'])
@login_required
def send_email_grooming_now(config_id):
    config = EmailGroomingConfig.query.get(config_id)
    if not config:
        return jsonify({'error': 'Config not found'}), 404
    try:
        from app.tasks.email_grooming_tasks import send_grooming_email_now
        task = send_grooming_email_now.delay(config.id)
        return jsonify({'task_id': task.id, 'status': 'queued'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Trigger full grooming cycle (all active configs)
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming/run-cycle', methods=['POST'])
@login_required
def run_email_grooming_cycle():
    try:
        from app.tasks.email_grooming_tasks import run_full_grooming_cycle
        task = run_full_grooming_cycle.delay()
        return jsonify({'task_id': task.id, 'status': 'queued'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Send logs (recent history)
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming/logs', methods=['GET'])
@login_required
def list_email_grooming_logs():
    config_id = request.args.get('config_id', type=int)
    limit = request.args.get('limit', 50, type=int)
    limit = min(limit, 200)

    # Scope to active project's domains
    allowed_ids = _project_domain_ids()
    allowed_config_ids = None
    if allowed_ids is not None:
        allowed_config_ids = {c.id for c in EmailGroomingConfig.query.filter(
            EmailGroomingConfig.domain_id.in_(allowed_ids)
        ).with_entities(EmailGroomingConfig.id).all()} if allowed_ids else set()

    q = EmailGroomingLog.query
    if config_id:
        q = q.filter_by(config_id=config_id)
    if allowed_config_ids is not None:
        q = q.filter(EmailGroomingLog.config_id.in_(allowed_config_ids)) if allowed_config_ids else q.filter(db.false())
    logs = q.order_by(EmailGroomingLog.sent_at.desc()).limit(limit).all()

    # Also compute today's stats
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_q = EmailGroomingLog.query.filter(EmailGroomingLog.sent_at >= today_start)
    if config_id:
        today_q = today_q.filter_by(config_id=config_id)
    if allowed_config_ids is not None:
        today_q = today_q.filter(EmailGroomingLog.config_id.in_(allowed_config_ids)) if allowed_config_ids else today_q.filter(db.false())
    today_sent = today_q.filter_by(success=True).count()
    today_failed = today_q.filter_by(success=False).count()

    return jsonify({
        'logs': [l.to_dict() for l in logs],
        'today': {
            'sent': today_sent,
            'failed': today_failed,
        },
    })


# ---------------------------------------------------------------------------
# Per-domain send stats (emails sent grouped by sender domain)
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming/domain-stats', methods=['GET'])
@login_required
def email_grooming_domain_stats():
    # Extract domain from from_address (everything after '@')
    sender_domain = func.split_part(EmailGroomingLog.from_address, '@', 2)

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Scope to active project's domains
    allowed_ids = _project_domain_ids()
    allowed_config_ids = None
    if allowed_ids is not None:
        allowed_config_ids = {c.id for c in EmailGroomingConfig.query.filter(
            EmailGroomingConfig.domain_id.in_(allowed_ids)
        ).with_entities(EmailGroomingConfig.id).all()} if allowed_ids else set()

    # Exclude rows with missing/malformed from_address (would produce blank-domain ghost row)
    valid_sender = EmailGroomingLog.from_address.isnot(None) & EmailGroomingLog.from_address.like('%@%')

    # Total counts per sender domain
    total_q = db.session.query(
        sender_domain.label('domain'),
        func.count().label('total'),
        func.sum(db.case((EmailGroomingLog.success == True, 1), else_=0)).label('success'),
        func.sum(db.case((EmailGroomingLog.success == False, 1), else_=0)).label('failed'),
    ).filter(valid_sender)
    if allowed_config_ids is not None:
        total_q = total_q.filter(EmailGroomingLog.config_id.in_(allowed_config_ids)) if allowed_config_ids else total_q.filter(db.false())
    total_rows = total_q.group_by(sender_domain).order_by(func.count().desc()).all()

    # Today's counts per sender domain
    today_q = db.session.query(
        sender_domain.label('domain'),
        func.count().label('total'),
        func.sum(db.case((EmailGroomingLog.success == True, 1), else_=0)).label('success'),
        func.sum(db.case((EmailGroomingLog.success == False, 1), else_=0)).label('failed'),
    ).filter(valid_sender, EmailGroomingLog.sent_at >= today_start)
    if allowed_config_ids is not None:
        today_q = today_q.filter(EmailGroomingLog.config_id.in_(allowed_config_ids)) if allowed_config_ids else today_q.filter(db.false())
    today_rows = today_q.group_by(sender_domain).order_by(func.count().desc()).all()

    today_map = {r.domain: {'total': r.total, 'success': int(r.success or 0), 'failed': int(r.failed or 0)} for r in today_rows}

    domains = []
    for r in total_rows:
        today = today_map.get(r.domain, {'total': 0, 'success': 0, 'failed': 0})
        domains.append({
            'domain': r.domain,
            'total': r.total,
            'success': int(r.success or 0),
            'failed': int(r.failed or 0),
            'today_total': today['total'],
            'today_success': today['success'],
            'today_failed': today['failed'],
        })

    return jsonify({'domains': domains})
