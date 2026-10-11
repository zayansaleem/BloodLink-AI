from datetime import datetime, timezone, timedelta
import hashlib
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app.extensions import db


class User(UserMixin, db.Model):
    """Core user account model supporting DONOR, HOSPITAL, BLOOD_BANK, and ADMIN roles."""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='DONOR')  # 'DONOR', 'HOSPITAL', 'BLOOD_BANK', 'ADMIN'
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    email_verified = db.Column(db.Boolean, default=True, nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=True)

    # Brute-force & Malicious Login Defense Fields
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    last_failed_login_at = db.Column(db.DateTime, nullable=True)
    locked_until = db.Column(db.DateTime, nullable=True)

    # Multi-Factor Authentication (TOTP)
    mfa_secret = db.Column(db.String(64), nullable=True)
    mfa_enabled = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    donor_profile = db.relationship('DonorProfile', backref='user', uselist=False, cascade='all, delete-orphan')
    memberships = db.relationship('OrganizationMembership', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    donations = db.relationship('Donation', foreign_keys='Donation.donor_id', backref='donor', lazy='dynamic')
    verified_donations = db.relationship('Donation', foreign_keys='Donation.verified_by', backref='verifier', lazy='dynamic')
    reward_transactions = db.relationship('RewardTransaction', backref='donor', lazy='dynamic', cascade='all, delete-orphan')
    redemptions = db.relationship('CouponRedemption', backref='donor', lazy='dynamic', cascade='all, delete-orphan')
    notifications = db.relationship('Notification', backref='recipient', lazy='dynamic', cascade='all, delete-orphan')
    audit_logs = db.relationship('AuditLog', backref='actor', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_temporarily_locked(self) -> bool:
        """Check if account is temporarily throttled/locked due to repeated failed logins."""
        if not self.locked_until:
            return False
        lu = self.locked_until
        if lu.tzinfo is None:
            lu = lu.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < lu

    def record_failed_login(self, max_attempts=5, lockout_minutes=15):
        """Increment failed attempts and apply progressive temporary lockout without permanent disablement."""
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        self.last_failed_login_at = datetime.now(timezone.utc)
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)
        db.session.commit()

    def record_successful_login(self):
        """Clear failed attempts and lockouts upon valid authentication."""
        self.failed_login_attempts = 0
        self.locked_until = None
        self.last_failed_login_at = None
        db.session.commit()

    def generate_mfa_secret(self) -> str:
        """Generate a cryptographically random RFC 6238 Base32 secret for TOTP MFA."""
        import pyotp
        self.mfa_secret = pyotp.random_base32()
        return self.mfa_secret

    def verify_totp(self, token: str) -> bool:
        """Verify an RFC 6238 6-digit TOTP code against the stored secret."""
        if not self.mfa_secret or not token:
            return False
        import pyotp
        totp = pyotp.TOTP(self.mfa_secret)
        return bool(totp.verify(str(token).strip(), valid_window=1))

    @property
    def organization(self):
        """Returns the organization the user belongs to, if any."""
        membership = self.memberships.first()
        return membership.organization if membership else None

    @property
    def reward_balance(self):
        """Calculate verified balance by summing all ledger transactions."""
        from app.models.rewards import RewardTransaction
        result = db.session.query(db.func.coalesce(db.func.sum(RewardTransaction.points), 0))\
                           .filter(RewardTransaction.donor_id == self.id).scalar()
        return int(result or 0)

    @property
    def unread_notification_count(self):
        return self.notifications.filter_by(read_at=None).count()

    @property
    def recent_notifications(self):
        from app.models.notification import Notification
        return self.notifications.order_by(Notification.created_at.desc()).limit(5).all()

    def __repr__(self):
        return f'<User {self.email} ({self.role})>'


class PasswordResetToken(db.Model):
    """Cryptographically secure, single-use token storage with SHA-256 token hashing."""
    __tablename__ = 'password_reset_tokens'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    token_hash = db.Column(db.String(128), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship('User', backref=db.backref('reset_tokens', cascade='all, delete-orphan', lazy='dynamic'))

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()

    @classmethod
    def create_token_for_user(cls, user_id: int, expires_minutes: int = 15) -> str:
        """Generate a random single-use token and store its SHA-256 hash."""
        # Invalidate any prior active tokens for this user
        cls.query.filter_by(user_id=user_id, used_at=None).update(
            {'used_at': datetime.now(timezone.utc)}
        )
        raw_token = secrets.token_urlsafe(32)
        hashed = cls.hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)

        token_record = cls(
            user_id=user_id,
            token_hash=hashed,
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(token_record)
        db.session.commit()
        return raw_token

    @classmethod
    def verify_raw_token(cls, raw_token: str):
        """Validate an unhashed reset token; returns token record or None."""
        if not raw_token:
            return None
        hashed = cls.hash_token(raw_token)
        token_record = cls.query.filter_by(token_hash=hashed).first()
        if not token_record or not token_record.is_valid:
            return None
        return token_record

    @property
    def is_valid(self) -> bool:
        if self.used_at is not None:
            return False
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) <= exp

    def mark_used(self):
        self.used_at = datetime.now(timezone.utc)
        db.session.commit()

