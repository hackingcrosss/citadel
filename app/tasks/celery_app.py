from celery import Celery
from app import create_app

flask_app = create_app()

celery = Celery(flask_app.import_name)
celery.conf.update(
    broker_url=flask_app.config['CELERY_BROKER_URL'],
    result_backend=flask_app.config['CELERY_RESULT_BACKEND'],
    beat_schedule={
        'email-grooming-cycle': {
            'task': 'app.tasks.email_grooming_tasks.process_email_grooming',
            'schedule': 1800.0,  # every 30 minutes
        },
        'ia-campaign-sync': {
            'task': 'app.tasks.initial_access_tasks.sync_active_campaigns',
            'schedule': 300.0,  # every 5 minutes
        },
    },
    timezone='UTC',
)


class ContextTask(celery.Task):
    """Ensure every Celery task runs inside a Flask application context."""
    def __call__(self, *args, **kwargs):
        with flask_app.app_context():
            return self.run(*args, **kwargs)


celery.Task = ContextTask

# Import task modules so they are registered with the celery instance
import app.tasks.dns_tasks               # noqa: F401, E402
import app.tasks.container_tasks          # noqa: F401, E402
import app.tasks.website_generator_tasks  # noqa: F401, E402
import app.tasks.cdn_tasks                # noqa: F401, E402
import app.tasks.email_grooming_tasks     # noqa: F401, E402
import app.tasks.initial_access_tasks    # noqa: F401, E402
