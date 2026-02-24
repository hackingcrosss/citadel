from celery import Celery
from app import create_app

flask_app = create_app()

celery = Celery(
    flask_app.import_name,
    broker=flask_app.config['CELERY_BROKER_URL'],
    backend=flask_app.config['CELERY_RESULT_BACKEND'],
)
celery.conf.update(flask_app.config)


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
