import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.organization import Organization
from app.models.donation import Donation
from app.models.rewards import RewardTransaction, Coupon, CouponRedemption
from app.rewards.services import award_donation_points, redeem_coupon


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


class TestRewardLedgerAndRedemptions:
    """Tests for secure reward issuance, duplicate prevention, and coupon redemption."""

    def test_award_points_and_duplicate_prevention(self, app):
        donor = User(name="Donor Test", email="donor@test.com", role="DONOR")
        donor.set_password("pass")
        bank = Organization(
            organization_name="Test Bank", organization_type="BLOOD_BANK",
            address="Addr", contact_phone="123", verification_status="VERIFIED"
        )
        db.session.add_all([donor, bank])
        db.session.commit()

        # Unverified donation cannot earn points
        don_pending = Donation(
            donor_id=donor.id, blood_bank_id=bank.id, units=1,
            verification_status="PENDING"
        )
        db.session.add(don_pending)
        db.session.commit()

        assert award_donation_points(don_pending.id, 100) is False
        assert donor.reward_balance == 0

        # Mark verified
        don_pending.verification_status = "VERIFIED"
        db.session.commit()

        # Award points
        assert award_donation_points(don_pending.id, 100) is True
        assert donor.reward_balance == 100

        # Prevent duplicate rewards for the exact same donation
        assert award_donation_points(don_pending.id, 100) is False
        assert donor.reward_balance == 100

    def test_coupon_redemption_and_balance_enforcement(self, app):
        donor = User(name="Donor Buyer", email="buyer@test.com", role="DONOR")
        donor.set_password("pass")
        coupon = Coupon(
            partner_name="Partner A", title="Health Check", description="Desc",
            points_required=150, coupon_status="ACTIVE"
        )
        db.session.add_all([donor, coupon])
        db.session.commit()

        # Insufficient points
        ok, msg, code = redeem_coupon(donor.id, coupon.id)
        assert ok is False
        assert code is None
        assert "insufficient" in msg.lower()

        # Credit points
        tx = RewardTransaction(donor_id=donor.id, points=200, transaction_type="CREDIT", description="Credit")
        db.session.add(tx)
        db.session.commit()
        assert donor.reward_balance == 200

        # Now redeem successfully
        ok, msg, code = redeem_coupon(donor.id, coupon.id)
        assert ok is True
        assert code is not None
        assert code.startswith("BL-")
        # Balance should now be 50
        assert donor.reward_balance == 50

    def test_expired_coupon_rejected(self, app):
        donor = User(name="Donor Exp", email="exp@test.com", role="DONOR")
        donor.set_password("pass")
        # Expired yesterday
        coupon_exp = Coupon(
            partner_name="Partner B", title="Expired Perk", description="Desc",
            points_required=50, coupon_status="ACTIVE",
            expiry_date=datetime.now(timezone.utc) - timedelta(days=1)
        )
        db.session.add_all([donor, coupon_exp])
        db.session.commit()

        tx = RewardTransaction(donor_id=donor.id, points=100, transaction_type="CREDIT", description="Credit")
        db.session.add(tx)
        db.session.commit()

        ok, msg, code = redeem_coupon(donor.id, coupon_exp.id)
        assert ok is False
        assert "expired" in msg.lower()
