from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

VALID_ROLES = ('admin', 'project_admin', 'operator', 'white_team', 'auditor')

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    role = db.Column(db.String(20), nullable=False, default='operator')
    plan_override = db.Column(db.String(20), nullable=True)   # None = inherit global license
    must_change_password = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # white_team users belong to exactly one company
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True, index=True)
    company = db.relationship('Company', foreign_keys=[company_id])

    # Back-reference to project memberships — avoids circular import by using string ref
    project_memberships = db.relationship(
        'ProjectMember',
        foreign_keys='ProjectMember.user_id',
        back_populates='user',
        lazy='dynamic',
    )

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_project_admin(self):
        return self.role == 'project_admin'

    @property
    def is_operator(self):
        return self.role == 'operator'

    @property
    def is_white_team(self):
        return self.role == 'white_team'

    @property
    def is_auditor(self):
        return self.role == 'auditor'

    @property
    def can_write_infra(self):
        return self.role in ('admin', 'operator')

    @property
    def can_manage_projects(self):
        return self.role in ('admin', 'project_admin')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.email}>'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))