from app.tasks.celery_app import celery


@celery.task(bind=True, max_retries=0, time_limit=600, soft_time_limit=570)
def generate_website_task(self, category, domain=None, extra_context=None):
    """
    Background task for website generation.
    Runs the full plan → HTML pipeline without blocking the web worker.
    Result is stored in Redis and retrievable via AsyncResult.
    """
    from app.services import website_generator_service
    plan, html = website_generator_service.generate_website(category, domain=domain, extra_context=extra_context)
    return {'plan': plan, 'html': html}
