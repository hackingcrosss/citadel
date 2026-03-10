from app import db
from datetime import datetime

PROJECT_ROLES = ('operator', 'white_team')
PROJECT_STATUSES = ('active', 'archived')


class Project(db.Model):
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(30), unique=True, nullable=False, index=True)  # e.g. "OP-ACME-2026"
    description = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default='active')  # active | archived
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    members = db.relationship('ProjectMember', back_populates='project',
                              cascade='all, delete-orphan')

    def to_dict(self, include_members=False):
        d = {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'description': self.description,
            'status': self.status,
            'created_by_id': self.created_by_id,
            'created_by_email': self.created_by.email if self.created_by else None,
            'member_count': len(self.members),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_members:
            d['members'] = [m.to_dict() for m in self.members]
        return d

    def __repr__(self):
        return f'<Project {self.code}>'


class ProjectMember(db.Model):
    __tablename__ = 'project_members'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    project_role = db.Column(db.String(20), nullable=False, default='operator')  # operator | white_team
    added_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', back_populates='members')
    user = db.relationship('User', foreign_keys=[user_id])
    added_by = db.relationship('User', foreign_keys=[added_by_id])

    __table_args__ = (
        db.UniqueConstraint('project_id', 'user_id', name='uq_project_member'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'user_id': self.user_id,
            'user_email': self.user.email if self.user else None,
            'user_display_name': self.user.display_name if self.user else None,
            'project_role': self.project_role,
            'added_by_id': self.added_by_id,
            'added_at': self.added_at.isoformat() if self.added_at else None,
        }

    def __repr__(self):
        return f'<ProjectMember project={self.project_id} user={self.user_id} role={self.project_role}>'
