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
        """Inject user_projects and active_project into every template."""
        from flask_login import current_user
        try:
            if not current_user.is_authenticated:
                return {'user_projects': [], 'active_project': None}
            from app.services.project_service import get_projects_for_user, get_active_project
            return {
                'user_projects': get_projects_for_user(current_user),
                'active_project': get_active_project(current_user),
            }
        except Exception:
            return {'user_projects': [], 'active_project': None}

    return app