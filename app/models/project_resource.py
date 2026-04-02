from app import db
from datetime import datetime

RESOURCE_TYPES = ('ec2', 'container', 'cs_listener', 'npm_host', 'ia_campaign', 'ia_scan_job')


class ProjectResource(db.Model):
    __tablename__ = 'project_resources'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    resource_type = db.Column(db.String(30), nullable=False, index=True)  # ec2 | container | cs_listener | npm_host
    external_id = db.Column(db.String(255), nullable=False, index=True)   # instance_id / container name / listener name / npm host id
    label = db.Column(db.String(255))                                      # human-readable display name
    tagged_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    tagged_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project')
    tagged_by = db.relationship('User', foreign_keys=[tagged_by_id])

    __table_args__ = (
        db.UniqueConstraint('project_id', 'resource_type', 'external_id',
                            name='uq_project_resource'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'resource_type': self.resource_type,
            'external_id': self.external_id,
            'label': self.label or '',
            'tagged_by_id': self.tagged_by_id,
            'tagged_at': self.tagged_at.isoformat() if self.tagged_at else None,
        }

    def __repr__(self):
        return f'<ProjectResource project={self.project_id} {self.resource_type}:{self.external_id}>'
