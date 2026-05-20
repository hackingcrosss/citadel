import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


_BANNED_SECRET_KEYS = {
    '',
    'CHANGE_ME',
    'dev-insecure-key-DO-NOT-USE-IN-PRODUCTION',
    # Value historically shipped in the maldev branch's .env. Anyone with a
    # checkout / backup / CI workspace from that branch has this value; treat
    # as permanently compromised.
    '64d7b2032c6c8ff0319ac27fd9408572a7961673b4954d952e94146463d782bf',
}
_BANNED_MASTER_KEYS = {
    '',
    'CHANGE_ME',
    # Value historically shipped in the maldev branch's .env (see note above).
    'yHUTPBJ9E22Vc8uzEzIKddt8A8bSPp3mCKbeP2uz2pE=',
}


def _require_secret(name, value, banned):
    # Fail-fast if a critical env var is unset or matches a known-leaked /
    # placeholder value. Replaces the silent dev fallback that used to substitute
    # 'dev-insecure-key-DO-NOT-USE-IN-PRODUCTION' when SECRET_KEY was missing.
    if value is None or value.strip() in banned:
        raise RuntimeError(
            f'{name} is not set or matches a known-leaked / placeholder value. '
            f'Run ./setup.sh to generate a fresh .env, then recreate the '
            f'containers with `docker compose up -d --force-recreate`.'
        )


_secret_key = os.getenv('SECRET_KEY')
_require_secret('SECRET_KEY', _secret_key, _BANNED_SECRET_KEYS)
_master_key = os.getenv('MASTER_ENCRYPTION_KEY')
_require_secret('MASTER_ENCRYPTION_KEY', _master_key, _BANNED_MASTER_KEYS)


def _refuse_docker_socket_in_prod():
    # M-03 belt-and-suspenders: production uses a remote Docker host
    # configured per-deployment via Settings → Docker → Host URL. A
    # bind-mounted /var/run/docker.sock turns any in-container RCE
    # into host root, so refuse to start in production if the socket
    # somehow reappeared (rogue compose override, manual volume add).
    if os.getenv('FLASK_ENV') == 'production' and os.path.exists('/var/run/docker.sock'):
        raise RuntimeError(
            '/var/run/docker.sock is bind-mounted into this container but FLASK_ENV=production. '
            'The Docker socket bind-mount is a container-escape primitive — any in-container RCE '
            'becomes host root. Remove the volume entry from docker-compose.yml; production should '
            'point at a remote Docker host via Settings → Docker → Host URL. For local development '
            'that genuinely needs the mount, run with FLASK_ENV=development.'
        )


_refuse_docker_socket_in_prod()


class Config:
    SECRET_KEY = _secret_key
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MASTER_ENCRYPTION_KEY = _master_key
    # Comma-separated previous keys, used only during a rotation window so legacy
    # ciphertexts remain readable until `flask rotate-keys-sweep` migrates them.
    # Drop back to empty once the sweep reports zero un-rotated rows.
    MASTER_ENCRYPTION_KEY_LEGACY = os.getenv('MASTER_ENCRYPTION_KEY_LEGACY', '')

    # Bumping SESSION_COOKIE_NAME during a SECRET_KEY rotation (e.g. session →
    # session_v2) forces every operator to re-authenticate cleanly — old cookies
    # are simply ignored under the new name rather than failing signature
    # verification. Leave at 'session' in steady state.
    SESSION_COOKIE_NAME = os.getenv('SESSION_COOKIE_NAME', 'session')
    SESSION_COOKIE_HTTPONLY = True

    SESSION_COOKIE_SAMESITE = 'Strict'
    SESSION_COOKIE_SECURE = os.getenv('FLASK_ENV') != 'development'
    REMEMBER_COOKIE_SECURE = os.getenv('FLASK_ENV') != 'development'
    # Flask-WTF CSRF
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour token lifetime

    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Strict')
    SESSION_COOKIE_SECURE = os.getenv('FLASK_ENV') != 'development'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.getenv('SESSION_LIFETIME_HOURS', '8')))
    SESSION_REFRESH_EACH_REQUEST = True

    # Flask-Login persistent "remember me" cookie. Keep it shorter than the
    # previous 1-year framework default and bind it to HTTPS/SameSite in prod.
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_SAMESITE = os.getenv('REMEMBER_COOKIE_SAMESITE', 'Strict')
    REMEMBER_COOKIE_DURATION = timedelta(days=int(os.getenv('REMEMBER_COOKIE_DAYS', '14')))
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = False
    SESSION_PROTECTION = 'strong'

    # Audit retention. Use `flask audit-retention-sweep` from cron/systemd to
    # purge rows older than this many days; set to 0 to disable purging.
    AUDIT_RETENTION_DAYS = int(os.getenv('AUDIT_RETENTION_DAYS', '365'))

    # Celery
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL')
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND')
