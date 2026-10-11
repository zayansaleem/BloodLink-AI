import secrets
from datetime import datetime, timezone
from app.extensions import db


def generate_request_reference():
    year = datetime.now(timezone.utc).year
    random_hex = secrets.token_hex(3).upper()
    return f"REQ-{year}-{random_hex}"


class BloodRequest(db.Model):
    """Clinical emergency and planned blood transfusion request issued by verified hospitals."""
    __tablename__ = 'blood_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_reference = db.Column(db.String(32), default=generate_request_reference, unique=True, nullable=False, index=True)
    requesting_organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    blood_group = db.Column(db.String(5), nullable=False)
    component_type = db.Column(db.String(30), default='Whole Blood', nullable=False)
    units_required = db.Column(db.Integer, default=1, nullable=False)
    location = db.Column(db.String(255), nullable=False)
    country = db.Column(db.String(64), default='India', nullable=True)
    state = db.Column(db.String(64), nullable=True)
    district = db.Column(db.String(64), nullable=True)
    city = db.Column(db.String(64), nullable=True)
    postal_code = db.Column(db.String(10), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    urgency_level = db.Column(db.String(20), default='HIGH', nullable=False)  # 'CRITICAL', 'HIGH', 'MEDIUM', 'ROUTINE'
    clinical_deadline = db.Column(db.DateTime, nullable=True)
    verification_status = db.Column(db.String(20), default='PENDING', nullable=False)  # 'PENDING', 'VERIFIED', 'REJECTED'
    request_status = db.Column(db.String(35), default='SUBMITTED', nullable=False)  # 'SUBMITTED', 'ACTIVE_MATCHING', 'BLOOD_BANK_RESPONDED', 'DONOR_RESPONDED', 'PARTIALLY_FULFILLED', 'FULFILLED', 'CANCELLED', 'FLAGGED_FOR_REVIEW'
    priority_score = db.Column(db.Float, default=50.0, nullable=False)
    priority_breakdown = db.Column(db.Text, nullable=True)
    additional_notes = db.Column(db.Text, nullable=True)
    patient_name = db.Column(db.String(120), nullable=True)
    patient_reference = db.Column(db.String(64), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    matches = db.relationship('DonorMatch', backref='blood_request', lazy='dynamic', cascade='all, delete-orphan')
    donations = db.relationship('Donation', backref='blood_request', lazy='dynamic')

    @staticmethod
    def generate_reference():
        return generate_request_reference()

    def hours_elapsed(self):
        created = self.created_at or datetime.now(timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).total_seconds() / 3600.0

    @property
    def is_active(self):
        return self.request_status not in [
            'FULFILLED', 'REJECTED', 'CANCELLED', 'EXPIRED',
            'VALIDATION_FAILED', 'FLAGGED_FOR_REVIEW'
        ]

    @property
    def status_badge(self):
        badges = {
            'SUBMITTED': ('Submitted', 'secondary'),
            'ACTIVE_MATCHING': ('Active Matching', 'primary'),
            'MATCHING': ('Active Matching', 'primary'),
            'VERIFIED': ('Active Matching', 'primary'),
            'OPEN': ('Active Matching', 'primary'),
            'BLOOD_BANK_RESPONDED': ('Blood Bank Responded', 'info text-dark'),
            'DONOR_RESPONDED': ('Donor Responded', 'info text-dark'),
            'PARTIALLY_FULFILLED': ('Partially Fulfilled', 'warning text-dark'),
            'FULFILLED': ('Fulfilled', 'success'),
            'CANCELLED': ('Cancelled', 'secondary'),
            'FLAGGED_FOR_REVIEW': ('Flagged for Review', 'danger'),
            'REJECTED': ('Rejected', 'danger'),
            'VALIDATION_FAILED': ('Validation Failed', 'danger'),
            'ADDITIONAL_INFO_REQUIRED': ('Info Required', 'warning text-dark'),
        }
        return badges.get(self.request_status, (self.request_status, 'secondary'))

    def get_patient_name(self, viewing_user, record_audit=True):
        """Clinical privacy enforcement: Patient name is visible ONLY to requesting hospital staff or audited admins."""
        if not viewing_user or not viewing_user.is_authenticated:
            return None
        if viewing_user.role == 'HOSPITAL':
            org = viewing_user.organization
            if org and org.id == self.requesting_organization_id:
                return self.patient_name
        elif viewing_user.role == 'ADMIN':
            if record_audit and self.patient_name:
                try:
                    from app.models.audit import AuditLog
                    from app.extensions import get_client_ip
                    AuditLog.log(
                        action='ACCESS_PATIENT_RECORD',
                        entity_type='BloodRequest',
                        entity_id=self.id,
                        details=f"Admin accessed patient record for request {self.request_reference}",
                        actor_id=viewing_user.id,
                        ip_address=get_client_ip()
                    )
                except Exception:
                    pass
            return self.patient_name
        return None

    def __repr__(self):
        return f'<BloodRequest {self.request_reference} {self.blood_group} ({self.request_status})>'


class DonorMatch(db.Model):
    """Records preliminary matches and notification dispatch for consenting donors."""
    __tablename__ = 'donor_matches'

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('blood_requests.id', ondelete='CASCADE'), nullable=False)
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    approximate_distance = db.Column(db.Float, nullable=True)
    match_score = db.Column(db.Float, nullable=False)
    match_status = db.Column(db.String(20), default='PRELIMINARY', nullable=False)  # 'PRELIMINARY', 'NOTIFIED', 'ACCEPTED', 'DECLINED'
    score_breakdown = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    donor = db.relationship('User', foreign_keys=[donor_id])

    __table_args__ = (
        db.UniqueConstraint('request_id', 'donor_id', name='uq_request_donor_match'),
    )

    def __repr__(self):
        return f'<DonorMatch Req={self.request_id} Donor={self.donor_id} Score={self.match_score}>'
