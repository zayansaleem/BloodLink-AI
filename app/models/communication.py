from datetime import datetime, timezone
from app.extensions import db


class DonorRequestResponse(db.Model):
    """Tracks voluntary donor willingness to respond to active hospital blood requests."""
    __tablename__ = 'donor_request_responses'

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    blood_request_id = db.Column(db.Integer, db.ForeignKey('blood_requests.id', ondelete='CASCADE'), nullable=False)
    response_status = db.Column(
        db.String(30),
        default='INTERESTED',
        nullable=False
    )  # 'INTERESTED', 'CONTACT_REQUESTED', 'CONTACTED', 'CONFIRMED', 'WITHDRAWN', 'COMPLETED', 'DECLINED'
    response_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    withdrawn_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    donor = db.relationship('User', foreign_keys=[donor_id], backref=db.backref('request_responses', lazy='dynamic'))
    blood_request = db.relationship('BloodRequest', foreign_keys=[blood_request_id], backref=db.backref('donor_responses', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('donor_id', 'blood_request_id', name='uq_donor_request_response'),
    )

    VALID_STATUSES = {
        'INTERESTED', 'CONTACT_REQUESTED', 'CONTACTED',
        'CONFIRMED', 'WITHDRAWN', 'COMPLETED', 'DECLINED'
    }

    def withdraw(self):
        """Safely transition response to WITHDRAWN status with timestamp."""
        if self.response_status in ('COMPLETED', 'DECLINED'):
            return False, "Cannot withdraw an already finalized response."
        self.response_status = 'WITHDRAWN'
        self.withdrawn_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        return True, "Response withdrawn successfully."

    def __repr__(self):
        return f'<DonorRequestResponse Donor={self.donor_id} Req={self.blood_request_id} Status={self.response_status}>'


class DonorInvitation(db.Model):
    """Invitations dispatched by verified hospitals to suitable voluntary donors."""
    __tablename__ = 'donor_invitations'

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    hospital_id = db.Column(db.Integer, db.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    blood_request_id = db.Column(db.Integer, db.ForeignKey('blood_requests.id', ondelete='CASCADE'), nullable=False)
    invitation_status = db.Column(
        db.String(30),
        default='SENT',
        nullable=False
    )  # 'SENT', 'DELIVERED', 'VIEWED', 'ACCEPTED', 'DECLINED', 'WITHDRAWN', 'EXPIRED'
    message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    responded_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    donor = db.relationship('User', foreign_keys=[donor_id], backref=db.backref('received_invitations', lazy='dynamic'))
    hospital = db.relationship('Organization', foreign_keys=[hospital_id], backref=db.backref('sent_invitations', lazy='dynamic'))
    blood_request = db.relationship('BloodRequest', foreign_keys=[blood_request_id], backref=db.backref('invitations', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('donor_id', 'blood_request_id', name='uq_donor_request_invitation'),
    )

    @property
    def status(self):
        return self.invitation_status

    @status.setter
    def status(self, val):
        self.invitation_status = val

    def __repr__(self):
        return f'<DonorInvitation Hospital={self.hospital_id} Donor={self.donor_id} Status={self.invitation_status}>'


class Conversation(db.Model):
    """In-app communication channel between verified hospital staff and voluntary donors."""
    __tablename__ = 'conversations'

    id = db.Column(db.Integer, primary_key=True)
    blood_request_id = db.Column(db.Integer, db.ForeignKey('blood_requests.id', ondelete='CASCADE'), nullable=False)
    donor_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    hospital_id = db.Column(db.Integer, db.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    blood_request = db.relationship('BloodRequest', backref=db.backref('conversations', lazy='dynamic'))
    donor = db.relationship('User', foreign_keys=[donor_id], backref=db.backref('donor_conversations', lazy='dynamic'))
    hospital = db.relationship('Organization', foreign_keys=[hospital_id], backref=db.backref('hospital_conversations', lazy='dynamic'))
    messages = db.relationship('Message', backref='conversation', lazy='dynamic', cascade='all, delete-orphan', order_by='Message.created_at.asc()')

    def is_participant(self, user):
        """Verify whether the specified user is an authorized participant."""
        if not user or not user.is_authenticated:
            return False
        if user.role == 'ADMIN':
            return True
        if user.id == self.donor_id:
            return True
        if user.role == 'HOSPITAL':
            org = user.organization
            if org and org.id == self.hospital_id:
                return True
        return False

    def __repr__(self):
        return f'<Conversation #{self.id} Req={self.blood_request_id} Donor={self.donor_id} Hosp={self.hospital_id}>'


class Message(db.Model):
    """Individual message exchange within an authorized clinical conversation."""
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    sender_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    message_body = db.Column(db.Text, nullable=False)
    is_reported = db.Column(db.Boolean, default=False, nullable=False)
    report_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    read_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    sender = db.relationship('User', foreign_keys=[sender_user_id])

    @property
    def is_read(self):
        return self.read_at is not None

    def mark_read(self):
        if not self.read_at:
            self.read_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f'<Message #{self.id} Conv={self.conversation_id} Sender={self.sender_user_id}>'


class BloodBankResponse(db.Model):
    """Tracks blood bank responses and stock reservations for active hospital blood requests."""
    __tablename__ = 'blood_bank_responses'

    id = db.Column(db.Integer, primary_key=True)
    blood_request_id = db.Column(db.Integer, db.ForeignKey('blood_requests.id', ondelete='CASCADE'), nullable=False)
    blood_bank_id = db.Column(db.Integer, db.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    responder_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    response_status = db.Column(
        db.String(40),
        default='ACCEPTED',
        nullable=False
    )  # 'ACCEPTED', 'DECLINED', 'INSUFFICIENT_INVENTORY', 'ADDITIONAL_VERIFICATION_REQUIRED'
    units_reserved = db.Column(db.Integer, default=0, nullable=False)
    response_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    blood_request = db.relationship('BloodRequest', foreign_keys=[blood_request_id], backref=db.backref('bank_responses', lazy='dynamic', cascade='all, delete-orphan'))
    blood_bank = db.relationship('Organization', foreign_keys=[blood_bank_id], backref=db.backref('hospital_request_responses', lazy='dynamic'))
    responder = db.relationship('User', foreign_keys=[responder_user_id])

    __table_args__ = (
        db.UniqueConstraint('blood_bank_id', 'blood_request_id', name='uq_bank_blood_request_response'),
    )

    VALID_STATUSES = {
        'ACCEPTED', 'REVIEWING', 'DECLINED', 'INSUFFICIENT_INVENTORY', 'ADDITIONAL_VERIFICATION_REQUIRED'
    }

    def __repr__(self):
        return f'<BloodBankResponse Bank={self.blood_bank_id} Req={self.blood_request_id} Status={self.response_status} Reserved={self.units_reserved}>'
