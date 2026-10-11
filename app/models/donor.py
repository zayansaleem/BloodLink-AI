from datetime import datetime, date, timezone
from app.extensions import db


class DonorProfile(db.Model):
    """Profile model storing voluntary donor information and privacy preferences."""
    __tablename__ = 'donor_profiles'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    declared_blood_group = db.Column(db.String(5), nullable=False)  # 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'
    country = db.Column(db.String(64), default='India', nullable=True)
    state = db.Column(db.String(64), nullable=True)
    district = db.Column(db.String(64), nullable=True)
    city = db.Column(db.String(64), nullable=True)
    postal_code = db.Column(db.String(10), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    availability_status = db.Column(db.Boolean, default=True, nullable=False)
    notification_consent = db.Column(db.Boolean, default=True, nullable=False)
    verification_status = db.Column(db.String(35), default='APPROVED', nullable=False)  # 'PENDING_VERIFICATION', 'APPROVED', 'REJECTED', 'SUSPENDED'
    is_demo = db.Column(db.Boolean, default=False, nullable=True)
    last_donation_date = db.Column(db.Date, nullable=True)
    next_eligible_date = db.Column(db.Date, nullable=True)
    clinical_review_required = db.Column(db.Boolean, default=False, nullable=True)
    recovery_period_days = db.Column(db.Integer, default=56, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    def is_eligible_to_donate(self, cooldown_days=None):
        """
        Clinical eligibility check respecting configured recovery duration and review dates.
        Returns: (is_eligible: bool, days_remaining: int)
        """
        if not self.availability_status:
            return False, 0
        if self.verification_status not in ('APPROVED', 'VERIFIED'):
            return False, 0
        if self.clinical_review_required:
            return False, 0
        if not self.last_donation_date:
            return True, 0

        from datetime import timedelta
        last_dt = self.last_donation_date
        if isinstance(last_dt, datetime):
            last_dt = last_dt.date()

        if self.next_eligible_date:
            effective_next_date = self.next_eligible_date
            if isinstance(effective_next_date, datetime):
                effective_next_date = effective_next_date.date()
        else:
            days = cooldown_days if cooldown_days is not None else (self.recovery_period_days or 56)
            effective_next_date = last_dt + timedelta(days=days)

        today = date.today()
        if today < effective_next_date:
            return False, (effective_next_date - today).days

        return True, 0

    def get_clinical_status(self) -> dict:
        """
        Calculates donor clinical availability/recovery state for display and matching.
        Distinguishes:
        - AVAILABLE_FOR_MATCHING
        - TEMPORARILY_UNAVAILABLE
        - INVITATION_ACCEPTED
        - DONATION_PENDING_VERIFICATION
        - DONATION_VERIFIED
        - RECOVERY_RESTRICTION_ACTIVE
        - ELIGIBILITY_REVIEW_REQUIRED
        """
        today = date.today()
        from app.models.donation import Donation
        from app.models.communication import DonorRequestResponse, DonorInvitation
        from app.models.request import BloodRequest

        # 1. Verification incomplete / suspended
        if self.verification_status not in ('APPROVED', 'VERIFIED'):
            return {
                'status': 'ELIGIBILITY_REVIEW_REQUIRED',
                'label': 'Eligibility Review Required',
                'badge_class': 'bg-warning text-dark',
                'description': 'Profile identity verification is pending or requires compliance review.',
                'can_donate': False,
                'days_remaining': 0,
                'next_date': None
            }

        # 2. Donor standby toggled off
        if not self.availability_status:
            return {
                'status': 'TEMPORARILY_UNAVAILABLE',
                'label': 'Temporarily Unavailable',
                'badge_class': 'bg-secondary',
                'description': 'Standby availability is paused. Toggle status to ready to receive opportunities.',
                'can_donate': False,
                'days_remaining': 0,
                'next_date': None
            }

        # 3. Check for pending donation intake
        pending_donation = Donation.query.filter_by(
            donor_id=self.user_id,
            verification_status='PENDING'
        ).first()
        if pending_donation:
            return {
                'status': 'DONATION_PENDING_VERIFICATION',
                'label': 'Donation Pending Verification',
                'badge_class': 'bg-info text-dark',
                'description': 'Recent donation recorded; awaiting laboratory certification from collection facility.',
                'can_donate': False,
                'days_remaining': 0,
                'next_date': None
            }

        # 4. Check for active confirmed response to ongoing request
        active_accepted = DonorRequestResponse.query.filter_by(
            donor_id=self.user_id,
            response_status='CONFIRMED'
        ).join(BloodRequest).filter(
            BloodRequest.request_status.notin_(['FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED'])
        ).first()
        if active_accepted:
            return {
                'status': 'INVITATION_ACCEPTED',
                'label': 'Invitation Accepted',
                'badge_class': 'bg-primary',
                'description': 'You have accepted an active hospital invitation. Awaiting facility arrival & screening.',
                'can_donate': False,
                'days_remaining': 0,
                'next_date': None
            }

        # 5. Check active recovery restriction (post-donation cooldown)
        if self.last_donation_date:
            from datetime import timedelta
            last_dt = self.last_donation_date
            if isinstance(last_dt, datetime):
                last_dt = last_dt.date()

            effective_next = self.next_eligible_date or (last_dt + timedelta(days=self.recovery_period_days or 56))
            if isinstance(effective_next, datetime):
                effective_next = effective_next.date()

            if today < effective_next:
                days_left = (effective_next - today).days
                return {
                    'status': 'RECOVERY_RESTRICTION_ACTIVE',
                    'label': 'Recovery Restriction Active',
                    'badge_class': 'bg-danger bg-opacity-75',
                    'description': f"Clinical physiological recovery in progress ({days_left} days remaining until {effective_next.strftime('%d %b %Y')}).",
                    'can_donate': False,
                    'days_remaining': days_left,
                    'next_date': effective_next
                }

        # 6. Flagged for clinical review
        if self.clinical_review_required:
            return {
                'status': 'ELIGIBILITY_REVIEW_REQUIRED',
                'label': 'Eligibility Review Required',
                'badge_class': 'bg-warning text-dark',
                'description': 'Recovery duration elapsed; health questionnaire & clinical check required prior to matching.',
                'can_donate': False,
                'days_remaining': 0,
                'next_date': None
            }

        # 7. Check if past donations exist (verified) vs first-time donor
        past_verified_count = Donation.query.filter_by(
            donor_id=self.user_id,
            verification_status='VERIFIED'
        ).count()

        if past_verified_count > 0:
            return {
                'status': 'AVAILABLE_FOR_MATCHING',
                'label': 'Available for Matching (Verified Donor)',
                'badge_class': 'bg-success',
                'description': f'Eligible and ready for emergency matching. {past_verified_count} verified lifesaver donation(s) on record.',
                'can_donate': True,
                'days_remaining': 0,
                'next_date': None
            }

        # 8. First time available donor
        return {
            'status': 'AVAILABLE_FOR_MATCHING',
            'label': 'Available for Matching',
            'badge_class': 'bg-success',
            'description': 'Registered voluntary donor on active standby for emergency matching.',
            'can_donate': True,
            'days_remaining': 0,
            'next_date': None
        }

    def __repr__(self):
        return f'<DonorProfile User={self.user_id} ({self.declared_blood_group})>'
