from flask import Blueprint, jsonify
from werkzeug.exceptions import HTTPException

api_bp = Blueprint('api', __name__)


@api_bp.errorhandler(HTTPException)
def api_http_error(error):
    """Return JSON for API aborts instead of Flask's HTML error pages."""
    return jsonify({'error': error.description or error.name}), error.code or 500


from app.api import domains, containers, aws, azure, azure_dns, hetzner, cdn, credentials, npm, email, gophish, cobaltstrike, website_generator, task_log, users, license, projects, companies, audit, email_grooming, initial_access, evilginx, watchtower
