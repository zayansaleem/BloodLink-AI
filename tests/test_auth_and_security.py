import pytest
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.organization import Organization, OrganizationMembership
from app.models.inventory import BloodInventory


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


class TestSecurityAndPermissions:
    """Tests for authentication security, RBAC authorization, and data integrity constraints."""

    def test_password_hashing(self, app):
        user = User(name="Test User", email="user@test.com", role="DONOR")
        user.set_password("SecurePassword123")
        assert user.password_hash != "SecurePassword123"
        assert user.check_password("SecurePassword123") is True
        assert user.check_password("WrongPassword") is False

    def test_unverified_organization_status_flag(self, app):
        org = Organization(
            organization_name="Pending Hospital", organization_type="HOSPITAL",
            address="Street 1", contact_phone="12345", verification_status="PENDING"
        )
        db.session.add(org)
        db.session.commit()

        assert org.is_verified is False
        org.verification_status = "VERIFIED"
        db.session.commit()
        assert org.is_verified is True

    def test_negative_inventory_rejected_by_validation(self, app):
        bank = Organization(
            organization_name="Test Bank", organization_type="BLOOD_BANK",
            address="Addr", contact_phone="123", verification_status="VERIFIED"
        )
        db.session.add(bank)
        db.session.commit()

        # Valid non-negative inventory
        inv = BloodInventory(
            blood_bank_id=bank.id, blood_group="A+", component_type="Whole Blood",
            available_units=10
        )
        db.session.add(inv)
        db.session.commit()
        assert inv.available_units == 10

        # Updating to negative should fail or violate constraint
        with pytest.raises(Exception):
            inv_bad = BloodInventory(
                blood_bank_id=bank.id, blood_group="B+", component_type="Whole Blood",
                available_units=-5
            )
            db.session.add(inv_bad)
            db.session.commit()
        db.session.rollback()
