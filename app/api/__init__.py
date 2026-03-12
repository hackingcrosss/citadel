from flask import Blueprint

api_bp = Blueprint('api', __name__)

from app.api import domains, containers, aws, azure, azure_dns, cdn, credentials, npm, email, gophish, cobaltstrike, website_generator, task_log, users, license, projects, companies