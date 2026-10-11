import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest, DonorMatch
from app.models.donation import Donation
from app.models.rewards import Coupon, CouponRedemption, RewardTransaction
from app.rewards.services import award_donation_points, redeem_coupon


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


class TestEndToEndWorkflows:
    """Rigorous end-to-end integration test suite simulating all 5 hackathon roles and workflows."""

    # =========================================================================
    # WORKFLOW A: DONOR
    # =========================================================================
    def test_workflow_a_donor(self, app, client):
        # 1. Register donor
        res = client.post('/auth/register', data={
            'reg_type': 'donor',
            'name': 'Rohan Lifesaver',
            'email': 'rohan@example.com',
            'password': 'Password123!',
            'blood_group': 'O-',
            'state': 'Karnataka',
            'district': 'Bengaluru Urban',
            'city': 'Bengaluru',
            'phone': '+91 9876543210',
            'notification_consent': 'y',
            'latitude': '12.9716',
            'longitude': '77.5946'
        }, follow_redirects=True)
        assert res.status_code == 200
        assert b"Welcome to the BloodLink AI lifesaver network" in res.data

        # 2. View Donor Dashboard
        res_dash = client.get('/donor/dashboard')
        assert res_dash.status_code == 200
        assert b"Rohan Lifesaver" in res_dash.data
        assert b"O-" in res_dash.data

        # 3. Update profile and availability
        res_prof = client.post('/donor/profile', data={
            'state': 'Karnataka',
            'district': 'Bengaluru Urban',
            'city': 'Whitefield, Bengaluru',
            'phone': '+91 9999988888',
            'availability_status': 'y',
            'notification_consent': 'y',
            'latitude': '12.9698',
            'longitude': '77.7499'
        }, follow_redirects=True)
        assert res_prof.status_code == 200
        assert b"profile and privacy settings have been updated" in res_prof.data

        with app.app_context():
            donor_user = User.query.filter_by(email='rohan@example.com').first()
            assert donor_user.donor_profile.city == 'Whitefield, Bengaluru'
            assert donor_user.donor_profile.phone == '+91 9999988888'

        # 4. Toggle availability
        client.post('/donor/availability/toggle', follow_redirects=True)
        with app.app_context():
            donor_user = User.query.filter_by(email='rohan@example.com').first()
            assert donor_user.donor_profile.availability_status is False

        # 5. View rewards and redeem an eligible coupon
        with app.app_context():
            donor_user = User.query.filter_by(email='rohan@example.com').first()
            coupon = Coupon(
                partner_name="Metro Transit",
                title="Free Transit Pass",
                description="30-day city transit pass",
                category="Transit",
                points_required=50,
                coupon_status="ACTIVE"
            )
            db.session.add(coupon)
            # Credit 100 points to donor
            tx = RewardTransaction(
                donor_id=donor_user.id,
                points=100,
                transaction_type="CREDIT",
                description="Initial donation bonus"
            )
            db.session.add(tx)
            db.session.commit()
            coupon_id = coupon.id

        res_rewards = client.get('/donor/rewards')
        assert res_rewards.status_code == 200
        assert b"Free Transit Pass" in res_rewards.data

        # Redeem coupon
        res_redeem = client.post(f'/donor/redeem/{coupon_id}', follow_redirects=True)
        assert res_redeem.status_code == 200
        assert b"Your Voucher Code:" in res_redeem.data

        with app.app_context():
            donor_user = User.query.filter_by(email='rohan@example.com').first()
            assert donor_user.reward_balance == 50

        # 6. Log out
        res_logout = client.get('/auth/logout', follow_redirects=True)
        assert res_logout.status_code == 200
        assert b"signed out successfully" in res_logout.data

    # =========================================================================
    # WORKFLOW B: BLOOD BANK
    # =========================================================================
    def test_workflow_b_blood_bank(self, app, client):
        # 1. Register blood bank
        res = client.post('/auth/register', data={
            'reg_type': 'blood_bank',
            'org_name': 'Central City Blood Center',
            'registration_reference': 'BB-REG-2026-001',
            'contact_phone': '+91 80 1122 3344',
            'contact_email': 'info@centralblood.org',
            'address': '12 Hospital Road',
            'state': 'Karnataka',
            'district': 'Bengaluru Urban',
            'city': 'Bengaluru',
            'representative_name': 'Dr. Suresh Director',
            'representative_email': 'suresh@centralblood.org',
            'password': 'BankPassword123!',
            'latitude': '12.9716',
            'longitude': '77.5946'
        }, follow_redirects=True)
        assert res.status_code == 200
        assert b"Organization account registered" in res.data
        assert b"PENDING" in res.data

        with app.app_context():
            org = Organization.query.filter_by(organization_name='Central City Blood Center').first()
            assert org.verification_status == 'PENDING'
            assert org.is_verified is False
            org_id = org.id

        # 2. Block restricted operations before verification
        res_blocked = client.post('/blood-bank/inventory/update', data={
            'blood_group': 'B+',
            'component_type': 'Whole Blood',
            'available_units': '10'
        }, follow_redirects=True)
        assert b"pending administrator verification" in res_blocked.data

        # 3. Admin verifies blood bank
        with app.app_context():
            admin = User(name="Admin", email="admin@system.com", role="ADMIN")
            admin.set_password("AdminPass123!")
            db.session.add(admin)
            db.session.commit()

        # Admin logs in and approves organization
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'admin@system.com', 'password': 'AdminPass123!'}, follow_redirects=True)
        res_verify = client.post(f'/admin/organizations/{org_id}/verify', follow_redirects=True)
        assert b"has been verified successfully" in res_verify.data

        with app.app_context():
            org = db.session.get(Organization, org_id)
            assert org.verification_status == 'VERIFIED'
            assert org.is_verified is True

        # 4. Log in as verified blood bank representative
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'suresh@centralblood.org', 'password': 'BankPassword123!'}, follow_redirects=True)

        # 5. Add and Update inventory
        res_inv = client.post('/blood-bank/inventory/update', data={
            'blood_group': 'B+',
            'component_type': 'Whole Blood',
            'available_units': '15'
        }, follow_redirects=True)
        assert res_inv.status_code == 200
        assert b"Inventory saved: B+ Whole Blood set to 15 units" in res_inv.data

        # Verify DB persistence
        with app.app_context():
            inv = BloodInventory.query.filter_by(blood_bank_id=org_id, blood_group='B+').first()
            assert inv is not None
            assert inv.available_units == 15

        # Update inventory again to 20 units
        client.post('/blood-bank/inventory/update', data={
            'blood_group': 'B+',
            'component_type': 'Whole Blood',
            'available_units': '20'
        }, follow_redirects=True)

        with app.app_context():
            inv = BloodInventory.query.filter_by(blood_bank_id=org_id, blood_group='B+').first()
            assert inv.available_units == 20

        # View inventory and activity history
        res_view = client.get('/blood-bank/inventory')
        assert res_view.status_code == 200
        assert b"20 Units" in res_view.data
        assert b"Recent Inventory Activity Log" in res_view.data

        # 6. Record and verify donation
        with app.app_context():
            donor = User(name="Kavita Rao", email="kavita@donor.org", role="DONOR")
            donor.set_password("pass123")
            db.session.add(donor)
            db.session.flush()
            profile = DonorProfile(user_id=donor.id, declared_blood_group="B+", state="KA", district="BLR", city="Bengaluru")
            db.session.add(profile)
            db.session.commit()

        # Record donation intake
        res_rec = client.post('/blood-bank/donations/record-new', data={
            'donor_email': 'kavita@donor.org',
            'component_type': 'Whole Blood',
            'units': '1',
            'notes': 'Voluntary intake at blood bank'
        }, follow_redirects=True)
        assert b"Donation intake recorded" in res_rec.data

        with app.app_context():
            donation = Donation.query.filter_by(blood_bank_id=org_id).first()
            assert donation.verification_status == 'PENDING'
            donation_id = donation.id

        # Verify donation
        res_ver_don = client.post(f'/blood-bank/donations/{donation_id}/verify', follow_redirects=True)
        assert b"verified" in res_ver_don.data

        with app.app_context():
            donation = db.session.get(Donation, donation_id)
            assert donation.verification_status == 'VERIFIED'
            donor_check = User.query.filter_by(email="kavita@donor.org").first()
            assert donor_check.reward_balance == 100

    # =========================================================================
    # WORKFLOW C: HOSPITAL
    # =========================================================================
    def test_workflow_c_hospital(self, app, client):
        # 1. Register hospital
        client.post('/auth/register', data={
            'reg_type': 'hospital',
            'org_name': 'St. Jude Memorial Hospital',
            'registration_reference': 'HOSP-2026-999',
            'contact_phone': '+91 80 5566 7788',
            'contact_email': 'icu@stjude.org',
            'address': '45 Healthcare Ave',
            'state': 'Karnataka',
            'district': 'Bengaluru Urban',
            'city': 'Bengaluru',
            'representative_name': 'Dr. Meera Chief',
            'representative_email': 'meera@stjude.org',
            'password': 'HospitalPass123!',
            'latitude': '12.9716',
            'longitude': '77.5946'
        }, follow_redirects=True)

        with app.app_context():
            org = Organization.query.filter_by(organization_name='St. Jude Memorial Hospital').first()
            assert org.is_verified is False
            org_id = org.id

        # 2. Unverified hospital cannot access request creation
        res_blocked = client.get('/hospital/request/new', follow_redirects=True)
        assert b"pending administrator verification" in res_blocked.data

        # 3. Admin verifies hospital
        with app.app_context():
            admin = User(name="Admin2", email="admin2@system.com", role="ADMIN")
            admin.set_password("AdminPass123!")
            db.session.add(admin)
            db.session.commit()

        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'admin2@system.com', 'password': 'AdminPass123!'}, follow_redirects=True)
        client.post(f'/admin/organizations/{org_id}/verify', follow_redirects=True)

        # 4. Verified hospital creates blood request
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'meera@stjude.org', 'password': 'HospitalPass123!'}, follow_redirects=True)

        res_create = client.post('/hospital/request/new', data={
            'blood_group': 'AB-',
            'component_type': 'Whole Blood',
            'units_required': '2',
            'urgency_level': 'CRITICAL',
            'location': 'ICU Ward 3B',
            'contact_phone': '+91 80 5566 7788',
            'additional_notes': 'Emergency surgical bypass',
            'clinical_deadline': (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        }, follow_redirects=True)
        assert res_create.status_code == 200
        assert b"created and activated for matching" in res_create.data

        with app.app_context():
            req = BloodRequest.query.filter_by(requesting_organization_id=org_id).first()
            assert req is not None
            assert req.blood_group == 'AB-'
            assert req.units_required == 2
            assert req.verification_status == 'VERIFIED'
            assert req.request_status == 'ACTIVE_MATCHING'
            req_id = req.id

        # 5. Matching donor registration and match refresh
        with app.app_context():
            donor = User(name="Vikram AB-", email="vikram@donor.com", role="DONOR")
            donor.set_password("pass123")
            db.session.add(donor)
            db.session.flush()
            prof = DonorProfile(
                user_id=donor.id, declared_blood_group="AB-",
                latitude=12.9716, longitude=77.5946,
                state="KA", district="BLR", city="Bengaluru",
                availability_status=True, notification_consent=True,
                verification_status='APPROVED'
            )
            db.session.add(prof)
            db.session.commit()

        # Hospital refreshes donor matches directly without routine admin approval
        res_refresh = client.post(f'/hospital/request/{req_id}/match', follow_redirects=True)
        assert res_refresh.status_code == 200

        with app.app_context():
            req = db.session.get(BloodRequest, req_id)
            assert req.verification_status == 'VERIFIED'
            assert req.priority_score > 0
            assert req.matches.count() > 0

        # 6. Hospital views matches, triggers refresh, and updates status to FULFILLED
        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'meera@stjude.org', 'password': 'HospitalPass123!'}, follow_redirects=True)

        res_details = client.get(f'/hospital/request/{req_id}')
        assert res_details.status_code == 200
        assert b"Preliminary Smart Donor Matches" in res_details.data

        # Refresh matching
        res_rematch = client.post(f'/hospital/request/{req_id}/match', follow_redirects=True)
        assert b"Matching executed:" in res_rematch.data

        # Update status to FULFILLED
        res_fulfill = client.post(f'/hospital/request/{req_id}/update-status', data={
            'request_status': 'FULFILLED'
        }, follow_redirects=True)
        assert b"status has been updated to FULFILLED" in res_fulfill.data

        with app.app_context():
            req = db.session.get(BloodRequest, req_id)
            assert req.request_status == 'FULFILLED'

        # 7. Unauthorized modification attempt by another user is blocked (403)
        with app.app_context():
            other_user = User(name="Other Hospital", email="other@hospital.com", role="HOSPITAL")
            other_user.set_password("pass")
            other_org = Organization(
                organization_name="Other Org", organization_type="HOSPITAL",
                address="Addr", contact_phone="123", verification_status="VERIFIED"
            )
            db.session.add_all([other_user, other_org])
            db.session.flush()
            db.session.add(OrganizationMembership(organization_id=other_org.id, user_id=other_user.id))
            db.session.commit()

        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'other@hospital.com', 'password': 'pass'}, follow_redirects=True)

        res_unauth = client.post(f'/hospital/request/{req_id}/update-status', data={
            'request_status': 'CANCELLED'
        })
        assert res_unauth.status_code == 403

    # =========================================================================
    # WORKFLOW D: REWARD SYSTEM
    # =========================================================================
    def test_workflow_d_reward_system(self, app, client):
        with app.app_context():
            donor = User(name="Aarti Donor", email="aarti@donor.com", role="DONOR")
            donor.set_password("pass123")
            bank = Organization(
                organization_name="Rotary Bank", organization_type="BLOOD_BANK",
                address="Addr", contact_phone="123", verification_status="VERIFIED"
            )
            db.session.add_all([donor, bank])
            db.session.commit()

            # Record donation
            donation = Donation(
                donor_id=donor.id, blood_bank_id=bank.id, units=1,
                verification_status="VERIFIED"
            )
            db.session.add(donation)
            db.session.commit()

            # Award points
            assert award_donation_points(donation.id, points=100) is True
            assert donor.reward_balance == 100

            # Prevent duplicate points for same donation
            assert award_donation_points(donation.id, points=100) is False
            assert donor.reward_balance == 100

            # Create available and expired coupons
            active_coupon = Coupon(
                partner_name="Partner A", title="Perk 40",
                description="40 points discount perk",
                points_required=40, coupon_status="ACTIVE"
            )
            expensive_coupon = Coupon(
                partner_name="Partner B", title="Perk 500",
                description="500 points diagnostic check",
                points_required=500, coupon_status="ACTIVE"
            )
            expired_coupon = Coupon(
                partner_name="Partner C", title="Perk Expired",
                description="Expired test perk",
                points_required=20, coupon_status="EXPIRED",
                expiry_date=datetime.now(timezone.utc) - timedelta(days=1)
            )
            db.session.add_all([active_coupon, expensive_coupon, expired_coupon])
            db.session.commit()

            # Insufficient balance rejected
            success, msg, code = redeem_coupon(donor.id, expensive_coupon.id)
            assert success is False
            assert "Insufficient balance" in msg
            assert donor.reward_balance == 100

            # Expired coupon rejected
            success_exp, msg_exp, _ = redeem_coupon(donor.id, expired_coupon.id)
            assert success_exp is False
            assert "expired or inactive" in msg_exp
            assert donor.reward_balance == 100

            # Valid redemption succeeds
            success_valid, msg_valid, code_valid = redeem_coupon(donor.id, active_coupon.id)
            assert success_valid is True
            assert code_valid.startswith("BL-")
            assert donor.reward_balance == 60

    # =========================================================================
    # WORKFLOW E: ADMINISTRATOR
    # =========================================================================
    def test_workflow_e_administrator(self, app, client):
        # 1. Setup admin account
        with app.app_context():
            admin = User(name="Super Admin", email="superadmin@bloodlink.ai", role="ADMIN", is_active=True, email_verified=True)
            admin.set_password("AdminSecurePassword2026!")
            db.session.add(admin)
            db.session.commit()

        # Login as admin
        client.post('/auth/login', data={'email': 'superadmin@bloodlink.ai', 'password': 'AdminSecurePassword2026!'}, follow_redirects=True)

        # 2. Access admin views
        assert client.get('/admin/dashboard').status_code == 200
        assert client.get('/admin/organizations').status_code == 200
        assert client.get('/admin/requests').status_code == 200
        assert client.get('/admin/coupons').status_code == 200
        assert client.get('/admin/audit-logs').status_code == 200

        # 3. Create approved coupon
        res_coup = client.post('/admin/coupons', data={
            'partner_name': 'Apollo Diagnostics',
            'title': 'Free Lipid Profile Test',
            'description': 'Complete cholesterol & lipid screening',
            'category': 'Diagnostics',
            'points_required': '120',
            'icon': 'bi-heart-pulse'
        }, follow_redirects=True)
        assert res_coup.status_code == 200
        assert b"added to the marketplace" in res_coup.data

        with app.app_context():
            c = Coupon.query.filter_by(title='Free Lipid Profile Test').first()
            assert c is not None
            assert c.points_required == 120

        # 4. Ordinary user (donor) forbidden from admin actions
        with app.app_context():
            donor = User(name="Ordinary Donor", email="ordinary@donor.com", role="DONOR")
            donor.set_password("pass123")
            db.session.add(donor)
            db.session.commit()

        client.get('/auth/logout')
        client.post('/auth/login', data={'email': 'ordinary@donor.com', 'password': 'pass123'}, follow_redirects=True)

        assert client.get('/admin/dashboard').status_code == 403
        assert client.get('/admin/organizations').status_code == 403
        assert client.get('/admin/requests').status_code == 403
        assert client.get('/admin/coupons').status_code == 403
        assert client.get('/admin/audit-logs').status_code == 403
