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

    Error visibility rules:
    - Debug mode: full error string (developer workflow).
    - Admin users: error string included (operational diagnostics).
    - Everyone else: generic "Internal error" + correlation id.
    """
    err_id = uuid4().hex[:12]
    current_app.logger.exception('api error [%s]', err_id)
    body = {'err_id': err_id}

    show_detail = current_app.debug
    if not show_detail:
        try:
            from flask_login import current_user
            show_detail = current_user.is_authenticated and current_user.is_admin
        except Exception:
            pass

    if show_detail:
        body['error'] = str(exc)
    else:
        body['error'] = 'Internal error'
    body.update(extra)
    return jsonify(body), status
