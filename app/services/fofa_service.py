"""FOFA search engine integration for infrastructure OSINT."""

import json
import logging
from base64 import b64encode
from datetime import datetime

import requests

from app import db
from app.models.ia_fofa_search import IAFofaSearch
from app.services.credential_service import get_credential

_log = logging.getLogger(__name__)

BASE_URL = 'https://fofa.info/api/v1/search/all'

DEFAULT_FIELDS = (
    'host', 'ip', 'port', 'protocol', 'title', 'server',
    'domain', 'country', 'as_organization', 'lastupdatetime',
)

MAX_SIZE = 500  # results per query (safe default within free-tier limits)


def _get_config():
    email = get_credential('fofa', 'email')
    api_key = get_credential('fofa', 'api_key')
    if not email or not api_key:
        raise ValueError('FOFA credentials not configured. Add them in Settings.')
    return email, api_key


def test_connection():
    """Verify FOFA credentials with a minimal query."""
    email, api_key = _get_config()
    resp = requests.get(BASE_URL, params={
        'email': email, 'key': api_key,
        'qbase64': b64encode(b'host="fofa.info"').decode(),
        'fields': 'host',
        'size': 1,
    }, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get('error'):
        raise ValueError(data.get('errmsg', 'FOFA API error'))
    return {'status': 'ok'}


def search(query, fields=None, size=None, page=1):
    """Execute a FOFA search. Returns {total, results, query}."""
    email, api_key = _get_config()
    fields = fields or DEFAULT_FIELDS
    size = size or MAX_SIZE

    resp = requests.get(BASE_URL, params={
        'email': email,
        'key': api_key,
        'qbase64': b64encode(query.encode()).decode(),
        'fields': ','.join(fields),
        'size': size,
        'page': page,
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get('error'):
        raise ValueError(data.get('errmsg', 'FOFA API error'))

    results = [dict(zip(fields, row)) for row in (data.get('results') or [])]
    return {
        'total': data.get('size', 0),
        'results': results,
        'query': query,
    }


def build_query(scope_type, scope_value):
    """Build a FOFA query string from a scope item."""
    if scope_type == 'domain':
        return f'domain="{scope_value}"'
    elif scope_type == 'ip':
        return f'ip="{scope_value}"'
    elif scope_type == 'cidr':
        return f'ip="{scope_value}"'
    else:
        return scope_value  # custom query — pass through


def run_scope_search(search_ids, project_id):
    """Execute FOFA searches for a list of IAFofaSearch records.

    Called by the Celery task. Processes each search sequentially.
    """
    for search_id in search_ids:
        record = IAFofaSearch.query.get(search_id)
        if not record or record.project_id != project_id:
            continue

        try:
            data = search(record.search_query)
            record.total_results = data['total']
            record.results_count = len(data['results'])
            record.raw_results = json.dumps(data['results'])
            record.status = 'completed'
        except Exception as e:
            _log.exception('FOFA search failed for record %s', search_id)
            record.status = 'failed'
            record.error_message = str(e)[:2000]

        db.session.commit()
