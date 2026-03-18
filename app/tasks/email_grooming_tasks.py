import base64
import logging
import random
import time
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
# Email bodies organised by type: text_only, with_links, with_attachment.
# The grooming cycle alternates between these three types round-robin based
# on the config's emails_sent counter.
#
# {signature} / {text_sig} — signature placeholders
# {domain} — sender domain (used in hyperlink templates)
# ---------------------------------------------------------------------------

_EMAIL_TYPES = ('text_only', 'with_links', 'with_attachment')

_TEMPLATES_TEXT_ONLY = [
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
]

_TEMPLATES_WITH_LINKS = [
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>I uploaded the revised project plan to our shared workspace. You can access it here:</p>'
                '<p><a href="https://{domain}/shared/project-plan" style="color:#0563C1;">https://{domain}/shared/project-plan</a></p>'
                '<p>Let me know if you have trouble accessing it or if you have any feedback.</p>'
                '<p>Thanks,<br>{signature}</p></div>',
        'text': 'Hi,\n\nI uploaded the revised project plan to our shared workspace. You can access it here:\n\n'
                'https://{domain}/shared/project-plan\n\n'
                'Let me know if you have trouble accessing it or if you have any feedback.\n\nThanks,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hello,</p>'
                '<p>The updated onboarding guide is now live on our portal:</p>'
                '<p><a href="https://{domain}/resources/onboarding-guide" style="color:#0563C1;">https://{domain}/resources/onboarding-guide</a></p>'
                '<p>Please take a look when you get a chance and let me know if anything needs updating.</p>'
                '<p>Best regards,<br>{signature}</p></div>',
        'text': 'Hello,\n\nThe updated onboarding guide is now live on our portal:\n\n'
                'https://{domain}/resources/onboarding-guide\n\n'
                'Please take a look when you get a chance and let me know if anything needs updating.\n\n'
                'Best regards,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>Quick note — the expense report form has been updated. New version is available at:</p>'
                '<p><a href="https://{domain}/forms/expense-report" style="color:#0563C1;">https://{domain}/forms/expense-report</a></p>'
                '<p>Please use this one going forward. The old link will redirect automatically.</p>'
                '<p>Regards,<br>{signature}</p></div>',
        'text': 'Hi,\n\nQuick note — the expense report form has been updated. New version is available at:\n\n'
                'https://{domain}/forms/expense-report\n\n'
                'Please use this one going forward. The old link will redirect automatically.\n\nRegards,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Good morning,</p>'
                '<p>I put together a summary of last quarter\'s results. You can view the dashboard here:</p>'
                '<p><a href="https://{domain}/reports/quarterly-review" style="color:#0563C1;">Quarterly Review Dashboard</a></p>'
                '<p>Happy to walk through it if you would like more context on any of the numbers.</p>'
                '<p>Thank you,<br>{signature}</p></div>',
        'text': 'Good morning,\n\nI put together a summary of last quarter\'s results. You can view the dashboard here:\n\n'
                'https://{domain}/reports/quarterly-review\n\n'
                'Happy to walk through it if you would like more context on any of the numbers.\n\nThank you,\n{text_sig}',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hello,</p>'
                '<p>The team calendar for next month has been published. Please review your scheduled slots:</p>'
                '<p><a href="https://{domain}/calendar/team-schedule" style="color:#0563C1;">https://{domain}/calendar/team-schedule</a></p>'
                '<p>If you need to swap any dates, reply to this email and I will update the calendar.</p>'
                '<p>Kind regards,<br>{signature}</p></div>',
        'text': 'Hello,\n\nThe team calendar for next month has been published. Please review your scheduled slots:\n\n'
                'https://{domain}/calendar/team-schedule\n\n'
                'If you need to swap any dates, reply to this email and I will update the calendar.\n\n'
                'Kind regards,\n{text_sig}',
    },
]

_TEMPLATES_WITH_ATTACHMENT = [
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>Please find attached the meeting notes from this morning. I tried to capture '
                'the key decisions and action items. Let me know if I missed anything.</p>'
                '<p>Thanks,<br>{signature}</p></div>',
        'text': 'Hi,\n\nPlease find attached the meeting notes from this morning. I tried to capture '
                'the key decisions and action items. Let me know if I missed anything.\n\nThanks,\n{text_sig}',
        'attachment_type': 'meeting_notes',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hello,</p>'
                '<p>Attached is the updated contact list for the project team. Please check that your '
                'details are correct and let me know if anything needs changing.</p>'
                '<p>Best regards,<br>{signature}</p></div>',
        'text': 'Hello,\n\nAttached is the updated contact list for the project team. Please check that your '
                'details are correct and let me know if anything needs changing.\n\nBest regards,\n{text_sig}',
        'attachment_type': 'contact_list',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>I have attached the agenda for next week\'s planning session. If you have any topics '
                'to add, just reply and I will include them before I send the final version.</p>'
                '<p>Regards,<br>{signature}</p></div>',
        'text': 'Hi,\n\nI have attached the agenda for next week\'s planning session. If you have any topics '
                'to add, just reply and I will include them before I send the final version.\n\nRegards,\n{text_sig}',
        'attachment_type': 'agenda',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Good afternoon,</p>'
                '<p>Here is the calendar invite for the review session on Thursday. I attached it as an ICS '
                'file so you can add it directly to your calendar.</p>'
                '<p>See you there,<br>{signature}</p></div>',
        'text': 'Good afternoon,\n\nHere is the calendar invite for the review session on Thursday. I attached it '
                'as an ICS file so you can add it directly to your calendar.\n\nSee you there,\n{text_sig}',
        'attachment_type': 'calendar_invite',
    },
    {
        'html': '<div style="font-family:Calibri,Arial,sans-serif;font-size:14px;color:#333;">'
                '<p>Hi,</p>'
                '<p>Attached is the summary of action items from last week. I highlighted the ones that are '
                'still open. Would be great if we could close these out before the end of the week.</p>'
                '<p>Thanks,<br>{signature}</p></div>',
        'text': 'Hi,\n\nAttached is the summary of action items from last week. I highlighted the ones that are '
                'still open. Would be great if we could close these out before the end of the week.\n\nThanks,\n{text_sig}',
        'attachment_type': 'action_items',
    },
]

_TEMPLATES_BY_TYPE = {
    'text_only': _TEMPLATES_TEXT_ONLY,
    'with_links': _TEMPLATES_WITH_LINKS,
    'with_attachment': _TEMPLATES_WITH_ATTACHMENT,
}

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


def _pick_email_type(emails_sent):
    """Round-robin across the three email types based on send count."""
    return _EMAIL_TYPES[emails_sent % len(_EMAIL_TYPES)]


def _generate_attachment(attachment_type, sender_domain):
    """Generate a simple, benign attachment. Returns a GoPhish attachment dict
    with 'name' (filename), 'content' (base64-encoded), and 'type' (MIME type)."""
    now = datetime.utcnow()
    date_str = now.strftime('%Y-%m-%d')

    if attachment_type == 'meeting_notes':
        content = (
            f'Meeting Notes - {date_str}\n'
            f'{"=" * 40}\n\n'
            f'Attendees: Team members\n'
            f'Date: {now.strftime("%A, %B %d, %Y")}\n\n'
            f'Key Decisions:\n'
            f'- Timeline approved for next phase\n'
            f'- Budget allocation confirmed\n'
            f'- Weekly check-ins to continue\n\n'
            f'Action Items:\n'
            f'- Finalize resource plan by end of week\n'
            f'- Share updated timeline with stakeholders\n'
            f'- Schedule follow-up for next Wednesday\n'
        )
        return {
            'name': f'meeting-notes-{date_str}.txt',
            'content': base64.b64encode(content.encode()).decode(),
            'type': 'text/plain',
        }

    elif attachment_type == 'contact_list':
        content = (
            'Name,Email,Role,Department\n'
            f'Project Lead,lead@{sender_domain},Manager,Operations\n'
            f'Analyst,analyst@{sender_domain},Senior Analyst,Research\n'
            f'Coordinator,coordinator@{sender_domain},Coordinator,Planning\n'
            f'Support,support@{sender_domain},Specialist,IT\n'
        )
        return {
            'name': f'team-contacts-{date_str}.csv',
            'content': base64.b64encode(content.encode()).decode(),
            'type': 'text/csv',
        }

    elif attachment_type == 'agenda':
        content = (
            f'Planning Session Agenda - {now.strftime("%B %d, %Y")}\n'
            f'{"=" * 40}\n\n'
            f'1. Review of previous action items (10 min)\n'
            f'2. Project status updates (15 min)\n'
            f'3. Resource allocation discussion (10 min)\n'
            f'4. Upcoming milestones and deadlines (10 min)\n'
            f'5. Open floor / questions (15 min)\n\n'
            f'Location: Conference Room B / Video call\n'
            f'Duration: 1 hour\n'
        )
        return {
            'name': f'agenda-{date_str}.txt',
            'content': base64.b64encode(content.encode()).decode(),
            'type': 'text/plain',
        }

    elif attachment_type == 'calendar_invite':
        # Next Thursday at 14:00 UTC
        days_until_thu = (3 - now.weekday()) % 7 or 7
        event_date = now + timedelta(days=days_until_thu)
        dt_start = event_date.strftime('%Y%m%dT140000Z')
        dt_end = event_date.strftime('%Y%m%dT150000Z')
        content = (
            'BEGIN:VCALENDAR\r\n'
            'VERSION:2.0\r\n'
            f'PRODID:-//{sender_domain}//EN\r\n'
            'BEGIN:VEVENT\r\n'
            f'DTSTART:{dt_start}\r\n'
            f'DTEND:{dt_end}\r\n'
            'SUMMARY:Review Session\r\n'
            'DESCRIPTION:Weekly review session with the project team.\r\n'
            f'ORGANIZER:MAILTO:noreply@{sender_domain}\r\n'
            'END:VEVENT\r\n'
            'END:VCALENDAR\r\n'
        )
        return {
            'name': 'review-session.ics',
            'content': base64.b64encode(content.encode()).decode(),
            'type': 'text/calendar',
        }

    else:  # action_items
        content = (
            f'Action Items Summary - {date_str}\n'
            f'{"=" * 40}\n\n'
            f'[OPEN]   Finalize Q4 budget proposal\n'
            f'[OPEN]   Update stakeholder presentation\n'
            f'[DONE]   Complete vendor evaluation\n'
            f'[DONE]   Submit compliance report\n'
            f'[OPEN]   Schedule training sessions for new hires\n'
        )
        return {
            'name': f'action-items-{date_str}.txt',
            'content': base64.b64encode(content.encode()).decode(),
            'type': 'text/plain',
        }


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


def _generate_email_content(used_subjects, from_address='', email_type='text_only',
                            sender_domain=''):
    """Return (subject, html_body, text_body, first_name, last_name, attachments)
    for a warm-up email.

    email_type: one of 'text_only', 'with_links', 'with_attachment'.
    sender_domain: used for hyperlinks and attachment content.
    Avoids subjects already used (per-target dedup).
    """
    available = [s for s in _SUBJECTS if s not in used_subjects]
    if not available:
        available = list(_SUBJECTS)
    subject = random.choice(available)
    first = random.choice(_FIRST_NAMES)
    last = random.choice(_LAST_NAMES)
    title = random.choice(_TITLES)
    sig_html = _build_signature(first, last, title, from_address)
    sig_text = _build_text_sig(first, last, title, from_address)

    templates = _TEMPLATES_BY_TYPE.get(email_type, _TEMPLATES_TEXT_ONLY)
    tpl = random.choice(templates)

    html = tpl['html'].replace('{signature}', sig_html).replace('{domain}', sender_domain)
    text = tpl['text'].replace('{text_sig}', sig_text).replace('{domain}', sender_domain)

    attachments = None
    if email_type == 'with_attachment' and tpl.get('attachment_type'):
        attachments = [_generate_attachment(tpl['attachment_type'], sender_domain)]

    return subject, html, text, first, last, attachments


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

        # Generate email content with subject deduplication and type rotation
        from_address = profile.get('from_address', f'noreply@{domain_name}')
        used_subjects = _get_recent_subjects(config.id, EmailGroomingLog)
        email_type = _pick_email_type(config.emails_sent or 0)
        subject, html_body, text_body, first_name, last_name, attachments = _generate_email_content(
            used_subjects, from_address, email_type=email_type, sender_domain=domain_name)
        envelope_sender = f'{first_name} {last_name} <{from_address}>'

        # Send via GoPhish
        try:
            gophish_service.send_test_email(
                smtp_profile=profile,
                to_email=config.target_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                envelope_sender=envelope_sender,
                attachments=attachments,
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


@celery.task(bind=True, max_retries=0, time_limit=1800, soft_time_limit=1700)
def run_full_grooming_cycle(self):
    """Send ALL remaining daily emails for every active config (manual trigger).

    Unlike process_email_grooming (which sends 1 per config per 30-min beat),
    this sends up to emails_per_day for each config with a short delay between
    sends to avoid bursting.
    """
    from app import db
    from app.models.email_grooming import EmailGroomingConfig
    from app.models.email_grooming_log import EmailGroomingLog
    from app.services import gophish_service

    configs = EmailGroomingConfig.query.filter_by(status='active').all()
    if not configs:
        return {'processed': 0, 'sent': 0, 'errors': 0}

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_count = 0
    error_count = 0
    processed = 0
    _profiles_cache = {}

    for config in configs:
        processed += 1
        domain = config.domain
        if not domain:
            _log.warning('Grooming config %d has no domain, skipping', config.id)
            continue

        today_sent = EmailGroomingLog.query.filter(
            EmailGroomingLog.config_id == config.id,
            EmailGroomingLog.sent_at >= today_start,
            EmailGroomingLog.success == True,  # noqa: E712
        ).count()

        remaining = config.emails_per_day - today_sent
        if remaining <= 0:
            _log.debug('Config %d: already sent %d/%d today, skipping',
                       config.id, today_sent, config.emails_per_day)
            continue

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
            _log.warning('No GoPhish sending profile for domain %s (config %d)', domain_name, config.id)
            log_entry = EmailGroomingLog(
                config_id=config.id, from_address='?', to_address=config.target_email,
                subject='(no profile)', success=False,
                error_message=f'No GoPhish sending profile found for domain {domain_name}',
            )
            db.session.add(log_entry)
            error_count += 1
            continue

        from_address = profile.get('from_address', f'noreply@{domain_name}')

        for i in range(remaining):
            used_subjects = _get_recent_subjects(config.id, EmailGroomingLog)
            email_type = _pick_email_type(config.emails_sent or 0)
            subject, html_body, text_body, first_name, last_name, attachments = _generate_email_content(
                used_subjects, from_address, email_type=email_type, sender_domain=domain_name)
            envelope_sender = f'{first_name} {last_name} <{from_address}>'

            try:
                gophish_service.send_test_email(
                    smtp_profile=profile,
                    to_email=config.target_email,
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    envelope_sender=envelope_sender,
                    attachments=attachments,
                )
                log_entry = EmailGroomingLog(
                    config_id=config.id, from_address=from_address,
                    to_address=config.target_email, subject=subject,
                    success=True, gophish_profile_id=profile.get('id'),
                )
                db.session.add(log_entry)
                config.emails_sent = (config.emails_sent or 0) + 1
                config.last_sent_at = datetime.utcnow()
                db.session.commit()
                sent_count += 1
                _log.info('Full cycle: sent %s -> %s [%s] (%d/%d)',
                          from_address, config.target_email, subject, i + 1, remaining)
            except Exception as exc:
                _log.error('Full cycle: failed config %d email %d: %s', config.id, i + 1, exc)
                log_entry = EmailGroomingLog(
                    config_id=config.id, from_address=from_address,
                    to_address=config.target_email, subject=subject,
                    success=False, error_message=str(exc)[:500],
                    gophish_profile_id=profile.get('id'),
                )
                db.session.add(log_entry)
                db.session.commit()
                error_count += 1

            # Re-pick profile for next email (advances rotation)
            profile = _pick_profile(config, all_profiles, gophish_service)
            if not profile:
                break

            # Small delay between sends to avoid bursting
            if i < remaining - 1:
                time.sleep(3)

    _log.info('Full grooming cycle complete: processed=%d sent=%d errors=%d',
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
    email_type = _pick_email_type(config.emails_sent or 0)
    subject, html_body, text_body, first_name, last_name, attachments = _generate_email_content(
        used_subjects, from_address, email_type=email_type, sender_domain=domain.name)
    envelope_sender = f'{first_name} {last_name} <{from_address}>'

    try:
        gophish_service.send_test_email(
            smtp_profile=profile,
            to_email=config.target_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            envelope_sender=envelope_sender,
            attachments=attachments,
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
