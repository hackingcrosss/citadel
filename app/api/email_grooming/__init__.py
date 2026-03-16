import re
from flask import request, jsonify
from flask_login import login_required, current_user
from app.api import api_bp
from app import db
from app.models.domain import Domain
from app.models.email_grooming import EmailGroomingConfig

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
_OUTLOOK_DOMAINS = {
    'outlook.com', 'hotmail.com', 'live.com', 'msn.com',
    'outlook.fr', 'outlook.de', 'outlook.co.uk', 'hotmail.co.uk',
    'hotmail.fr', 'hotmail.de', 'live.co.uk', 'live.fr',
}


def _is_outlook(email):
    domain = email.rsplit('@', 1)[-1].lower()
    return domain in _OUTLOOK_DOMAINS


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
    configs = q.order_by(EmailGroomingConfig.created_at.desc()).all()

    # Aggregate stats
    total_configs = len(configs)
    total_sent = sum(c.emails_sent for c in configs)
    active_count = sum(1 for c in configs if c.status == 'active')

    return jsonify({
        'configs': [c.to_dict() for c in configs],
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

    targets = data.get('targets') or []
    if not targets:
        return jsonify({'error': 'At least one target email is required'}), 400

    emails_per_day = data.get('emails_per_day', 10)
    if not isinstance(emails_per_day, int) or emails_per_day < 1 or emails_per_day > 50:
        return jsonify({'error': 'emails_per_day must be between 1 and 50'}), 400

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
    config = EmailGroomingConfig.query.get_or_404(config_id)
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

    db.session.commit()
    return jsonify(config.to_dict())


# ---------------------------------------------------------------------------
# Delete config
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming/<int:config_id>', methods=['DELETE'])
@login_required
def delete_email_grooming(config_id):
    config = EmailGroomingConfig.query.get_or_404(config_id)
    db.session.delete(config)
    db.session.commit()
    return jsonify({'deleted': True})


# ---------------------------------------------------------------------------
# Bulk delete by domain
# ---------------------------------------------------------------------------

@api_bp.route('/email-grooming/domain/<int:domain_id>', methods=['DELETE'])
@login_required
def delete_email_grooming_by_domain(domain_id):
    count = EmailGroomingConfig.query.filter_by(domain_id=domain_id).delete()
    db.session.commit()
    return jsonify({'deleted': count})
