from datetime import datetime, timezone
from app.extensions import db


class Donation(db.Model):
    """Verified blood donation records linking donors, blood banks, and verifying staff."""
    __tablename__ = 'donations'

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    blood_bank_id = db.Column(db.Integer, db.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey('blood_requests.id'), nullable=True)
    units = db.Column(db.Integer, default=1, nullable=False)
    component_type = db.Column(db.String(30), default='Whole Blood', nullable=False)
    donation_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    verification_status = db.Column(db.String(20), default='PENDING', nullable=False)  # 'PENDING', 'VERIFIED', 'REJECTED'
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_demo = db.Column(db.Boolean, default=False, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    reward_transactions = db.relationship('RewardTransaction', backref='donation', lazy='dynamic')

    def __repr__(self):
        return f'<Donation #{self.id} Donor={self.donor_id} Org={self.blood_bank_id} Status={self.verification_status}>'
