"""ia_target_service.py — Target management for initial access campaigns.

Handles CRUD, CSV import with dedup on (project_id, email),
and OSINT enrichment from scan results.
"""

import csv
import io
import json
import logging
from datetime import datetime

from app import db
from app.models.ia_target import IATarget

_log = logging.getLogger(__name__)

# CSV column mapping: header variations -> model field
_CSV_FIELD_MAP = {
    'first_name': 'first_name', 'first name': 'first_name', 'firstname': 'first_name',
    'last_name': 'last_name', 'last name': 'last_name', 'lastname': 'last_name',
    'email': 'email', 'email address': 'email', 'e-mail': 'email',
    'phone': 'phone', 'phone number': 'phone', 'mobile': 'phone',
    'job_title': 'job_title', 'job title': 'job_title', 'title': 'job_title', 'position': 'job_title',
    'department': 'department', 'dept': 'department',
    'organisation': 'organisation', 'organization': 'organisation', 'company': 'organisation', 'org': 'organisation',
    'linkedin_url': 'linkedin_url', 'linkedin': 'linkedin_url',
    'notes': 'notes',
}

_VALID_FIELDS = {'first_name', 'last_name', 'email', 'phone', 'job_title',
                 'department', 'organisation', 'linkedin_url', 'notes'}

MAX_CSV_IMPORT_ROWS = 5000
MAX_CSV_IMPORT_BYTES = 1024 * 1024


def validate_csv_import_size(csv_text):
    """Return (ok, reason) for IA target CSV import limits (L-09)."""
    if len((csv_text or '').encode('utf-8')) > MAX_CSV_IMPORT_BYTES:
        return False, f'CSV import exceeds {MAX_CSV_IMPORT_BYTES // 1024} KiB limit'
    try:
        row_count = max(0, sum(1 for _ in csv.reader(io.StringIO(csv_text))) - 1)
    except csv.Error as exc:
        return False, f'Invalid CSV: {exc}'
    if row_count > MAX_CSV_IMPORT_ROWS:
        return False, f'CSV import exceeds {MAX_CSV_IMPORT_ROWS} data-row limit'
    return True, None


def list_targets(project_id, search=None):
    """List all targets for a project, optionally filtered by search term."""
    q = IATarget.query.filter_by(project_id=project_id)
    if search:
        pattern = f'%{search}%'
        q = q.filter(
            db.or_(
                IATarget.email.ilike(pattern),
                IATarget.first_name.ilike(pattern),
                IATarget.last_name.ilike(pattern),
                IATarget.organisation.ilike(pattern),
                IATarget.department.ilike(pattern),
                IATarget.job_title.ilike(pattern),
            )
        )
    return q.order_by(IATarget.created_at.desc()).all()


def get_target(target_id):
    return IATarget.query.get(target_id)


def create_target(project_id, data, user_id):
    """Create a single target. Returns the target or raises on duplicate."""
    target = IATarget(
        project_id=project_id,
        source='manual',
        created_by_id=user_id,
    )
    for field in _VALID_FIELDS:
        val = data.get(field)
        if val is not None:
            setattr(target, field, str(val).strip()[:500])

    db.session.add(target)
    db.session.commit()
    return target


def update_target(target, data):
    """Update a target's fields."""
    for field in _VALID_FIELDS:
        if field in data:
            val = data[field]
            setattr(target, field, str(val).strip()[:500] if val else None)
    target.updated_at = datetime.utcnow()
    db.session.commit()
    return target


def delete_target(target):
    db.session.delete(target)
    db.session.commit()


def import_csv(project_id, csv_text, user_id):
    """Import targets from CSV text. Deduplicates on (project_id, email).

    Returns:
        dict with 'created', 'skipped', 'errors' counts and 'error_details' list.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        return {'created': 0, 'skipped': 0, 'errors': 1, 'error_details': ['No CSV headers found']}

    # Map CSV headers to model fields
    col_map = {}
    for header in reader.fieldnames:
        normalised = header.strip().lower()
        if normalised in _CSV_FIELD_MAP:
            col_map[header] = _CSV_FIELD_MAP[normalised]

    if 'email' not in col_map.values():
        return {'created': 0, 'skipped': 0, 'errors': 1,
                'error_details': ['CSV must contain an "email" column']}

    # Load existing emails for dedup
    existing = set(
        r[0].lower() for r in
        db.session.query(IATarget.email)
        .filter_by(project_id=project_id)
        .filter(IATarget.email.isnot(None))
        .all()
    )

    created = 0
    skipped = 0
    errors = 0
    error_details = []
    skipped_details = []

    for row_num, row in enumerate(reader, start=2):
        try:
            mapped = {}
            for csv_col, model_field in col_map.items():
                val = row.get(csv_col, '').strip()
                if val:
                    mapped[model_field] = val[:500]

            email = mapped.get('email')
            if not email:
                skipped += 1
                skipped_details.append(f'Row {row_num}: missing email')
                continue

            if email.lower() in existing:
                skipped += 1
                skipped_details.append(f'Row {row_num}: duplicate ({email})')
                continue

            target = IATarget(
                project_id=project_id,
                source='import',
                created_by_id=user_id,
                **mapped,
            )
            db.session.add(target)
            existing.add(email.lower())
            created += 1
        except Exception as e:
            errors += 1
            error_details.append(f'Row {row_num}: {e}')

    if created:
        db.session.commit()

    _log.info('CSV import for project %s: %d created, %d skipped, %d errors',
              project_id, created, skipped, errors)
    return {'created': created, 'skipped': skipped, 'errors': errors,
            'error_details': error_details, 'skipped_details': skipped_details}


def enrich_from_scan(target, scan_results):
    """Enrich a target with OSINT data from scan results.

    Matches the target's email against breach/email lists in the scan results.
    Merges new data with existing enrichment (does not overwrite).
    """
    if not target.email or not scan_results:
        return False

    email_lower = target.email.lower()
    enriched = False

    # Breach enrichment
    breaches = scan_results.get('breaches', [])
    matching_breaches = [b for b in breaches if b.get('email', '').lower() == email_lower]
    if matching_breaches:
        existing = json.loads(target.breach_sources) if target.breach_sources else []
        existing_keys = {(b.get('source'), b.get('year')) for b in existing}
        for b in matching_breaches:
            key = (b.get('source'), b.get('year'))
            if key not in existing_keys:
                existing.append(b)
                enriched = True
        target.breach_sources = json.dumps(existing)

    # Email presence enrichment — mark that the email was found in recon
    emails_found = scan_results.get('emails', [])
    matching_emails = [e for e in emails_found if e.get('address', '').lower() == email_lower]
    if matching_emails:
        existing_svcs = json.loads(target.exposed_services) if target.exposed_services else []
        existing_sources = {s.get('source') for s in existing_svcs}
        for e in matching_emails:
            src = e.get('source')
            if src and src not in existing_sources:
                existing_svcs.append({'service': 'email_exposure', 'host': email_lower, 'port': src})
                enriched = True
        target.exposed_services = json.dumps(existing_svcs)

    if enriched:
        target.osint_enriched_at = datetime.utcnow()
        db.session.commit()

    return enriched


def bulk_enrich_from_scan(project_id, scan_results):
    """Enrich all targets in a project from scan results. Returns count of enriched targets."""
    targets = IATarget.query.filter_by(project_id=project_id).filter(IATarget.email.isnot(None)).all()
    count = 0
    for t in targets:
        if enrich_from_scan(t, scan_results):
            count += 1
    return count
