"""Safe error responses for API endpoints.

Replaces the broad `return jsonify({'error': str(e)}), N` pattern with a helper
that logs the full exception server-side and returns a generic message + a
short correlation id to the client. In debug mode the raw text is included to
keep the developer workflow useful. See finding G-03.
"""

from uuid import uuid4
from flask import current_app, jsonify


def safe_error(exc, status=400, **extra):
    """Log `exc` server-side, return a masked JSON response with a correlation id.

    `extra` keys are merged into the response body so endpoints that previously
    returned auxiliary fields (e.g. `tasks=[]`, `sites=[]`) keep working.
    """
    err_id = uuid4().hex[:12]
    current_app.logger.exception('api error [%s]', err_id)
    body = {'err_id': err_id}
    if current_app.debug:
        body['error'] = str(exc)
    else:
        body['error'] = 'Internal error'
    body.update(extra)
    return jsonify(body), status
