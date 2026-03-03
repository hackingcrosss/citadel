from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from app import db
from app.models.credential import Credential


def _get_fernet():
    key = current_app.config['MASTER_ENCRYPTION_KEY']
    if not key:
        raise ValueError("MASTER_ENCRYPTION_KEY not configured")
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def set_credential(provider, key_name, plaintext_value, label='default'):
    f = _get_fernet()
    encrypted = f.encrypt(plaintext_value.encode()).decode()

    cred = Credential.query.filter_by(provider=provider, label=label, key_name=key_name).first()
    if cred:
        cred.encrypted_value = encrypted
    else:
        cred = Credential(provider=provider, label=label, key_name=key_name, encrypted_value=encrypted)
        db.session.add(cred)

    db.session.commit()
    return cred


def get_credential(provider, key_name, label='default'):
    cred = Credential.query.filter_by(provider=provider, label=label, key_name=key_name).first()
    if not cred:
        return None

    f = _get_fernet()
    try:
        return f.decrypt(cred.encrypted_value.encode()).decode()
    except InvalidToken:
        return None


def get_all_for_provider(provider):
    """Return credentials grouped by label: {label: {key_name: {exists, masked, updated_at}}}"""
    creds = Credential.query.filter_by(provider=provider).order_by(Credential.label, Credential.key_name).all()
    result = {}
    f = _get_fernet()
    for c in creds:
        try:
            plain = f.decrypt(c.encrypted_value.encode()).decode()
            if len(plain) > 10:
                masked = plain[:4] + '*' * (len(plain) - 8) + plain[-4:]
            else:
                masked = '****'
        except InvalidToken:
            masked = '[DECRYPTION ERROR]'
        result.setdefault(c.label, {})[c.key_name] = {
            'exists': True,
            'masked': masked,
            'updated_at': c.updated_at.isoformat() if c.updated_at else None,
        }
    return result


def get_account_labels(provider):
    """Return a sorted list of distinct account labels for a provider."""
    rows = (
        db.session.query(Credential.label)
        .filter_by(provider=provider)
        .distinct()
        .order_by(Credential.label)
        .all()
    )
    return [r.label for r in rows]


def delete_credential(provider, key_name, label='default'):
    cred = Credential.query.filter_by(provider=provider, label=label, key_name=key_name).first()
    if cred:
        db.session.delete(cred)
        db.session.commit()
        return True
    return False


def delete_account(provider, label):
    """Delete all credentials for a (provider, label) pair."""
    creds = Credential.query.filter_by(provider=provider, label=label).all()
    if not creds:
        return False
    for c in creds:
        db.session.delete(c)
    db.session.commit()
    return True
