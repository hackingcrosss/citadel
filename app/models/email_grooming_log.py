from app import db
from datetime import datetime


class EmailGroomingLog(db.Model):
    __tablename__ = 'email_grooming_logs'

    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey('email_grooming_configs.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    sent_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    from_address = db.Column(db.String(255), nullable=False)
    to_address = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(500), nullable=False)
    success = db.Column(db.Boolean, nullable=False, default=True)
    error_message = db.Column(db.Text, nullable=True)
    gophish_profile_id = db.Column(db.Integer, nullable=True)

    config = db.relationship('EmailGroomingConfig', backref='send_logs')

    def to_dict(self):
        return {
            'id': self.id,
            'config_id': self.config_id,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'from_address': self.from_address,
            'to_address': self.to_address,
            'subject': self.subject,
            'success': self.success,
            'error_message': self.error_message,
            'gophish_profile_id': self.gophish_profile_id,
        }
