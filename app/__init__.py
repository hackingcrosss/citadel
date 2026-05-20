from urllib.parse import urlparse

from flask import Flask, g, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from app.config import Config

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Behind nginx — trust X-Forwarded-* headers from exactly one proxy hop
    # so request.remote_addr reflects the real client IP, not the docker
    # bridge gateway. Fixes A-01 (single attacker IP locking out all users
    # via the login rate-limiter) and makes the audit log record useful
    # client IPs. If a deployment adds an upstream proxy (ALB, CDN), bump
    # x_for to match the number of trusted hops — but never set it higher
    # than the real chain length or clients can spoof X-Forwarded-For.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    migrate.init_app(app, db)
    csrf.init_app(app)

    def _same_origin_url(value):
        """Return True when an Origin/Referer header points at this app."""
        if not value:
            return True
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return False
        expected = urlparse(request.host_url)
        return parsed.scheme in ('http', 'https') and parsed.netloc == expected.netloc

    @app.before_request
    def enforce_api_request_hardening():
        """Defense-in-depth for JSON API CSRF targets (H-06).

        Flask-WTF CSRFProtect validates X-CSRFToken on mutating API requests;
        this additionally rejects cross-origin browser requests and non-JSON
        request bodies for API mutations that send a body.
        """
        if not request.path.startswith('/api/'):
            return None
        if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return None

        origin = request.headers.get('Origin')
        referer = request.headers.get('Referer')
        if origin and not _same_origin_url(origin):
            return jsonify({'error': 'Cross-origin API request rejected'}), 403
        if not origin and referer and not _same_origin_url(referer):
            return jsonify({'error': 'Cross-origin API request rejected'}), 403

        if request.content_length and request.mimetype != 'application/json':
            return jsonify({'error': 'API mutations with a request body must use application/json'}), 415
        return None

    @app.after_request
    def set_security_headers(response):
        """Apply app-layer browser hardening headers (I-07/M-05)."""
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net data:; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    # Register blueprints
    from app.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    # Register routes
    from app.routes import register_routes
    register_routes(app)

    # Register CLI commands
    from app.cli import register_cli
    register_cli(app)

    # Inject current_plan into every template context (cached per request on g)
    from app.services.plan_service import get_current_plan

    @app.context_processor
    def inject_plan():
        try:
            return {'current_plan': get_current_plan()}
        except Exception:
            # Graceful fallback during DB migrations / setup
            from app.services.plan_service import PlanInfo, TIERS
            return {'current_plan': PlanInfo(
                tier='community',
                max_users=1, max_domains=3,
                features=TIERS['community']['features'],
                org_name='',
            )}

    @app.context_processor
    def inject_projects():
        """Inject user_projects, active_project, and active_project_role into every template."""
        from flask_login import current_user
        try:
            if not current_user.is_authenticated:
                return {'user_projects': [], 'active_project': None, 'active_project_role': None}
            from app.services.project_service import (
                get_projects_for_user, get_active_project, get_user_project_role,
            )
            active = get_active_project(current_user)
            role = None
            if active:
                if current_user.is_admin:
                    role = 'operator'
                elif current_user.is_auditor:
                    role = 'auditor'
                else:
                    role = get_user_project_role(current_user.id, active.id)
            all_projects = get_projects_for_user(current_user)
            return {
                'user_projects': [p for p in all_projects if p.status == 'active'],
                'active_project': active,
                'active_project_role': role,
            }
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning('inject_projects failed: %s', exc)
            return {'user_projects': [], 'active_project': None, 'active_project_role': None}

    @app.context_processor
    def inject_hetzner_enabled():
        """Inject hetzner_enabled: True when at least one Hetzner credential is configured.

        Drives sidebar visibility, page route gating, and frontend picker inclusion.
        Cached on g for the request so the DB hit happens at most once per render.
        """
        try:
            if hasattr(g, '_hetzner_enabled'):
                return {'hetzner_enabled': g._hetzner_enabled}
            from flask_login import current_user
            if not current_user.is_authenticated:
                return {'hetzner_enabled': False}
            from app.services.credential_service import get_account_labels
            enabled = bool(get_account_labels('hetzner'))
            g._hetzner_enabled = enabled
            return {'hetzner_enabled': enabled}
        except Exception:
            return {'hetzner_enabled': False}

    @app.context_processor
    def inject_phase():
        """Inject phase flags for the phase switcher in the sidebar."""
        from flask import request as _req
        try:
            path = _req.path
            return {
                'is_ia_phase': path.startswith('/initial-access/'),
                'is_citadel_phase': path.startswith('/citadel/'),
            }
        except Exception:
            return {'is_ia_phase': False, 'is_citadel_phase': False}

    @app.context_processor
    def inject_company():
        """Inject active_company and user_companies into every template."""
        from flask_login import current_user
        try:
            if not current_user.is_authenticated or current_user.is_admin:
                return {'active_company': None, 'user_companies': []}
            from app.services.project_service import get_active_project
            from app.models.company import Company
            from app.models.project import Project, ProjectMember
            # white_team: use direct company_id on user
            if current_user.is_white_team:
                active_company = current_user.company if current_user.company_id else None
                user_companies = [active_company] if active_company else []
                return {'active_company': active_company, 'user_companies': user_companies}
            # auditor has global read-only access — see all companies
            if current_user.is_auditor:
                all_companies = Company.query.filter_by(status='active').order_by(Company.name).all()
                return {'active_company': None, 'user_companies': all_companies}
            # project_admin: see all active companies (needed to create projects)
            if current_user.is_project_admin:
                all_companies = Company.query.filter_by(status='active').order_by(Company.name).all()
                active = get_active_project(current_user)
                active_company = None
                if active and active.company_id:
                    active_company = Company.query.get(active.company_id)
                return {'active_company': active_company, 'user_companies': all_companies}
            # operator: derive from active project + all memberships
            active = get_active_project(current_user)
            active_company = None
            if active and active.company_id:
                active_company = Company.query.get(active.company_id)
            user_companies = (
                Company.query
                .join(Project, Project.company_id == Company.id)
                .join(ProjectMember, ProjectMember.project_id == Project.id)
                .filter(
                    ProjectMember.user_id == current_user.id,
                    Project.status == 'active',
                )
                .distinct()
                .order_by(Company.name)
                .all()
            )
            return {'active_company': active_company, 'user_companies': user_companies}
        except Exception:
            return {'active_company': None, 'user_companies': []}

    return app