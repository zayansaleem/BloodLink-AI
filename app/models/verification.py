from datetime import datetime, timezone
from app.extensions import db


class VerificationApplication(db.Model):
    """Administrative verification record for donor identities, hospital licenses, and blood bank registries."""
    __tablename__ = 'verification_applications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id', ondelete='SET NULL'), nullable=True)
    verification_type = db.Column(db.String(20), nullable=False)  # 'DONOR', 'HOSPITAL', 'BLOOD_BANK'
    verification_status = db.Column(
        db.String(35),
        default='PENDING_VERIFICATION',
        nullable=False
    )  # 'PENDING_VERIFICATION', 'APPROVED', 'REJECTED', 'SUSPENDED', 'ADDITIONAL_INFO_REQUESTED'
    verification_method = db.Column(db.String(50), default='MANUAL_REVIEW', nullable=False)
    provider_reference = db.Column(db.String(120), nullable=True)  # State registration code or anonymized doc token
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    review_reason = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('verification_applications', lazy='dynamic'))
    organization = db.relationship('Organization', foreign_keys=[organization_id], backref=db.backref('verification_applications', lazy='dynamic'))
    reviewer = db.relationship('User', foreign_keys=[reviewer_id])
    documents = db.relationship('VerificationDocument', backref='application', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def applicant_name(self):
        if self.organization:
            return self.organization.organization_name
        return self.user.name if self.user else "Unknown Applicant"

    @property
    def applicant_reference(self):
        if self.organization:
            return self.organization.registration_reference or f"ORG-APP-{self.organization.id:04d}"
        return f"DONOR-APP-{self.user_id:04d}"

    def __repr__(self):
        return f'<VerificationApplication #{self.id} Type={self.verification_type} Status={self.verification_status}>'


class VerificationDocument(db.Model):
    """Metadata for uploaded regulatory license or verification proof stored in isolated storage."""
    __tablename__ = 'verification_documents'

    id = db.Column(db.Integer, primary_key=True)
    verification_application_id = db.Column(
        db.Integer,
        db.ForeignKey('verification_applications.id', ondelete='CASCADE'),
        nullable=False
    )
    private_storage_reference = db.Column(db.String(255), nullable=False)
    document_type = db.Column(db.String(60), nullable=False)  # 'HOSPITAL_LICENSE', 'BLOOD_BANK_CERTIFICATE', 'IDENTITY_PROOF'
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    retention_deadline = db.Column(db.DateTime, nullable=True)
    deletion_status = db.Column(db.String(30), default='STORED', nullable=False)  # 'STORED', 'PURGED'

    def __repr__(self):
        return f'<VerificationDocument #{self.id} App={self.verification_application_id} Type={self.document_type}>'
