from app.tasks.celery_app import celery


@celery.task(bind=True, max_retries=0, time_limit=600, soft_time_limit=570)
def create_cdn_distribution_task(self, dist_id, provider, origin_host, origin_port,
                                  comment, account_label, resource_group=None):
    """
    Background task for CDN distribution creation.
    The DB record is pre-created with status='creating' and external_id='task:<task_id>'.
    On success: updates external_id, domain, status='deploying'.
    On failure: sets status='error', external_id='error:<message>'.
    """
    from app import db
    from app.models.cdn_distribution import CdnDistribution
    from app.services import cdn_service

    dist = CdnDistribution.query.get(dist_id)
    if not dist:
        return {'error': 'Distribution record not found'}

    try:
        if provider == 'cloudfront':
            result = cdn_service.create_cloudfront_distribution(
                origin_host, origin_port, comment, label=account_label
            )
        else:
            result = cdn_service.create_afd_distribution(
                resource_group, origin_host, origin_port, comment, label=account_label
            )

        dist.external_id = result['external_id']
        dist.domain = result['domain']
        dist.status = result.get('status', 'deploying')
        db.session.commit()
        return {'external_id': result['external_id'], 'domain': result['domain'], 'status': dist.status}

    except Exception as exc:
        dist.status = 'error'
        dist.external_id = f'error:{str(exc)[:400]}'
        db.session.commit()
        raise
