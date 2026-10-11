from datetime import datetime, timezone
from app.extensions import db


class Organization(db.Model):
    """Hospital or Blood Bank facility model."""
    __tablename__ = 'organizations'

    id = db.Column(db.Integer, primary_key=True)
    organization_name = db.Column(db.String(150), nullable=False)
    organization_type = db.Column(db.String(20), nullable=False)  # 'HOSPITAL', 'BLOOD_BANK'
    registration_reference = db.Column(db.String(100), nullable=True)  # State medical license / registration code
    address = db.Column(db.String(255), nullable=False)
    country = db.Column(db.String(64), default='India', nullable=True)
    state = db.Column(db.String(64), nullable=True)
    district = db.Column(db.String(64), nullable=True)
    city = db.Column(db.String(64), nullable=True)
    postal_code = db.Column(db.String(10), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    contact_phone = db.Column(db.String(20), nullable=False)
    contact_email = db.Column(db.String(120), nullable=True)
    verification_status = db.Column(db.String(20), default='PENDING', nullable=False)  # 'PENDING', 'VERIFIED', 'REJECTED'
    is_demo = db.Column(db.Boolean, default=False, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    memberships = db.relationship('OrganizationMembership', backref='organization', lazy='dynamic', cascade='all, delete-orphan')
    inventories = db.relationship('BloodInventory', backref='blood_bank', lazy='dynamic', cascade='all, delete-orphan')
    requests = db.relationship('BloodRequest', backref='requesting_organization', lazy='dynamic')
    donations = db.relationship('Donation', backref='blood_bank', lazy='dynamic')

    @property
    def is_verified(self):
        return self.verification_status in ('VERIFIED', 'APPROVED')

    @is_verified.setter
    def is_verified(self, val):
        if val:
            self.verification_status = 'VERIFIED'
        elif self.verification_status in ('VERIFIED', 'APPROVED'):
            self.verification_status = 'PENDING'

    @property
    def total_reported_units(self):
        from app.models.inventory import BloodInventory
        result = db.session.query(db.func.coalesce(db.func.sum(BloodInventory.available_units), 0))\
                           .filter(BloodInventory.blood_bank_id == self.id).scalar()
        return int(result or 0)

    def __repr__(self):
        return f'<Organization {self.organization_name} ({self.organization_type} - {self.verification_status})>'


class OrganizationMembership(db.Model):
    """Links user accounts with their affiliated organization and authorization level."""
    __tablename__ = 'organization_memberships'

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    membership_role = db.Column(db.String(20), default='STAFF', nullable=False)  # 'ADMIN', 'STAFF'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f'<Membership User={self.user_id} Org={self.organization_id} Role={self.membership_role}>'
