from app.tasks.celery_app import celery
from app.services import dns_service


@celery.task(bind=True, max_retries=3, default_retry_delay=5)
def create_dns_record(self, zone_id, record_type, name, content, ttl=1, proxied=False, priority=None):
    try:
        return dns_service.create_dns_record(zone_id, record_type, name, content, ttl, proxied, priority)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=3, default_retry_delay=5)
def update_dns_record(self, zone_id, record_id, record_type, name, content, ttl=1, proxied=False, priority=None):
    try:
        return dns_service.update_dns_record(zone_id, record_id, record_type, name, content, ttl, proxied, priority)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=3, default_retry_delay=5)
def delete_dns_record(self, zone_id, record_id):
    try:
        return dns_service.delete_dns_record(zone_id, record_id)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=2, default_retry_delay=10)
def sync_zone_records(self, zone_id):
    """Sync all DNS records for a zone from Cloudflare into local database."""
    from app import db
    from app.models.domain import Domain, DNSRecord

    zone = dns_service.get_zone(zone_id)
    records = dns_service.list_dns_records(zone_id)

    domain = Domain.query.filter_by(cloudflare_zone_id=zone_id).first()
    if not domain:
        domain = Domain(
            name=zone['name'],
            cloudflare_zone_id=zone_id,
            status=zone.get('status', 'active'),
        )
        db.session.add(domain)
        db.session.flush()

    existing_records = {r.cloudflare_record_id: r for r in domain.dns_records}
    seen_ids = set()

    for rec in records:
        cf_id = rec['id']
        seen_ids.add(cf_id)

        if cf_id in existing_records:
            db_rec = existing_records[cf_id]
            db_rec.record_type = rec['type']
            db_rec.name = rec['name']
            db_rec.content = rec['content']
            db_rec.ttl = rec.get('ttl', 1)
            db_rec.proxied = rec.get('proxied', False)
            db_rec.priority = rec.get('priority')
        else:
            db_rec = DNSRecord(
                domain_id=domain.id,
                cloudflare_record_id=cf_id,
                record_type=rec['type'],
                name=rec['name'],
                content=rec['content'],
                ttl=rec.get('ttl', 1),
                proxied=rec.get('proxied', False),
                priority=rec.get('priority'),
            )
            db.session.add(db_rec)

    # Remove records that no longer exist in Cloudflare
    for cf_id, db_rec in existing_records.items():
        if cf_id not in seen_ids:
            db.session.delete(db_rec)

    db.session.commit()
    return {'zone': zone['name'], 'records_synced': len(records)}
