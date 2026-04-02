from app import db
from datetime import datetime


class IACampaignEvent(db.Model):
    __tablename__ = 'ia_campaign_events'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('ia_campaigns.id', ondelete='CASCADE'),
                            nullable=False, index=True)
    target_id = db.Column(db.Integer, db.ForeignKey('ia_targets.id', ondelete='SET NULL'),
                          nullable=True, index=True)

    # email_sent | open | click | cred_capture | payload_exec |
    # vishing_attempt | vishing_success | sms_sent | sms_click
    event_type = db.Column(db.String(30), nullable=False, index=True)

    occurred_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    source = db.Column(db.String(30), default='gophish')  # gophish | manual | webhook
    raw_data = db.Column(db.Text)      # JSON blob from GoPhish or manual entry
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    notes = db.Column(db.Text)

    campaign = db.relationship('IACampaign', back_populates='events')
    target = db.relationship('IATarget', foreign_keys=[target_id])

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'campaign_id': self.campaign_id,
            'target_id': self.target_id,
            'target_email': self.target.email if self.target else None,
            'target_name': self.target.full_name if self.target else None,
            'event_type': self.event_type,
            'occurred_at': self.occurred_at.isoformat() if self.occurred_at else None,
            'source': self.source,
            'raw_data': json.loads(self.raw_data) if self.raw_data else None,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'notes': self.notes,
        }
