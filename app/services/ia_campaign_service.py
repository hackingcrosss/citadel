"""ia_campaign_service.py — Campaign lifecycle for initial access operations.

Handles campaign CRUD, GoPhish orchestration, RoE enforcement,
event syncing, and denormalized stat updates.
"""

import json
import logging
from datetime import datetime

from app import db
from app.models.ia_campaign import IACampaign, ia_campaign_targets
from app.models.ia_campaign_event import IACampaignEvent
from app.models.ia_target import IATarget
from app.services import gophish_service

_log = logging.getLogger(__name__)

_VALID_VECTORS = {'phishing', 'vishing', 'smishing'}
_VALID_STATUSES = {'draft', 'active', 'paused', 'completed', 'archived'}
_EDITABLE_FIELDS = {'name', 'vector', 'domain_id', 'gophish_smtp_id',
                    'landing_page_id', 'email_template_id', 'phishing_url',
                    'scheduled_start', 'scheduled_end', 'roe_enforced'}


# ── CRUD ────────────────────────────────────────────────────────────────

def list_campaigns(project_id, status=None):
    q = IACampaign.query.filter_by(project_id=project_id)
    if status:
        q = q.filter_by(status=status)
    return q.order_by(IACampaign.created_at.desc()).all()


def get_campaign(campaign_id):
    return IACampaign.query.get(campaign_id)


def create_campaign(project_id, data, user_id):
    vector = data.get('vector', 'phishing')
    if vector not in _VALID_VECTORS:
        raise ValueError(f'Invalid vector: {vector}')

    campaign = IACampaign(
        project_id=project_id,
        name=data['name'][:200],
        vector=vector,
        status='draft',
        domain_id=data.get('domain_id'),
        email_template_id=data.get('email_template_id'),
        gophish_smtp_id=data.get('gophish_smtp_id'),
        landing_page_id=data.get('landing_page_id'),
        phishing_url=data.get('phishing_url', ''),
        roe_enforced=data.get('roe_enforced', True),
        created_by_id=user_id,
    )

    # Parse schedule dates
    for field in ('scheduled_start', 'scheduled_end'):
        val = data.get(field)
        if val:
            try:
                setattr(campaign, field, datetime.fromisoformat(val))
            except (ValueError, TypeError):
                pass

    db.session.add(campaign)
    db.session.commit()
    return campaign


def update_campaign(campaign, data):
    if campaign.status not in ('draft', 'paused'):
        raise ValueError('Can only edit campaigns in draft or paused status')

    for field in _EDITABLE_FIELDS:
        if field not in data:
            continue
        val = data[field]
        if field == 'vector' and val not in _VALID_VECTORS:
            raise ValueError(f'Invalid vector: {val}')
        if field in ('scheduled_start', 'scheduled_end') and isinstance(val, str):
            try:
                val = datetime.fromisoformat(val)
            except (ValueError, TypeError):
                continue
        if field == 'name' and val:
            val = str(val)[:200]
        if field == 'phishing_url' and val:
            val = str(val)[:500]
        setattr(campaign, field, val)

    campaign.updated_at = datetime.utcnow()
    db.session.commit()
    return campaign


def archive_campaign(campaign):
    campaign.status = 'archived'
    campaign.updated_at = datetime.utcnow()
    db.session.commit()
    return campaign


# ── Target management ───────────────────────────────────────────────────

def add_targets(campaign, target_ids):
    """Add targets to a campaign. Returns count of newly added."""
    existing = {t.id for t in campaign.targets.all()}
    added = 0
    for tid in target_ids:
        if tid in existing:
            continue
        target = IATarget.query.get(tid)
        if target and target.project_id == campaign.project_id:
            campaign.targets.append(target)
            added += 1
    campaign.targets_count = campaign.targets.count()
    db.session.commit()
    return added


def remove_target(campaign, target_id):
    target = IATarget.query.get(target_id)
    if target and target in campaign.targets.all():
        campaign.targets.remove(target)
        campaign.targets_count = campaign.targets.count()
        db.session.commit()
        return True
    return False


# ── RoE check ───────────────────────────────────────────────────────────

def check_roe(campaign):
    """Check if the campaign can launch given RoE constraints.

    Returns (ok: bool, reason: str|None).
    """
    if not campaign.roe_enforced:
        return True, None

    from app.models.project import Project
    project = Project.query.get(campaign.project_id)
    if not project or not project.company:
        return True, None  # No company = no RoE constraints

    company = project.company
    if company.allowed_hours:
        # allowed_hours is a free-form string like "Mon-Fri 09:00-17:00 UTC"
        # For now, just check it exists and warn — full parsing is future work
        _log.info('RoE allowed hours for campaign %s: %s', campaign.id, company.allowed_hours)

    return True, None


# ── GoPhish launch ──────────────────────────────────────────────────────

def launch_campaign(campaign):
    """Orchestrate launching a phishing campaign through GoPhish.

    Steps:
    1. Validate campaign has targets, domain, SMTP profile
    2. Check RoE
    3. Create GoPhish group from campaign targets
    4. Create GoPhish campaign
    5. Update local campaign status + GoPhish IDs
    """
    if campaign.status not in ('draft', 'paused'):
        raise ValueError(f'Cannot launch campaign in {campaign.status} status')

    if campaign.vector != 'phishing':
        raise ValueError('GoPhish launch only supports phishing vector')

    targets_list = campaign.targets.all()
    if not targets_list:
        raise ValueError('Campaign has no targets')

    if not campaign.gophish_smtp_id:
        raise ValueError('No GoPhish sending profile configured')

    # RoE check
    ok, reason = check_roe(campaign)
    if not ok:
        raise ValueError(f'RoE violation: {reason}')

    # Resolve template — linked or fallback to Citadel Grooming
    gp_template_name = 'Citadel Grooming'
    reuse_group = None

    if campaign.email_template_id:
        from app.models.ia_email_template import IAEmailTemplate
        tpl = IAEmailTemplate.query.get(campaign.email_template_id)
        if not tpl or not tpl.gophish_template_id:
            raise ValueError('Linked email template has not been pushed to GoPhish')
        gp_tpl = gophish_service.get_template(tpl.gophish_template_id)
        gp_template_name = gp_tpl['name']
        if tpl.gophish_group_id:
            reuse_group = gophish_service.get_group(tpl.gophish_group_id)

    # Build or reuse GoPhish target group
    if reuse_group:
        gp_group = reuse_group
    else:
        gp_targets = []
        for t in targets_list:
            if not t.email:
                continue
            gp_targets.append({
                'first_name': t.first_name or '',
                'last_name': t.last_name or '',
                'email': t.email,
                'position': t.job_title or '',
            })

        if not gp_targets:
            raise ValueError('No targets with valid email addresses')

        group_name = f'Citadel_{campaign.project_id}_{campaign.id}_{int(datetime.utcnow().timestamp())}'
        gp_group = gophish_service.create_group({
            'name': group_name,
            'targets': gp_targets,
        })

    # Get the sending profile
    smtp_profile = gophish_service.get_sending_profile(campaign.gophish_smtp_id)

    # Build campaign payload
    gp_payload = {
        'name': f'Citadel: {campaign.name[:150]}',
        'smtp': smtp_profile,
        'groups': [{'name': gp_group['name']}],
        'template': {'name': gp_template_name},
        'page': {'name': 'Blank', 'html': '<html><body></body></html>'},
        'url': campaign.phishing_url or '',
    }

    if campaign.scheduled_start:
        gp_payload['launch_date'] = campaign.scheduled_start.strftime('%Y-%m-%dT%H:%M:%S+00:00')
    if campaign.scheduled_end:
        gp_payload['send_by_date'] = campaign.scheduled_end.strftime('%Y-%m-%dT%H:%M:%S+00:00')

    gp_campaign = gophish_service.create_campaign(gp_payload)

    campaign.gophish_campaign_id = gp_campaign.get('id')
    campaign.status = 'active'
    campaign.updated_at = datetime.utcnow()
    db.session.commit()

    _log.info('Launched campaign %s as GoPhish campaign %s', campaign.id, campaign.gophish_campaign_id)
    return campaign


# ── Reschedule active campaign ─────────────────────────────────────────

def reschedule_campaign(campaign, scheduled_start, scheduled_end=None):
    """Reschedule an active/queued GoPhish campaign.

    Deletes the existing GoPhish campaign, updates the schedule,
    then re-launches with the new dates.
    """
    if campaign.status != 'active':
        raise ValueError('Can only reschedule active campaigns')
    if not campaign.gophish_campaign_id:
        raise ValueError('Campaign has no GoPhish campaign to reschedule')

    if isinstance(scheduled_start, str):
        scheduled_start = datetime.fromisoformat(scheduled_start)
    if isinstance(scheduled_end, str):
        scheduled_end = datetime.fromisoformat(scheduled_end)

    gp_id = campaign.gophish_campaign_id

    gophish_service.complete_campaign(gp_id)
    gophish_service.delete_campaign(gp_id)

    campaign.gophish_campaign_id = None
    campaign.scheduled_start = scheduled_start
    if scheduled_end is not None:
        campaign.scheduled_end = scheduled_end
    campaign.status = 'paused'
    campaign.updated_at = datetime.utcnow()
    db.session.commit()

    return launch_campaign(campaign)


# ── Event sync from GoPhish ─────────────────────────────────────────────

_EVENT_TYPE_MAP = {
    'Email Sent': 'email_sent',
    'Email Opened': 'open',
    'Clicked Link': 'click',
    'Submitted Data': 'cred_capture',
}


def sync_campaign_events(campaign):
    """Pull events from GoPhish and merge into local event log.

    Returns count of new events created.
    """
    if not campaign.gophish_campaign_id:
        return 0

    try:
        gp_data = gophish_service.get_campaign(campaign.gophish_campaign_id)
    except Exception as e:
        _log.warning('Failed to fetch GoPhish campaign %s: %s', campaign.gophish_campaign_id, e)
        return 0

    gp_results = gp_data.get('results', [])
    gp_timeline = gp_data.get('timeline', [])
    gp_status = gp_data.get('status', '')

    # Build email -> target_id map
    target_map = {}
    for t in campaign.targets.all():
        if t.email:
            target_map[t.email.lower()] = t.id

    # Get existing event fingerprints to deduplicate
    existing = set()
    for ev in campaign.events:
        existing.add((ev.event_type, ev.target_id, ev.occurred_at.isoformat() if ev.occurred_at else ''))

    new_count = 0
    for entry in gp_timeline:
        event_type = _EVENT_TYPE_MAP.get(entry.get('message'))
        if not event_type:
            continue

        email = (entry.get('email') or '').lower()
        target_id = target_map.get(email)
        occurred_at = None
        if entry.get('time'):
            try:
                ts = entry['time']
                if isinstance(ts, str):
                    occurred_at = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                occurred_at = datetime.utcnow()

        fingerprint = (event_type, target_id, occurred_at.isoformat() if occurred_at else '')
        if fingerprint in existing:
            continue

        event = IACampaignEvent(
            campaign_id=campaign.id,
            target_id=target_id,
            event_type=event_type,
            occurred_at=occurred_at or datetime.utcnow(),
            source='gophish',
            raw_data=json.dumps(entry),
            ip_address=entry.get('details', {}).get('browser', {}).get('address') if isinstance(entry.get('details'), dict) else None,
            user_agent=entry.get('details', {}).get('browser', {}).get('user-agent') if isinstance(entry.get('details'), dict) else None,
        )
        db.session.add(event)
        existing.add(fingerprint)
        new_count += 1

    # Update denormalized stats
    _update_campaign_stats(campaign)

    # Sync GoPhish status
    if gp_status == 'Completed' and campaign.status == 'active':
        campaign.status = 'completed'

    campaign.updated_at = datetime.utcnow()
    db.session.commit()

    return new_count


def _update_campaign_stats(campaign):
    """Recalculate denormalized stat counters from events."""
    from sqlalchemy import func
    counts = (
        db.session.query(IACampaignEvent.event_type, func.count(IACampaignEvent.id))
        .filter_by(campaign_id=campaign.id)
        .group_by(IACampaignEvent.event_type)
        .all()
    )
    count_map = dict(counts)
    campaign.emails_sent = count_map.get('email_sent', 0)
    campaign.opens_count = count_map.get('open', 0)
    campaign.clicks_count = count_map.get('click', 0)
    campaign.creds_captured = count_map.get('cred_capture', 0)
    campaign.payloads_executed = count_map.get('payload_exec', 0)
    campaign.targets_count = campaign.targets.count()


# ── Manual event logging (vishing/smishing) ─────────────────────────────

_MANUAL_EVENT_TYPES = {'vishing_attempt', 'vishing_success', 'sms_sent', 'sms_click',
                       'email_sent', 'open', 'click', 'cred_capture', 'payload_exec'}


def log_manual_event(campaign, data):
    """Log a manual event (vishing, smishing, etc.)."""
    event_type = data.get('event_type')
    if event_type not in _MANUAL_EVENT_TYPES:
        raise ValueError(f'Invalid event type: {event_type}')

    target_id = data.get('target_id')
    if target_id:
        target = IATarget.query.get(target_id)
        if not target or target.project_id != campaign.project_id:
            raise ValueError('Target not found in project')

    event = IACampaignEvent(
        campaign_id=campaign.id,
        target_id=target_id,
        event_type=event_type,
        occurred_at=datetime.utcnow(),
        source='manual',
        ip_address=data.get('ip_address'),
        notes=data.get('notes', '')[:1000] if data.get('notes') else None,
    )
    db.session.add(event)
    _update_campaign_stats(campaign)
    db.session.commit()
    return event


# ── Sync all active campaigns ───────────────────────────────────────────

def sync_all_active_campaigns():
    """Sync events for all active campaigns. Called by Celery beat."""
    active = IACampaign.query.filter_by(status='active').all()
    total = 0
    for c in active:
        if c.gophish_campaign_id:
            try:
                total += sync_campaign_events(c)
            except Exception as e:
                _log.warning('Failed to sync campaign %s: %s', c.id, e)
    return total


# ── Sender domain recommendation ────────────────────────────────────────

def get_eligible_domains(project_id):
    """Return phishing-ready domains checked out to the project.

    Only includes domains that have at least one GoPhish sending profile
    configured (which implies Mailgun SMTP is set up for the domain).
    """
    from app.models.domain import Domain

    domains = Domain.query.filter_by(
        checkout_project_id=project_id,
    ).all()

    result = []
    for d in domains:
        profiles = gophish_service.find_all_profiles_for_domain(d.name)
        if not profiles:
            continue
        result.append({
            'domain_id': d.id,
            'domain_name': d.name,
            'has_smtp_profile': True,
            'smtp_profiles': [{'id': p['id'], 'name': p['name']} for p in profiles],
            'status': d.status,
        })

    return result
