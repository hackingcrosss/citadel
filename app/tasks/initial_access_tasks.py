import logging
import time

from app.tasks.celery_app import celery

_log = logging.getLogger(__name__)

_POLL_INTERVAL = 60   # seconds between polls
_MAX_POLLS = 120      # max ~2 hours of polling


@celery.task(bind=True, max_retries=0, time_limit=7500, soft_time_limit=7200)
def scan_poll_job(self, job_id):
    """Poll the external scanner until the job reaches a terminal state.

    Called automatically after a scan is triggered.  Polls every 60 seconds
    for up to ~2 hours.  On completion, results are ingested into the
    IAScanJob row by ia_scan_service.poll_scan_job().
    """
    from app.services import ia_scan_service

    for attempt in range(1, _MAX_POLLS + 1):
        try:
            job = ia_scan_service.poll_scan_job(job_id)
            if job is None:
                _log.warning('Scan job %s not found, stopping poll', job_id)
                return {'status': 'not_found'}

            if job.status in ('completed', 'failed'):
                _log.info('Scan job %s finished with status: %s (poll #%d)',
                          job_id, job.status, attempt)
                return {'status': job.status, 'job_id': job_id}

        except Exception as e:
            _log.warning('Poll attempt %d for scan job %s failed: %s',
                         attempt, job_id, e)

        time.sleep(_POLL_INTERVAL)

    _log.warning('Scan job %s timed out after %d polls', job_id, _MAX_POLLS)
    return {'status': 'timeout', 'job_id': job_id}


@celery.task(bind=True, max_retries=0, time_limit=120, soft_time_limit=90)
def sync_active_campaigns(self):
    """Periodic task: sync events for all active GoPhish campaigns."""
    from app.services import ia_campaign_service

    try:
        count = ia_campaign_service.sync_all_active_campaigns()
        _log.info('Campaign sync complete: %d new events', count)
        return {'new_events': count}
    except Exception as e:
        _log.exception('Campaign sync failed: %s', e)
        return {'error': str(e)}


@celery.task(bind=True, max_retries=0, time_limit=300, soft_time_limit=270)
def generate_email_templates_task(self, batch_id, project_id, scan_job_id=None):
    """Generate AI-powered phishing email templates for a batch."""
    from app.services import email_template_service

    email_template_service.run_generation(batch_id, project_id, scan_job_id)
    return {'batch_id': batch_id, 'status': 'completed'}


@celery.task(bind=True, max_retries=0, time_limit=120, soft_time_limit=90)
def extract_intel_task(self, project_id, raw_text, updated_by_id):
    """Extract structured business intel fields from pasted markdown via Azure OpenAI."""
    from app.services import ia_business_intel_service

    try:
        fields = ia_business_intel_service.extract_fields_from_text(raw_text)
        ia_business_intel_service.update_intel(project_id, fields, updated_by_id)
        return {'status': 'completed', 'fields': list(fields.keys())}
    except Exception as e:
        _log.exception('Intel extraction failed for project %s', project_id)
        return {'status': 'failed', 'error': str(e)}


@celery.task(bind=True, max_retries=0, time_limit=120, soft_time_limit=90)
def fofa_search_task(self, search_ids, project_id):
    """Execute FOFA searches for a list of scope items."""
    from app.services import fofa_service

    try:
        fofa_service.run_scope_search(search_ids, project_id)
        return {'status': 'completed', 'search_ids': search_ids}
    except Exception as e:
        _log.exception('FOFA search task failed for project %s', project_id)
        return {'status': 'failed', 'error': str(e)}
