"""Flask CLI commands for Citadel operational tasks."""
from datetime import datetime, timedelta

import click
from cryptography.fernet import InvalidToken
from flask import current_app
from flask.cli import with_appcontext

from app import db
from app.models.credential import Credential
from app.models.instance_ssh_config import InstanceSSHConfig
from app.models.audit_log import AuditLog
from app.services.credential_service import _get_fernet, _get_primary_fernet


@click.command('rotate-keys-sweep')
@click.option('--dry-run', is_flag=True, help='Report what would be rotated; do not write.')
@with_appcontext
def rotate_keys_sweep(dry_run):
    """Re-encrypt every credential and SSH private key with the current primary
    MASTER_ENCRYPTION_KEY.

    Procedure for a rotation window:

      1. Generate a fresh key:
           python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
      2. In secrets.env: move the old MASTER_ENCRYPTION_KEY to
         MASTER_ENCRYPTION_KEY_LEGACY, set MASTER_ENCRYPTION_KEY to the new value.
      3. Restart the app. Existing rows decrypt via the legacy key; new writes
         use the primary.
      4. `flask rotate-keys-sweep --dry-run` to preview, then
         `flask rotate-keys-sweep` to commit.
      5. Remove MASTER_ENCRYPTION_KEY_LEGACY from secrets.env and restart.
    """
    primary = _get_primary_fernet()
    multi = _get_fernet()

    stats = {
        'credentials': {'rotated': 0, 'unchanged': 0, 'failed': 0},
        'ssh_keys':    {'rotated': 0, 'unchanged': 0, 'failed': 0},
    }

    click.echo("Sweeping credentials table...")
    for cred in Credential.query.all():
        blob = cred.encrypted_value.encode()
        try:
            primary.decrypt(blob)
            stats['credentials']['unchanged'] += 1
            continue
        except InvalidToken:
            pass
        try:
            new_blob = multi.rotate(blob).decode()
            if not dry_run:
                cred.encrypted_value = new_blob
            stats['credentials']['rotated'] += 1
            click.echo(f"  rotated id={cred.id} {cred.provider}/{cred.label}/{cred.key_name}")
        except InvalidToken:
            stats['credentials']['failed'] += 1
            click.echo(
                f"  FAILED id={cred.id} {cred.provider}/{cred.label}/{cred.key_name}",
                err=True,
            )

    click.echo("Sweeping instance_ssh_configs table...")
    for ssh in InstanceSSHConfig.query.all():
        blob = ssh.encrypted_private_key.encode()
        try:
            primary.decrypt(blob)
            stats['ssh_keys']['unchanged'] += 1
            continue
        except InvalidToken:
            pass
        try:
            new_blob = multi.rotate(blob).decode()
            if not dry_run:
                ssh.encrypted_private_key = new_blob
            stats['ssh_keys']['rotated'] += 1
            click.echo(f"  rotated id={ssh.id} {ssh.provider}/{ssh.instance_id}")
        except InvalidToken:
            stats['ssh_keys']['failed'] += 1
            click.echo(f"  FAILED id={ssh.id} {ssh.provider}/{ssh.instance_id}", err=True)

    if dry_run:
        click.echo("\n[DRY RUN] No changes committed.")
    elif stats['credentials']['rotated'] or stats['ssh_keys']['rotated']:
        db.session.commit()
        click.echo("\nCommitted.")
    else:
        click.echo("\nNo rows needed rotation.")

    click.echo(
        f"credentials  rotated={stats['credentials']['rotated']}  "
        f"unchanged={stats['credentials']['unchanged']}  "
        f"failed={stats['credentials']['failed']}"
    )
    click.echo(
        f"ssh keys     rotated={stats['ssh_keys']['rotated']}  "
        f"unchanged={stats['ssh_keys']['unchanged']}  "
        f"failed={stats['ssh_keys']['failed']}"
    )

    if stats['credentials']['failed'] or stats['ssh_keys']['failed']:
        click.echo(
            "\nOne or more rows did not decrypt with the primary or any legacy "
            "key. Confirm MASTER_ENCRYPTION_KEY_LEGACY contains every prior key "
            "used to encrypt rows currently in the database.",
            err=True,
        )
        raise click.exceptions.Exit(1)


@click.command('audit-retention-sweep')
@click.option('--days', type=int, default=None, help='Retention window in days; defaults to AUDIT_RETENTION_DAYS.')
@click.option('--batch-size', type=int, default=1000, show_default=True, help='Rows to delete per transaction.')
@click.option('--dry-run', is_flag=True, help='Report rows that would be purged; do not delete.')
@with_appcontext
def audit_retention_sweep(days, batch_size, dry_run):
    """Purge audit rows older than the configured retention window (L-04).

    Intended for cron/systemd timers, e.g. daily:
      flask audit-retention-sweep --days 365
    """
    retention_days = current_app.config.get('AUDIT_RETENTION_DAYS', 365) if days is None else days
    if retention_days <= 0:
        click.echo('Audit retention purge disabled (days <= 0).')
        return
    if batch_size <= 0:
        raise click.ClickException('batch-size must be positive')

    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    q = AuditLog.query.filter(AuditLog.timestamp < cutoff)
    total = q.count()
    click.echo(f'Audit rows older than {retention_days} days ({cutoff.isoformat()}Z): {total}')
    if dry_run or total == 0:
        if dry_run:
            click.echo('[DRY RUN] No rows deleted.')
        return

    deleted = 0
    while True:
        rows = q.order_by(AuditLog.id).limit(batch_size).all()
        if not rows:
            break
        for row in rows:
            db.session.delete(row)
        db.session.commit()
        deleted += len(rows)
        click.echo(f'  deleted {deleted}/{total}')

    click.echo(f'Purged {deleted} audit rows.')


def register_cli(app):
    """Attach Citadel CLI commands to the Flask app."""
    app.cli.add_command(rotate_keys_sweep)
    app.cli.add_command(audit_retention_sweep)
