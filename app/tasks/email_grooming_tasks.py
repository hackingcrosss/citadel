import logging
import random
from datetime import datetime, timedelta

from app.tasks.celery_app import celery

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Warm-up email content templates
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Subject lines: plain, human, no caps/punctuation spam, no marketing jargon.
# Written as a real colleague would write to another colleague.
# ---------------------------------------------------------------------------

_SUBJECTS = [
    'Quick question about the project timeline',
    'Following up on our conversation',
    'Notes from today\'s meeting',
    'Updated schedule - would appreciate your input',
    'Re: Document review',
    'Room booked for Thursday',
    'Draft report ready for your review',
    'Lunch plans this Friday',
    'Checking in on deliverables',
    'Updated travel policy - heads up',
    'Weekly planning session agenda',
    'Re: Budget discussion',
    'Working remotely next week',
    'Revised project plan attached',
    'Thanks for getting back to me so quickly',
    'Training deadline coming up',
    'Agenda for tomorrow',
    'Re: Vendor proposal feedback',
    'New team member starting Monday',
    'Re: Presentation slides',
    'Expense reports due this week',
    'Office hours over the holidays',
    'Thoughts on the proposal?',
    'Yesterday\'s action items',
    'Re: Quarterly review',
    'Status update - everything on track',
    'Feedback from the client meeting',
    'Planning for next quarter',
    'Re: Contract review',
    'Confirming our call tomorrow',
]

# ---------------------------------------------------------------------------
# Email bodies: clean minimal HTML, inline CSS, text-heavy, no images,
# no links, no tracking pixels, no marketing language. Reads like a real
# person typing in Outlook/Gmail. Each includes {signature} and {text_body}
# placeholders. Bodies encourage replies to drive engagement signals.
# ---------------------------------------------------------------------------

_EMAIL_TEMPLATES = [
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>I wanted to follow up on our conversation from last week about the project timeline. '
                'Have you had a chance to look at the updated milestones? I need to send the revised dates '
                'to the steering committee by Friday, so any input you have before then would be really helpful.</p>'
                '<p>Let me know if you want to jump on a quick call to go through it together.</p>'
                '<p>Thanks,<br>{signature}</p></div>',
        'text': 'Hi,\n\nI wanted to follow up on our conversation from last week about the project timeline. '
                'Have you had a chance to look at the updated milestones? I need to send the revised dates '
                'to the steering committee by Friday, so any input you have before then would be really helpful.\n\n'
                'Let me know if you want to jump on a quick call to go through it together.\n\nThanks,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hello,</p>'
                '<p>Here is a quick summary from today\'s meeting. Let me know if I missed anything:</p>'
                '<p>- Budget for Q4 has been confirmed<br>'
                '- Deadline moved to the 28th<br>'
                '- We will regroup next Wednesday to review progress</p>'
                '<p>If any of this doesn\'t match your notes, just reply and I\'ll correct the record.</p>'
                '<p>Kind regards,<br>{signature}</p></div>',
        'text': 'Hello,\n\nHere is a quick summary from today\'s meeting. Let me know if I missed anything:\n\n'
                '- Budget for Q4 has been confirmed\n'
                '- Deadline moved to the 28th\n'
                '- We will regroup next Wednesday to review progress\n\n'
                'If any of this doesn\'t match your notes, just reply and I\'ll correct the record.\n\n'
                'Kind regards,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Good morning,</p>'
                '<p>Just a reminder that the quarterly report sections are due by end of this week. '
                'If you have already submitted yours, thanks. If not, please try to get it in before Friday '
                'so I can compile everything over the weekend.</p>'
                '<p>Let me know if you have any questions about the format or what is expected.</p>'
                '<p>Thank you,<br>{signature}</p></div>',
        'text': 'Good morning,\n\nJust a reminder that the quarterly report sections are due by end of this week. '
                'If you have already submitted yours, thanks. If not, please try to get it in before Friday '
                'so I can compile everything over the weekend.\n\n'
                'Let me know if you have any questions about the format or what is expected.\n\nThank you,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>I went through the updated schedule and noticed a few changes I wanted to flag:</p>'
                '<p>The integration work has been pushed to the 15th, and the testing window was extended by a week. '
                'The go-live date stays the same for now.</p>'
                '<p>Does that work for your team? Happy to discuss if you see any issues.</p>'
                '<p>Regards,<br>{signature}</p></div>',
        'text': 'Hi,\n\nI went through the updated schedule and noticed a few changes I wanted to flag:\n\n'
                'The integration work has been pushed to the 15th, and the testing window was extended by a week. '
                'The go-live date stays the same for now.\n\n'
                'Does that work for your team? Happy to discuss if you see any issues.\n\nRegards,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hello,</p>'
                '<p>Thank you for sharing the document. I read through it and it looks solid overall. '
                'I have a couple of small suggestions for the summary section that I think would make it '
                'a bit clearer for the executive audience.</p>'
                '<p>Would it work to have a short call tomorrow afternoon? I am open between 2 and 4.</p>'
                '<p>Best regards,<br>{signature}</p></div>',
        'text': 'Hello,\n\nThank you for sharing the document. I read through it and it looks solid overall. '
                'I have a couple of small suggestions for the summary section that I think would make it '
                'a bit clearer for the executive audience.\n\n'
                'Would it work to have a short call tomorrow afternoon? I am open between 2 and 4.\n\n'
                'Best regards,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>Just confirming we are still on for tomorrow at 2 PM. I will send the dial-in details '
                'this afternoon.</p>'
                '<p>If you get a chance, it would be helpful to review the briefing notes I circulated last week '
                'so we are all on the same page going in.</p>'
                '<p>See you then,<br>{signature}</p></div>',
        'text': 'Hi,\n\nJust confirming we are still on for tomorrow at 2 PM. I will send the dial-in details '
                'this afternoon.\n\n'
                'If you get a chance, it would be helpful to review the briefing notes I circulated last week '
                'so we are all on the same page going in.\n\nSee you then,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>Quick update on where things stand this week:</p>'
                '<p>The API work and database migration are on track. Frontend redesign is almost done. '
                'We are still waiting on vendor access, which I escalated yesterday.</p>'
                '<p>I will have more detail at tomorrow\'s standup. Let me know if anything comes up before then.</p>'
                '<p>Thanks,<br>{signature}</p></div>',
        'text': 'Hi,\n\nQuick update on where things stand this week:\n\n'
                'The API work and database migration are on track. Frontend redesign is almost done. '
                'We are still waiting on vendor access, which I escalated yesterday.\n\n'
                'I will have more detail at tomorrow\'s standup. Let me know if anything comes up before then.\n\n'
                'Thanks,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hello,</p>'
                '<p>Writing to confirm the training session next Tuesday at 10 AM. We should have everything '
                'set up, but I need a final headcount by Friday for the room and catering.</p>'
                '<p>Could you reply to confirm whether you are attending? It would really help with the planning.</p>'
                '<p>Thanks,<br>{signature}</p></div>',
        'text': 'Hello,\n\nWriting to confirm the training session next Tuesday at 10 AM. We should have everything '
                'set up, but I need a final headcount by Friday for the room and catering.\n\n'
                'Could you reply to confirm whether you are attending? It would really help with the planning.\n\n'
                'Thanks,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Good afternoon,</p>'
                '<p>Following up on the action items from last week. The contract review and pricing comparison '
                'are both done. The impact assessment is still in progress and the final recommendation '
                'should be ready by Thursday.</p>'
                '<p>I will send it around as soon as it is finalized. Reach out if you have any questions.</p>'
                '<p>Best regards,<br>{signature}</p></div>',
        'text': 'Good afternoon,\n\nFollowing up on the action items from last week. The contract review and pricing '
                'comparison are both done. The impact assessment is still in progress and the final recommendation '
                'should be ready by Thursday.\n\n'
                'I will send it around as soon as it is finalized. Reach out if you have any questions.\n\n'
                'Best regards,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>Heads up that the updated security policy takes effect next Monday. The main changes are '
                'around password requirements and device enrollment. I put a summary in the shared folder '
                'if you want to take a look.</p>'
                '<p>Let me know if anything is unclear or if you have questions about what it means for our team.</p>'
                '<p>Thanks,<br>{signature}</p></div>',
        'text': 'Hi,\n\nHeads up that the updated security policy takes effect next Monday. The main changes are '
                'around password requirements and device enrollment. I put a summary in the shared folder '
                'if you want to take a look.\n\n'
                'Let me know if anything is unclear or if you have questions about what it means for our team.\n\n'
                'Thanks,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hello,</p>'
                '<p>Have you had a chance to look at the vendor proposal I forwarded last week? '
                'The evaluation group meets on Thursday and it would be great to have your thoughts before then.</p>'
                '<p>Even a quick read and your general impression would be helpful. No need for a full write-up.</p>'
                '<p>Appreciate it,<br>{signature}</p></div>',
        'text': 'Hello,\n\nHave you had a chance to look at the vendor proposal I forwarded last week? '
                'The evaluation group meets on Thursday and it would be great to have your thoughts before then.\n\n'
                'Even a quick read and your general impression would be helpful. No need for a full write-up.\n\n'
                'Appreciate it,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>I will be working from home tomorrow and Thursday. You can reach me by email or on Teams '
                'during normal hours. All meetings will go ahead as scheduled over video.</p>'
                '<p>If something urgent comes up, feel free to give me a call.</p>'
                '<p>Best,<br>{signature}</p></div>',
        'text': 'Hi,\n\nI will be working from home tomorrow and Thursday. You can reach me by email or on Teams '
                'during normal hours. All meetings will go ahead as scheduled over video.\n\n'
                'If something urgent comes up, feel free to give me a call.\n\nBest,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Good morning,</p>'
                '<p>The vendor came back with updated pricing. It looks reasonable and addresses most of what '
                'we raised in the last round. I think we should review it together before responding.</p>'
                '<p>Do you have 15 or 20 minutes this afternoon for a quick call?</p>'
                '<p>Regards,<br>{signature}</p></div>',
        'text': 'Good morning,\n\nThe vendor came back with updated pricing. It looks reasonable and addresses most of '
                'what we raised in the last round. I think we should review it together before responding.\n\n'
                'Do you have 15 or 20 minutes this afternoon for a quick call?\n\nRegards,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>Wanted to say thanks for the work on the analysis report. It was well put together and '
                'the leadership team was impressed with the level of detail. I already got positive feedback '
                'from a few people.</p>'
                '<p>I have sent the final version over to the executive committee for their review.</p>'
                '<p>Great job on this,<br>{signature}</p></div>',
        'text': 'Hi,\n\nWanted to say thanks for the work on the analysis report. It was well put together and '
                'the leadership team was impressed with the level of detail. I already got positive feedback '
                'from a few people.\n\n'
                'I have sent the final version over to the executive committee for their review.\n\n'
                'Great job on this,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hello,</p>'
                '<p>Reminder about the team gathering next Friday from noon to 3 PM. Lunch will be covered.</p>'
                '<p>Could you reply by Wednesday to let me know if you are coming? I need to finalize the '
                'headcount for the venue. If you have any dietary needs, include that in your reply.</p>'
                '<p>Looking forward to it,<br>{signature}</p></div>',
        'text': 'Hello,\n\nReminder about the team gathering next Friday from noon to 3 PM. Lunch will be covered.\n\n'
                'Could you reply by Wednesday to let me know if you are coming? I need to finalize the '
                'headcount for the venue. If you have any dietary needs, include that in your reply.\n\n'
                'Looking forward to it,\n{text_sig}',
    },
]

_FIRST_NAMES = [
    'Alexander', 'Benjamin', 'Charlotte', 'Daniel', 'Elizabeth', 'Frederick',
    'Grace', 'Harrison', 'Isabella', 'Jonathan', 'Katherine', 'Lawrence',
    'Margaret', 'Nicholas', 'Olivia', 'Patricia', 'Robert', 'Sophia',
    'Thomas', 'Victoria', 'William', 'Abigail', 'Christopher', 'Eleanor',
]
_LAST_NAMES = [
    'Anderson', 'Bennett', 'Campbell', 'Davidson', 'Edwards', 'Fletcher',
    'Graham', 'Harrison', 'Ingram', 'Jenkins', 'Keller', 'Lambert',
    'Mitchell', 'Nelson', 'O\'Brien', 'Parker', 'Reynolds', 'Stewart',
    'Thompson', 'Wallace', 'Crawford', 'Morrison', 'Henderson', 'Sullivan',
]
_TITLES = [
    'Project Manager', 'Senior Analyst', 'Operations Coordinator',
    'Account Manager', 'Business Development Lead', 'Program Director',
    'Strategy Consultant', 'Client Relations Manager', 'Team Lead',
    'Communications Specialist', 'Planning Manager', 'Research Analyst',
]


def _build_signature(first, last, title, from_address):
    """Build a professional email signature block (HTML)."""
    return (
        f'<strong>{first} {last}</strong><br>'
        f'<span style="color:#666;font-size:12px;">{title}</span><br>'
        f'<span style="color:#666;font-size:12px;">{from_address}</span>'
    )


def _build_text_sig(first, last, title, from_address):
    """Build a plain-text email signature."""
    return f'{first} {last}\n{title}\n{from_address}'


def _generate_email_content(used_subjects, from_address=''):
    """Return (subject, html_body, text_body, first_name, last_name) for a warm-up email.
    Avoids subjects already used (per-target dedup).
    Both HTML and plain text parts are returned for proper MIME multipart."""
    available = [s for s in _SUBJECTS if s not in used_subjects]
    if not available:
        available = list(_SUBJECTS)
    subject = random.choice(available)
    first = random.choice(_FIRST_NAMES)
    last = random.choice(_LAST_NAMES)
    title = random.choice(_TITLES)
    sig_html = _build_signature(first, last, title, from_address)
    sig_text = _build_text_sig(first, last, title, from_address)
    tpl = random.choice(_EMAIL_TEMPLATES)
    html = tpl['html'].replace('{signature}', sig_html)
    text = tpl['text'].replace('{text_sig}', sig_text)
    return subject, html, text, first, last


def _pick_profile(config, all_profiles_for_domain, gophish_service):
    """Select a GoPhish sending profile for a config.

    If config.gophish_profile_id is set, use that specific profile.
    Otherwise rotate across all matching profiles for the domain.
    """
    if config.gophish_profile_id:
        for p in all_profiles_for_domain:
            if p.get('id') == config.gophish_profile_id:
                return p
        # Pinned profile not found among domain matches — try fetching it directly
        try:
            return gophish_service.get_sending_profile(config.gophish_profile_id)
        except Exception:
            return None

    if not all_profiles_for_domain:
        return None

    # Rotate: pick based on config.emails_sent so each cycle advances
    idx = (config.emails_sent or 0) % len(all_profiles_for_domain)
    return all_profiles_for_domain[idx]


def _get_recent_subjects(config_id, EmailGroomingLog):
    """Return set of subjects sent to this config in the last 7 days."""
    cutoff = datetime.utcnow() - timedelta(days=7)
    rows = EmailGroomingLog.query.filter(
        EmailGroomingLog.config_id == config_id,
        EmailGroomingLog.sent_at >= cutoff,
        EmailGroomingLog.success == True,  # noqa: E712
    ).with_entities(EmailGroomingLog.subject).all()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Celery periodic task — process all active grooming configs
# ---------------------------------------------------------------------------

@celery.task(bind=True, max_retries=0, time_limit=300, soft_time_limit=280)
def process_email_grooming(self):
    """Process all active email grooming configs and send emails where due.

    For each active config:
      1. Count how many emails were sent today.
      2. If below the daily limit, send one email via GoPhish.
      3. Log the result in EmailGroomingLog.
      4. Update the config's emails_sent and last_sent_at.

    This task is designed to run every 30 minutes via Celery beat.
    """
    from app import db
    from app.models.email_grooming import EmailGroomingConfig
    from app.models.email_grooming_log import EmailGroomingLog
    from app.services import gophish_service

    configs = EmailGroomingConfig.query.filter_by(status='active').all()
    if not configs:
        _log.debug('No active email grooming configs')
        return {'processed': 0, 'sent': 0, 'errors': 0}

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_count = 0
    error_count = 0
    processed = 0

    # Cache all GoPhish profiles per domain (for rotation)
    _profiles_cache = {}  # domain_name -> list of profiles

    for config in configs:
        processed += 1
        domain = config.domain
        if not domain:
            _log.warning('Grooming config %d has no domain, skipping', config.id)
            continue

        # Count emails sent today for this config
        today_sent = EmailGroomingLog.query.filter(
            EmailGroomingLog.config_id == config.id,
            EmailGroomingLog.sent_at >= today_start,
            EmailGroomingLog.success == True,  # noqa: E712
        ).count()

        if today_sent >= config.emails_per_day:
            _log.debug('Config %d: %d/%d sent today, skipping',
                       config.id, today_sent, config.emails_per_day)
            continue

        # Check spacing: don't send more than one per interval
        interval_minutes = (24 * 60) / config.emails_per_day
        if config.last_sent_at:
            minutes_since = (datetime.utcnow() - config.last_sent_at).total_seconds() / 60
            if minutes_since < interval_minutes * 0.8:
                _log.debug('Config %d: last sent %.0fm ago, interval is %.0fm, skipping',
                           config.id, minutes_since, interval_minutes)
                continue

        # Fetch all matching profiles for this domain (cached)
        domain_name = domain.name
        if domain_name not in _profiles_cache:
            try:
                _profiles_cache[domain_name] = gophish_service.find_all_profiles_for_domain(domain_name)
            except Exception as exc:
                _log.error('Failed to fetch GoPhish profiles for %s: %s', domain_name, exc)
                _profiles_cache[domain_name] = []

        all_profiles = _profiles_cache[domain_name]
        profile = _pick_profile(config, all_profiles, gophish_service)

        if not profile:
            _log.warning('No GoPhish sending profile found for domain %s (config %d, pinned=%s)',
                         domain_name, config.id, config.gophish_profile_id)
            log_entry = EmailGroomingLog(
                config_id=config.id,
                from_address='?',
                to_address=config.target_email,
                subject='(no profile)',
                success=False,
                error_message=f'No GoPhish sending profile found for domain {domain_name}',
            )
            db.session.add(log_entry)
            error_count += 1
            continue

        # Generate email content with subject deduplication
        from_address = profile.get('from_address', f'noreply@{domain_name}')
        used_subjects = _get_recent_subjects(config.id, EmailGroomingLog)
        subject, html_body, text_body, first_name, last_name = _generate_email_content(used_subjects, from_address)
        envelope_sender = f'{first_name} {last_name} <{from_address}>'

        # Send via GoPhish
        try:
            gophish_service.send_test_email(
                smtp_profile=profile,
                to_email=config.target_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                from_first=first_name,
                from_last=last_name,
                envelope_sender=envelope_sender,
            )
            log_entry = EmailGroomingLog(
                config_id=config.id,
                from_address=from_address,
                to_address=config.target_email,
                subject=subject,
                success=True,
                gophish_profile_id=profile.get('id'),
            )
            db.session.add(log_entry)
            config.emails_sent = (config.emails_sent or 0) + 1
            config.last_sent_at = datetime.utcnow()
            sent_count += 1
            _log.info('Sent grooming email: %s -> %s [%s] (profile #%s)',
                      from_address, config.target_email, subject, profile.get('id'))

        except Exception as exc:
            _log.error('Failed to send grooming email for config %d: %s', config.id, exc)
            log_entry = EmailGroomingLog(
                config_id=config.id,
                from_address=from_address,
                to_address=config.target_email,
                subject=subject,
                success=False,
                error_message=str(exc)[:500],
                gophish_profile_id=profile.get('id'),
            )
            db.session.add(log_entry)
            error_count += 1

    db.session.commit()
    _log.info('Email grooming cycle complete: processed=%d sent=%d errors=%d',
              processed, sent_count, error_count)
    return {'processed': processed, 'sent': sent_count, 'errors': error_count}


@celery.task(bind=True, max_retries=0, time_limit=60, soft_time_limit=50)
def send_grooming_email_now(self, config_id):
    """Send a single grooming email immediately for a specific config (manual trigger)."""
    from app import db
    from app.models.email_grooming import EmailGroomingConfig
    from app.models.email_grooming_log import EmailGroomingLog
    from app.services import gophish_service

    config = EmailGroomingConfig.query.get(config_id)
    if not config:
        return {'error': 'Config not found'}

    domain = config.domain
    if not domain:
        return {'error': 'Domain not found'}

    all_profiles = gophish_service.find_all_profiles_for_domain(domain.name)
    profile = _pick_profile(config, all_profiles, gophish_service)
    if not profile:
        return {'error': f'No GoPhish sending profile found for domain {domain.name}'}

    from_address = profile.get('from_address', f'noreply@{domain.name}')
    used_subjects = _get_recent_subjects(config.id, EmailGroomingLog)
    subject, html_body, text_body, first_name, last_name = _generate_email_content(used_subjects, from_address)
    envelope_sender = f'{first_name} {last_name} <{from_address}>'

    try:
        gophish_service.send_test_email(
            smtp_profile=profile,
            to_email=config.target_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            from_first=first_name,
            from_last=last_name,
            envelope_sender=envelope_sender,
        )
        log_entry = EmailGroomingLog(
            config_id=config.id,
            from_address=from_address,
            to_address=config.target_email,
            subject=subject,
            success=True,
            gophish_profile_id=profile.get('id'),
        )
        db.session.add(log_entry)
        config.emails_sent = (config.emails_sent or 0) + 1
        config.last_sent_at = datetime.utcnow()
        db.session.commit()
        _log.info('Manual grooming email sent: %s -> %s [%s]', from_address, config.target_email, subject)
        return {'success': True, 'subject': subject, 'from': from_address, 'to': config.target_email}

    except Exception as exc:
        log_entry = EmailGroomingLog(
            config_id=config.id,
            from_address=from_address,
            to_address=config.target_email,
            subject=subject,
            success=False,
            error_message=str(exc)[:500],
            gophish_profile_id=profile.get('id'),
        )
        db.session.add(log_entry)
        db.session.commit()
        return {'error': str(exc)}
