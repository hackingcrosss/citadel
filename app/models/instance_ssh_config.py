from app import db
from datetime import datetime


class InstanceSSHConfig(db.Model):
    __tablename__ = 'instance_ssh_configs'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False, default='aws')
    instance_id = db.Column(db.String(30), nullable=False, index=True)
    ssh_username = db.Column(db.String(100), nullable=False, default='ec2-user')
    encrypted_private_key = db.Column(db.Text, nullable=False)
    use_public_ip = db.Column(db.Boolean, default=True)
    key_label = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('provider', 'instance_id', name='uq_provider_instance_ssh'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'instance_id': self.instance_id,
            'ssh_username': self.ssh_username,
            'use_public_ip': self.use_public_ip,
            'key_label': self.key_label or '',
            'has_key': True,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<InstanceSSHConfig {self.provider}:{self.instance_id}>'
