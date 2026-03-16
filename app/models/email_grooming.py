from app import db
from datetime import datetime


class EmailGroomingConfig(db.Model):
    __tablename__ = 'email_grooming_configs'

    id = db.Column(db.Integer, primary_key=True)
    domain_id = db.Column(db.Integer, db.ForeignKey('domains.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    target_email = db.Column(db.String(255), nullable=False)
    emails_per_day = db.Column(db.Integer, nullable=False, default=10)
    gophish_profile_id = db.Column(db.Integer, nullable=True)  # NULL = rotate across all matching profiles
    status = db.Column(db.String(20), nullable=False, default='active')  # active, paused, completed
    emails_sent = db.Column(db.Integer, nullable=False, default=0)
    last_sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    domain = db.relationship('Domain', backref='email_grooming_configs')

    __table_args__ = (
        db.UniqueConstraint('domain_id', 'target_email', name='uq_grooming_domain_target'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'domain_id': self.domain_id,
            'domain_name': self.domain.name if self.domain else None,
            'target_email': self.target_email,
            'emails_per_day': self.emails_per_day,
            'gophish_profile_id': self.gophish_profile_id,
            'status': self.status,
            'emails_sent': self.emails_sent,
            'last_sent_at': self.last_sent_at.isoformat() if self.last_sent_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<EmailGroomingConfig {self.domain.name if self.domain else "?"} -> {self.target_email}>'
