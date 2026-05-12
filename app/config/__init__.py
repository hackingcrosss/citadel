import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    _secret_key = os.getenv('SECRET_KEY')
    if not _secret_key:
        _flask_env = os.getenv('FLASK_ENV', 'production')
        if _flask_env == 'production':
            raise RuntimeError('SECRET_KEY environment variable must be set in production')
        _secret_key = 'dev-insecure-key-DO-NOT-USE-IN-PRODUCTION'
    SECRET_KEY = _secret_key
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MASTER_ENCRYPTION_KEY = os.getenv('MASTER_ENCRYPTION_KEY')
    # Comma-separated previous keys, used only during a rotation window so legacy
    # ciphertexts remain readable until `flask rotate-keys-sweep` migrates them.
    # Drop back to empty once the sweep reports zero un-rotated rows.
    MASTER_ENCRYPTION_KEY_LEGACY = os.getenv('MASTER_ENCRYPTION_KEY_LEGACY', '')

    # Session cookie hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('FLASK_ENV') != 'development'

    # Celery
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL')
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND')