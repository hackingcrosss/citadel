"""Flask CLI commands for Citadel operational tasks."""
import click
from cryptography.fernet import InvalidToken
from flask.cli import with_appcontext

from app import db
from app.models.credential import Credential
from app.models.instance_ssh_config import InstanceSSHConfig
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


def register_cli(app):
    """Attach Citadel CLI commands to the Flask app."""
    app.cli.add_command(rotate_keys_sweep)
