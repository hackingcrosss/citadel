"""Smoke test for the rotate-keys-sweep CLI command.

Runs against an isolated tempfile SQLite database so it never touches the real
dev Postgres credentials. Verifies:

  1. set_credential / get_credential round-trip with the primary key.
  2. MultiFernet falls back to MASTER_ENCRYPTION_KEY_LEGACY for legacy ciphertexts.
  3. `flask rotate-keys-sweep` re-encrypts every row with the primary key.
  4. After the sweep, the legacy key alone no longer decrypts any row.
  5. Re-running the sweep is a no-op (idempotent).

Invocation (from the repo root, inside the dev container):

    docker compose exec web python tests/test_rotate_keys_sweep.py
    # or
    docker compose exec web python -m tests.test_rotate_keys_sweep
"""
import os
import sys
import tempfile
from pathlib import Path

# Allow direct invocation from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cryptography.fernet import Fernet


def main():
    # Generate test keys before importing the app — Config snapshots env at import.
    old_key = Fernet.generate_key()
    new_key = Fernet.generate_key()

    # Isolated SQLite DB so the real Postgres credentials are untouched.
    db_fd, db_path = tempfile.mkstemp(suffix='.sqlite', prefix='rotate_test_')
    os.close(db_fd)
    try:
        os.environ['DATABASE_URL'] = f'sqlite:///{db_path}'
        os.environ['MASTER_ENCRYPTION_KEY'] = old_key.decode()
        os.environ.pop('MASTER_ENCRYPTION_KEY_LEGACY', None)
        # Defensively neutralise anything the app might require at import time.
        os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-used-anywhere')
        os.environ.setdefault('FLASK_ENV', 'development')

        from app import create_app, db
        from app.models.credential import Credential
        from app.services.credential_service import set_credential, get_credential

        app = create_app()
        with app.app_context():
            db.create_all()

            # 1. Seed three rows encrypted with OLD.
            set_credential('rotate_test', 'value1', 'plaintext-1', label='unit')
            set_credential('rotate_test', 'value2', 'plaintext-2', label='unit')
            set_credential('rotate_test', 'value3', 'plaintext-3', label='other')
            assert Credential.query.count() == 3, 'expected 3 seeded rows'
            assert get_credential('rotate_test', 'value1', label='unit') == 'plaintext-1'
            print('[+] 3 rows seeded under OLD key; round-trip OK')

            # 2. Re-stage: NEW primary, OLD legacy.
            app.config['MASTER_ENCRYPTION_KEY'] = new_key.decode()
            app.config['MASTER_ENCRYPTION_KEY_LEGACY'] = old_key.decode()

            # 3. Read-through legacy fallback works.
            assert get_credential('rotate_test', 'value1', label='unit') == 'plaintext-1'
            print('[+] read-through legacy key works')

            # 4. Run the sweep.
            runner = app.test_cli_runner()
            result = runner.invoke(args=['rotate-keys-sweep'])
            print(result.output)
            assert result.exit_code == 0, f'sweep exited with {result.exit_code}'
            assert 'rotated=3' in result.output, 'expected 3 rotations in summary line'

            # 5. Drop legacy; reads still work under NEW alone.
            app.config['MASTER_ENCRYPTION_KEY_LEGACY'] = ''
            assert get_credential('rotate_test', 'value1', label='unit') == 'plaintext-1'
            assert get_credential('rotate_test', 'value2', label='unit') == 'plaintext-2'
            assert get_credential('rotate_test', 'value3', label='other') == 'plaintext-3'
            print('[+] post-rotation reads with NEW key alone work')

            # 6. OLD key no longer decrypts any row.
            for cred in Credential.query.all():
                try:
                    Fernet(old_key).decrypt(cred.encrypted_value.encode())
                except Exception:
                    continue
                print(f'[FAIL] OLD key still decrypts cred id={cred.id}', file=sys.stderr)
                sys.exit(1)
            print('[+] OLD key no longer decrypts any row')

            # 7. Idempotency: re-running the sweep rotates 0 rows.
            result2 = runner.invoke(args=['rotate-keys-sweep'])
            print(result2.output)
            assert result2.exit_code == 0
            assert 'rotated=0' in result2.output, 'sweep is not idempotent'
            print('[+] sweep is idempotent on already-rotated rows')

            print('\nALL CHECKS PASSED')
    finally:
        try:
            os.unlink(db_path)
        except FileNotFoundError:
            pass


if __name__ == '__main__':
    main()
