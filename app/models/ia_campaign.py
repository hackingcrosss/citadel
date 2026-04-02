from app import db
from datetime import datetime


# Many-to-many join table: campaigns <-> targets
ia_campaign_targets = db.Table(
    'ia_campaign_targets',
    db.Column('campaign_id', db.Integer, db.ForeignKey('ia_campaigns.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('target_id', db.Integer, db.ForeignKey('ia_targets.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('added_at', db.DateTime, default=datetime.utcnow),
)


class IACampaign(db.Model):
    __tablename__ = 'ia_campaigns'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    vector = db.Column(db.String(30), default='phishing')  # phishing | vishing | smishing
    status = db.Column(db.String(30), default='draft', index=True)  # draft | active | paused | completed | archived

    # Infrastructure links
    domain_id = db.Column(db.Integer, db.ForeignKey('domains.id'), nullable=True)
    gophish_campaign_id = db.Column(db.Integer)       # GoPhish campaign ID once launched
    gophish_smtp_id = db.Column(db.Integer)           # GoPhish sending profile ID
    landing_page_id = db.Column(db.Integer)           # FK to ia_landing_pages (Phase 5)

    # Scheduling + RoE
    scheduled_start = db.Column(db.DateTime)
    scheduled_end = db.Column(db.DateTime)
    roe_enforced = db.Column(db.Boolean, default=True)

    # Denormalized stats (updated on sync)
    targets_count = db.Column(db.Integer, default=0)
    emails_sent = db.Column(db.Integer, default=0)
    opens_count = db.Column(db.Integer, default=0)
    clicks_count = db.Column(db.Integer, default=0)
    creds_captured = db.Column(db.Integer, default=0)
    payloads_executed = db.Column(db.Integer, default=0)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = db.relationship('Project', foreign_keys=[project_id])
    domain = db.relationship('Domain', foreign_keys=[domain_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    targets = db.relationship('IATarget', secondary=ia_campaign_targets,
                              backref=db.backref('campaigns', lazy='dynamic'),
                              lazy='dynamic')
    events = db.relationship('IACampaignEvent', back_populates='campaign',
                             cascade='all, delete-orphan', order_by='IACampaignEvent.occurred_at.desc()')

    def to_dict(self, include_targets=False):
        d = {
            'id': self.id,
            'project_id': self.project_id,
            'name': self.name,
            'vector': self.vector,
            'status': self.status,
            'domain_id': self.domain_id,
            'domain_name': self.domain.name if self.domain else None,
            'gophish_campaign_id': self.gophish_campaign_id,
            'gophish_smtp_id': self.gophish_smtp_id,
            'landing_page_id': self.landing_page_id,
            'scheduled_start': self.scheduled_start.isoformat() if self.scheduled_start else None,
            'scheduled_end': self.scheduled_end.isoformat() if self.scheduled_end else None,
            'roe_enforced': self.roe_enforced,
            'targets_count': self.targets_count,
            'emails_sent': self.emails_sent,
            'opens_count': self.opens_count,
            'clicks_count': self.clicks_count,
            'creds_captured': self.creds_captured,
            'payloads_executed': self.payloads_executed,
            'created_by': self.created_by.display_name if self.created_by else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_targets:
            d['targets'] = [t.to_dict() for t in self.targets.all()]
        return d
