from app import db
from datetime import datetime


class Credential(db.Model):
    __tablename__ = 'credentials'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False, index=True)
    label = db.Column(db.String(100), nullable=False, default='default')
    key_name = db.Column(db.String(100), nullable=False)
    encrypted_value = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('provider', 'label', 'key_name', name='uq_provider_label_key'),
    )

    def __repr__(self):
        return f'<Credential {self.provider}/{self.label}/{self.key_name}>'
