from app.tasks.celery_app import celery
from app.services import docker_service


@celery.task(bind=True, max_retries=2, default_retry_delay=5)
def start_container(self, container_id):
    try:
        return docker_service.start_container(container_id)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=2, default_retry_delay=5)
def stop_container(self, container_id):
    try:
        return docker_service.stop_container(container_id)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=2, default_retry_delay=5)
def restart_container(self, container_id):
    try:
        return docker_service.restart_container(container_id)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=1, default_retry_delay=5)
def remove_container(self, container_id, force=False):
    try:
        return docker_service.remove_container(container_id, force=force)
    except Exception as exc:
        raise self.retry(exc=exc)
