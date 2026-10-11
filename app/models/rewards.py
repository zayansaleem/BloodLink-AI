import secrets
from datetime import datetime, timezone
from app.extensions import db


class RewardTransaction(db.Model):
    """Immutable ledger recording all points credited, redeemed, or reversed."""
    __tablename__ = 'reward_transactions'

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    donation_id = db.Column(db.Integer, db.ForeignKey('donations.id'), unique=True, nullable=True)
    points = db.Column(db.Integer, nullable=False)  # Positive for credit, negative for redemption
    transaction_type = db.Column(db.String(20), nullable=False)  # 'CREDIT', 'REDEMPTION', 'REVERSAL', 'BONUS'
    description = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f'<RewardTransaction Donor={self.donor_id} Pts={self.points} Type={self.transaction_type}>'


class Coupon(db.Model):
    """Available perks and coupons redeemable by donors using points."""
    __tablename__ = 'coupons'

    id = db.Column(db.Integer, primary_key=True)
    partner_name = db.Column(db.String(120), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    points_required = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(50), default='Health & Wellness', nullable=False)  # 'Juice', 'Food', 'Restaurant', 'Shopping', 'Pharmacy'
    coupon_status = db.Column(db.String(20), default='ACTIVE', nullable=False)  # 'ACTIVE', 'EXPIRED', 'INACTIVE'
    expiry_date = db.Column(db.DateTime, nullable=True)
    icon = db.Column(db.String(50), default='bi-gift', nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    redemptions = db.relationship('CouponRedemption', backref='coupon', lazy='dynamic')

    @property
    def is_available(self):
        if self.coupon_status != 'ACTIVE':
            return False
        if self.expiry_date:
            exp = self.expiry_date
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                return False
        return True

    def __repr__(self):
        return f'<Coupon {self.title} ({self.points_required} pts)>'


class CouponRedemption(db.Model):
    """Unique voucher issued upon successful points deduction."""
    __tablename__ = 'coupon_redemptions'

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupons.id', ondelete='CASCADE'), nullable=False)
    redemption_status = db.Column(db.String(20), default='ACTIVE', nullable=False)  # 'ACTIVE', 'USED', 'EXPIRED'
    redemption_code = db.Column(db.String(32), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    @staticmethod
    def generate_code():
        return f"BL-{secrets.token_hex(4).upper()}"

    def __repr__(self):
        return f'<CouponRedemption {self.redemption_code} Donor={self.donor_id}>'
