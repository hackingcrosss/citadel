from app import db
from datetime import datetime


class IALandingPage(db.Model):
    __tablename__ = 'ia_landing_pages'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)

    # cred_harvest | payload_delivery | redirect | awareness
    page_type = db.Column(db.String(30), default='cred_harvest')

    # deploying | live | error | torn_down
    status = db.Column(db.String(30), default='draft', index=True)

    # Infrastructure refs
    domain_id = db.Column(db.Integer, db.ForeignKey('domains.id'), nullable=True)
    container_name = db.Column(db.String(200))
    npm_host_id = db.Column(db.Integer)
    fqdn = db.Column(db.String(300))

    # Template / content
    template_source = db.Column(db.String(30), default='manual')  # manual | clone | gophish
    clone_url = db.Column(db.String(500))
    html_content = db.Column(db.Text)

    # GoPhish landing page ID (if pushed to GoPhish)
    gophish_page_id = db.Column(db.Integer)
    capture_credentials = db.Column(db.Boolean, default=True)
    capture_passwords = db.Column(db.Boolean, default=False)
    redirect_url = db.Column(db.String(500))

    deployed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    deployed_at = db.Column(db.DateTime)
    torn_down_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', foreign_keys=[project_id])
    domain = db.relationship('Domain', foreign_keys=[domain_id])
    deployed_by = db.relationship('User', foreign_keys=[deployed_by_id])

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'name': self.name,
            'page_type': self.page_type,
            'status': self.status,
            'domain_id': self.domain_id,
            'domain_name': self.domain.name if self.domain else None,
            'container_name': self.container_name,
            'npm_host_id': self.npm_host_id,
            'fqdn': self.fqdn,
            'template_source': self.template_source,
            'clone_url': self.clone_url,
            'has_html': bool(self.html_content),
            'gophish_page_id': self.gophish_page_id,
            'capture_credentials': self.capture_credentials,
            'capture_passwords': self.capture_passwords,
            'redirect_url': self.redirect_url,
            'deployed_by': self.deployed_by.display_name if self.deployed_by else None,
            'deployed_at': self.deployed_at.isoformat() if self.deployed_at else None,
            'torn_down_at': self.torn_down_at.isoformat() if self.torn_down_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
