from datetime import datetime, timezone
from app.extensions import db
from app.models.rewards import RewardTransaction, Coupon, CouponRedemption
from app.models.donation import Donation
from app.models.user import User
from app.models.audit import AuditLog
from app.notifications.services import create_notification


from sqlalchemy.exc import IntegrityError

def award_donation_points(donation_id: int, points: int = 100, description: str = None) -> bool:
    """
    Idempotent, transaction-safe credit of reward points for a verified donation.
    Prevents duplicate issuance for the same donation.
    """
    donation = db.session.get(Donation, donation_id)
    if not donation or donation.verification_status != 'VERIFIED':
        return False

    # Prevent duplicate issuance for the exact same donation
    existing = RewardTransaction.query.filter_by(donation_id=donation.id).first()
    if existing:
        return False

    desc = description or f"Points awarded for verified blood donation #{donation.id}"

    try:
        tx = RewardTransaction(
            donor_id=donation.donor_id,
            donation_id=donation.id,
            points=points,
            transaction_type='CREDIT',
            description=desc,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(tx)

        # Audit log entry
        AuditLog.log(
            action='AWARD_POINTS',
            entity_type='Donation',
            entity_id=donation.id,
            details=f"Credited {points} pts to Donor {donation.donor_id}",
            actor_id=donation.verified_by
        )

        db.session.commit()

        # Send notification
        create_notification(
            recipient_id=donation.donor_id,
            notification_type='POINTS_CREDITED',
            title='Reward Points Credited!',
            message=f"You have been awarded {points} points for your verified donation. Thank you for saving lives!"
        )
        return True
    except IntegrityError:
        db.session.rollback()
        # Duplicate transaction race condition trapped by DB unique constraint
        return False
    except Exception as e:
        db.session.rollback()
        print(f"[Reward Error]: {e}")
        return False


def redeem_coupon(donor_id: int, coupon_id: int) -> tuple[bool, str, str]:
    """
    Safely redeem a coupon by deducting points and generating a voucher code.
    Prevents concurrent balance manipulation and overspending.
    Returns: (success: bool, message: str, code: str or None)
    """
    user = db.session.get(User, donor_id)
    coupon = db.session.get(Coupon, coupon_id)

    if not user or not coupon:
        return False, "Invalid donor or coupon reference.", None

    if not coupon.is_available:
        return False, "This coupon offer is currently expired or inactive.", None

    # Server-side balance verification
    current_balance = user.reward_balance
    if current_balance < coupon.points_required:
        return False, f"Insufficient balance. You need {coupon.points_required} pts, but have {current_balance} pts.", None

    voucher_code = CouponRedemption.generate_code()

    try:
        # Atomic negative ledger entry
        tx = RewardTransaction(
            donor_id=user.id,
            donation_id=None,
            points=-coupon.points_required,
            transaction_type='REDEMPTION',
            description=f"Redemption of '{coupon.title}' ({coupon.partner_name})",
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(tx)

        redemption = CouponRedemption(
            donor_id=user.id,
            coupon_id=coupon.id,
            redemption_code=voucher_code,
            redemption_status='ACTIVE',
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(redemption)

        AuditLog.log(
            action='REDEEM_COUPON',
            entity_type='Coupon',
            entity_id=coupon.id,
            details=f"Donor {user.id} redeemed code {voucher_code} for {coupon.points_required} pts",
            actor_id=user.id
        )

        db.session.commit()

        create_notification(
            recipient_id=user.id,
            notification_type='COUPON_REDEEMED',
            title='Coupon Redeemed Successfully',
            message=f"Your coupon '{coupon.title}' is ready. Voucher Code: {voucher_code}"
        )

        return True, "Coupon successfully claimed!", voucher_code
    except Exception as e:
        db.session.rollback()
        return False, f"Transaction error: {str(e)}", None
