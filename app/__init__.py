from flask import Flask, g
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from app.config import Config

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    migrate.init_app(app, db)

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