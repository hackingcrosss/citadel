from app import db
from datetime import datetime


class InstanceTag(db.Model):
    __tablename__ = 'instance_tags'

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False, default='aws')
    instance_id = db.Column(db.String(30), nullable=False, index=True)
    tag = db.Column(db.String(100), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('provider', 'instance_id', 'tag', name='uq_provider_instance_tag'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'provider': self.provider,
            'instance_id': self.instance_id,
            'tag': self.tag,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<InstanceTag {self.provider}:{self.instance_id}:{self.tag}>'
