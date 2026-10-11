"""
BloodLink AI - Comprehensive Database Persistence and Form Submission Tests.
Verifies registration, donor profile creation, login, updates, admin donor management,
session rollback, and cross-session persistence across application restarts.
"""

import os
import tempfile
import pytest
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest
from app.models.rewards import Coupon, RewardTransaction


@pytest.fixture
def temp_db_app():
    """Application fixture with a temporary isolated on-disk SQLite database."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'test_persistence.db').replace('\\', '/')
    db_uri = f"sqlite:///{db_path}"

    app = create_app('testing', config_overrides={
        'SQLALCHEMY_DATABASE_URI': db_uri,
        'WTF_CSRF_ENABLED': False
    })

    with app.app_context():
        db.create_all()
        yield app, db_path

        db.session.remove()
        db.drop_all()

    # Cleanup temp file
    try:
        if os.path.exists(db_path):
            os.remove(db_path)
        if os.path.exists(temp_dir):
            os.rmdir(temp_dir)
    except Exception:
        pass


@pytest.fixture
def client(temp_db_app):
    app, _ = temp_db_app
    return app.test_client()


class TestDatabasePersistence:
    """Verifies that user data, donor profiles, inventory, and requests persist across connections."""

    def test_01_donor_registration_creates_and_commits_user_and_profile(self, temp_db_app, client):
        app, _ = temp_db_app

        res = client.post('/auth/register', data={
            'reg_type': 'donor',
            'name': 'Pooja Nair',
            'email': 'pooja.nair@test.org',
            'password': 'SecurePassword123!',
            'confirm_password': 'SecurePassword123!',
            'blood_group': 'B+',
            'state': 'Kerala',
            'district': 'Ernakulam',
            'city': 'Kochi',
            'phone': '+91 9876543210',
            'notification_consent': 'y'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"Registration successful" in res.data or b"Welcome" in res.data

        with app.app_context():
            user = User.query.filter_by(email='pooja.nair@test.org').first()
            assert user is not None
            assert user.name == 'Pooja Nair'
            assert user.role == 'DONOR'
            assert user.is_active is True

            # Verify DonorProfile is created and linked
            assert user.donor_profile is not None
            assert user.donor_profile.user_id == user.id
            assert user.donor_profile.declared_blood_group == 'B+'
            assert user.donor_profile.state == 'Kerala'
            assert user.donor_profile.district == 'Ernakulam'
            assert user.donor_profile.city == 'Kochi'
            assert user.donor_profile.phone == '+91 9876543210'

    def test_02_user_can_login_after_registration(self, temp_db_app, client):
        app, _ = temp_db_app

        # 1. Register
        client.post('/auth/register', data={
            'reg_type': 'donor',
            'name': 'Rahul Verma',
            'email': 'rahul.verma@test.org',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'blood_group': 'O-',
            'state': 'Maharashtra',
            'district': 'Pune',
            'city': 'Pune',
            'phone': '+91 9123456780',
            'notification_consent': 'y'
        }, follow_redirects=True)

        # 2. Logout
        client.get('/auth/logout', follow_redirects=True)

        # 3. Login
        res_login = client.post('/auth/login', data={
            'email': 'rahul.verma@test.org',
            'password': 'Password123!'
        }, follow_redirects=True)

        assert res_login.status_code == 200
        assert b"Welcome back, Rahul Verma!" in res_login.data or b"Rahul Verma" in res_login.data

    def test_03_donor_dashboard_and_profile_update_without_duplicates(self, temp_db_app, client):
        app, _ = temp_db_app

        # Register donor
        client.post('/auth/register', data={
            'reg_type': 'donor',
            'name': 'Ananya Sen',
            'email': 'ananya.sen@test.org',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'blood_group': 'AB+',
            'state': 'West Bengal',
            'district': 'Kolkata',
            'city': 'Kolkata',
            'phone': '+91 9333344444',
            'notification_consent': 'y'
        }, follow_redirects=True)

        # Access dashboard
        res_dash = client.get('/donor/dashboard')
        assert res_dash.status_code == 200
        assert b"Ananya Sen" in res_dash.data
        assert b"AB+" in res_dash.data

        # Update profile
        res_update = client.post('/donor/profile', data={
            'state': 'West Bengal',
            'district': 'Kolkata',
            'city': 'Salt Lake, Kolkata',
            'phone': '+91 9444455555',
            'availability_status': 'y',
            'notification_consent': 'y'
        }, follow_redirects=True)

        assert res_update.status_code == 200
        assert b"profile and privacy settings have been updated" in res_update.data

        with app.app_context():
            user = User.query.filter_by(email='ananya.sen@test.org').first()
            assert user.donor_profile.city == 'Salt Lake, Kolkata'
            assert user.donor_profile.phone == '+91 9444455555'

            # Ensure NO duplicate profile records were created
            profiles_count = DonorProfile.query.filter_by(user_id=user.id).count()
            assert profiles_count == 1

    def test_04_admin_donor_management_view_and_permissions(self, temp_db_app, client):
        app, _ = temp_db_app

        with app.app_context():
            # Create admin
            admin = User(name="Test Admin", email="admin.test@bloodlink.ai", role="ADMIN", is_active=True, email_verified=True)
            admin.set_password("AdminPass123!")
            db.session.add(admin)

            # Create donor
            donor = User(name="Kiran Kumar", email="kiran@test.org", role="DONOR", is_active=True, email_verified=True)
            donor.set_password("DonorPass123!")
            db.session.add(donor)
            db.session.flush()

            profile = DonorProfile(
                user_id=donor.id,
                declared_blood_group="A-",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                phone="+91 9888877777",
                availability_status=True
            )
            db.session.add(profile)
            db.session.commit()

        # Anonymous cannot access admin donors
        client.get('/auth/logout')
        res_anon = client.get('/admin/donors')
        assert res_anon.status_code in [302, 401]

        # Donor cannot access admin donors
        client.post('/auth/login', data={'email': 'kiran@test.org', 'password': 'DonorPass123!'}, follow_redirects=True)
        res_donor_unauth = client.get('/admin/donors')
        assert res_donor_unauth.status_code == 403

        # Admin CAN access admin donors
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'admin.test@bloodlink.ai', 'password': 'AdminPass123!'}, follow_redirects=True)
        res_admin = client.get('/admin/donors')
        assert res_admin.status_code == 200
        assert b"Kiran Kumar" in res_admin.data
        assert b"kiran@test.org" in res_admin.data
        assert b"A-" in res_admin.data
        assert b"Bengaluru Urban" in res_admin.data

    def test_05_invalid_submission_does_not_create_orphans_and_rolls_back(self, temp_db_app, client):
        app, _ = temp_db_app

        initial_user_count = 0
        initial_profile_count = 0
        with app.app_context():
            initial_user_count = User.query.count()
            initial_profile_count = DonorProfile.query.count()

        # Submit with invalid state
        res_invalid = client.post('/auth/register', data={
            'reg_type': 'donor',
            'name': 'Invalid User',
            'email': 'invalid@test.org',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'blood_group': 'O+',
            'state': 'NonExistentState',
            'district': 'NonExistentDistrict',
            'city': 'FakeCity'
        }, follow_redirects=True)

        assert b"Invalid State" in res_invalid.data

        with app.app_context():
            # Counts must be completely unchanged
            assert User.query.count() == initial_user_count
            assert DonorProfile.query.count() == initial_profile_count
            assert User.query.filter_by(email='invalid@test.org').first() is None

    def test_06_records_persist_across_database_reconnection(self, temp_db_app):
        """Confirm that after committing, closing, and reopening connections, records remain intact."""
        app, db_path = temp_db_app

        with app.app_context():
            user = User(name="Persistent Donor", email="persist@donor.org", role="DONOR")
            user.set_password("Pass12345!")
            db.session.add(user)
            db.session.flush()

            profile = DonorProfile(
                user_id=user.id,
                declared_blood_group="O+",
                state="Tamil Nadu",
                district="Chennai",
                city="Chennai"
            )
            db.session.add(profile)
            db.session.commit()
            saved_user_id = user.id

        # Close connection and open on-disk SQLite file using a completely fresh engine & session
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        fresh_engine = create_engine(f"sqlite:///{db_path}")
        FreshSession = sessionmaker(bind=fresh_engine)
        fresh_session = FreshSession()

        reloaded_user = fresh_session.get(User, saved_user_id)
        assert reloaded_user is not None
        assert reloaded_user.name == "Persistent Donor"
        assert reloaded_user.email == "persist@donor.org"
        assert reloaded_user.donor_profile.declared_blood_group == "O+"
        assert reloaded_user.donor_profile.state == "Tamil Nadu"
        fresh_session.close()

    def test_07_inventory_and_blood_requests_persist(self, temp_db_app):
        app, _ = temp_db_app

        with app.app_context():
            bank = Organization(
                organization_name="Apollo Blood Center",
                organization_type="BLOOD_BANK",
                address="Apollo Road",
                contact_phone="+91 80 1234 5678",
                state="Karnataka",
                district="Bengaluru Urban",
                city="Bengaluru",
                verification_status="VERIFIED"
            )
            db.session.add(bank)
            db.session.flush()

            inv = BloodInventory(
                blood_bank_id=bank.id,
                blood_group="A+",
                component_type="Whole Blood",
                available_units=25
            )
            db.session.add(inv)

            req = BloodRequest(
                request_reference="REQ-TEST-PERSIST-01",
                requesting_organization_id=bank.id,
                blood_group="A+",
                component_type="Whole Blood",
                units_required=3,
                location="ICU Ward",
                contact_phone="+91 80 1234 5678",
                verification_status="VERIFIED",
                request_status="MATCHING"
            )
            db.session.add(req)
            db.session.commit()

            # Query back
            inv_check = BloodInventory.query.filter_by(blood_bank_id=bank.id, blood_group="A+").first()
            assert inv_check is not None
            assert inv_check.available_units == 25

            req_check = BloodRequest.query.filter_by(request_reference="REQ-TEST-PERSIST-01").first()
            assert req_check is not None
            assert req_check.units_required == 3
