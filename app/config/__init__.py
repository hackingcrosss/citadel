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
    
    # Celery
    CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL')
    CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND')