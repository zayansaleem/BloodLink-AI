from datetime import datetime, timezone, timedelta
from app.extensions import db


class BloodInventory(db.Model):
    """Reported blood unit inventory by blood group and component type."""
    __tablename__ = 'blood_inventories'

    id = db.Column(db.Integer, primary_key=True)
    blood_bank_id = db.Column(db.Integer, db.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)
    blood_group = db.Column(db.String(5), nullable=False)  # 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'
    component_type = db.Column(db.String(30), nullable=False, default='Whole Blood')  # 'Whole Blood', 'Red Blood Cells', 'Platelets', 'Plasma'
    available_units = db.Column(db.Integer, default=0, nullable=False)
    reserved_units = db.Column(db.Integer, default=0, nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=True)
    last_updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('blood_bank_id', 'blood_group', 'component_type', name='uq_bank_group_component'),
        db.CheckConstraint('available_units >= 0', name='check_positive_units'),
        db.CheckConstraint('reserved_units >= 0', name='check_positive_reserved_units'),
    )

    updater = db.relationship('User', foreign_keys=[updated_by])

    def reserve_units(self, units: int) -> bool:
        """Transaction-safe reservation of available inventory without negative stock."""
        if units <= 0 or self.available_units < units:
            return False
        self.available_units -= units
        self.reserved_units = (self.reserved_units or 0) + units
        self.last_updated_at = datetime.now(timezone.utc)
        return True

    def release_reserved_units(self, units: int) -> bool:
        """Safely restore previously reserved units back to available stock."""
        if units <= 0:
            return False
        current_res = self.reserved_units or 0
        actual_release = min(units, current_res)
        self.reserved_units = current_res - actual_release
        self.available_units += actual_release
        self.last_updated_at = datetime.now(timezone.utc)
        return True

    @property
    def is_outdated(self):
        """Flag inventory records not updated within 7 days."""
        if not self.last_updated_at:
            return True
        last_dt = self.last_updated_at
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last_dt) > timedelta(days=7)

    @property
    def stock_level_status(self):
        """Status badge for reported units."""
        if self.available_units <= 2:
            return 'CRITICAL', 'danger'
        elif self.available_units <= 5:
            return 'LOW', 'warning'
        return 'ADEQUATE', 'success'

    def __repr__(self):
        return f'<BloodInventory Org={self.blood_bank_id} {self.blood_group} ({self.component_type}): {self.available_units}>'
