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
