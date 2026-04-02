"""ia_scan_service.py — External vulnerability scanner integration.

Triggers scans on an external scanning tool via its REST API,
polls for completion, and ingests results into IAScanJob rows.

Scanner credentials are stored via credential_service:
    provider='scanner', key_name='api_url'  -> base URL of the scanner API
    provider='scanner', key_name='api_key'  -> API key / bearer token
"""

import json
import logging
from datetime import datetime

import requests
from flask import current_app

from app import db
from app.models.ia_scan_job import IAScanJob
from app.services import credential_service

_log = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30  # seconds


def _get_scanner_config():
    """Return (api_url, api_key) or raise if not configured."""
    api_url = credential_service.get_credential('scanner', 'api_url')
    api_key = credential_service.get_credential('scanner', 'api_key')
    if not api_url or not api_key:
        raise ValueError('Scanner credentials not configured. Add them in Settings.')
    return api_url.rstrip('/'), api_key


def _headers(api_key):
    return {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def test_connection():
    """Test connectivity to the scanner API. Returns a status dict."""
    api_url, api_key = _get_scanner_config()
    resp = requests.get(
        f'{api_url}/api/health',
        headers=_headers(api_key),
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return {'status': 'ok', 'url': api_url}


def trigger_scan(project_id, scope_config, user_id):
    """Trigger a scan on the external scanner and create a local IAScanJob.

    Args:
        project_id: Active project ID.
        scope_config: dict with 'domains' (list[str]) and/or 'ip_ranges' (list[str]).
        user_id: ID of the user who triggered the scan.

    Returns:
        The created IAScanJob instance.
    """
    api_url, api_key = _get_scanner_config()

    resp = requests.post(
        f'{api_url}/api/scans',
        headers=_headers(api_key),
        json={'scope': scope_config},
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    job = IAScanJob(
        project_id=project_id,
        external_job_id=data.get('job_id'),
        status=data.get('status', 'pending'),
        target_scope=json.dumps(scope_config),
        triggered_by_id=user_id,
        triggered_at=datetime.utcnow(),
    )
    db.session.add(job)
    db.session.commit()

    _log.info('Scan job %s triggered (external: %s) for project %s',
              job.id, job.external_job_id, project_id)
    return job


def poll_scan_job(job_id):
    """Poll the external scanner for the status of a scan job.

    Updates the local IAScanJob row with latest status and results.

    Returns:
        The updated IAScanJob instance, or None if not found.
    """
    job = IAScanJob.query.get(job_id)
    if not job:
        return None

    if job.status in ('completed', 'failed'):
        return job

    api_url, api_key = _get_scanner_config()

    resp = requests.get(
        f'{api_url}/api/scans/{job.external_job_id}',
        headers=_headers(api_key),
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    job.status = data.get('status', job.status)
    job.polled_at = datetime.utcnow()

    if job.status == 'completed':
        results = data.get('results', {})
        job.raw_results = json.dumps(results)
        job.results_summary = json.dumps(_build_summary(results))
        job.completed_at = datetime.utcnow()
        _log.info('Scan job %s completed', job.id)

    elif job.status == 'failed':
        job.error_message = data.get('error', 'Unknown error from scanner')
        job.completed_at = datetime.utcnow()
        _log.warning('Scan job %s failed: %s', job.id, job.error_message)

    db.session.commit()
    return job


def _build_summary(results):
    """Build a compact summary from raw scan results."""
    return {
        'subdomains': len(results.get('subdomains', [])),
        'open_ports': len(results.get('open_ports', [])),
        'technologies': len(results.get('technologies', [])),
        'emails': len(results.get('emails', [])),
        'breaches': len(results.get('breaches', [])),
    }


def get_scan_results(job_id):
    """Return the full parsed results for a completed scan job."""
    job = IAScanJob.query.get(job_id)
    if not job or not job.raw_results:
        return None
    return json.loads(job.raw_results)
