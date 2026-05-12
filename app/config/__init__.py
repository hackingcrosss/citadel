import os
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
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('FLASK_ENV') != 'development'

    # Celery
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL')
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND')
