"""
BloodLink AI - Hospital Approval & Verification Status Test Suite

Verifies:
1. A pending hospital is approved by an authorized administrator.
2. The database verification status changes correctly (canonical VERIFIED).
3. The hospital portal displays the approved status (dashboard + verification-status).
4. The notification and database status agree.
5. Pending hospitals remain pending until approved (redirected to status page with PENDING badge).
6. Rejected hospitals remain rejected (status page displays REJECTED badge & reason).
7. Unauthorized users (unauthenticated, donors, hospitals) cannot approve hospitals.
8. Approval of one hospital does not accidentally update another hospital.
9. Repeated approval requests do not create duplicate/inconsistent records.
"""

import pytest
from datetime import datetime, timezone
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.organization import Organization, OrganizationMembership
from app.models.notification import Notification
from app.models.verification import VerificationApplication


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


class TestHospitalApprovalWorkflow:

    def _create_admin(self, email="admin@bloodlink.gov.in"):
        user = User(name="Super Admin", email=email, role="ADMIN")
        user.set_password("AdminPass123!")
        db.session.add(user)
        db.session.commit()
        return user

    def _create_hospital(self, name="City Care Hospital", email=None, status="PENDING"):
        uid = id(object())
        if not email:
            email = f"hosp_{uid}@citycare.org".lower()

        user = User(name=f"Dr. Coordinator {name}", email=email, role="HOSPITAL")
        user.set_password("HospitalPass123!")
        db.session.add(user)
        db.session.flush()

        org = Organization(
            organization_name=name,
            organization_type="HOSPITAL",
            registration_reference=f"REG-MED-{uid}",
            address="12 Healthcare Avenue",
            contact_phone="+91 80 4455 6677",
            contact_email=email,
            state="Karnataka",
            district="Bengaluru Urban",
            city="Bengaluru",
            latitude=12.9716,
            longitude=77.5946,
            verification_status=status
        )
        db.session.add(org)
        db.session.flush()

        membership = OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            membership_role="ADMIN"
        )
        db.session.add(membership)

        app_rec = VerificationApplication(
            user_id=user.id,
            organization_id=org.id,
            verification_type="HOSPITAL",
            verification_status="PENDING_VERIFICATION" if status == "PENDING" else "APPROVED",
            provider_reference=org.registration_reference
        )
        db.session.add(app_rec)
        db.session.commit()

        return {'user_id': user.id, 'email': email, 'org_id': org.id, 'name': name}

    def _create_donor(self, email="donor@volunteer.org"):
        user = User(name="Voluntary Donor", email=email, role="DONOR")
        user.set_password("DonorPass123!")
        db.session.add(user)
        db.session.commit()
        return user

    # =========================================================================
    # 1 & 2. PENDING HOSPITAL APPROVED BY ADMIN -> DB STATUS CHANGES TO VERIFIED
    # =========================================================================
    def test_pending_hospital_approved_by_admin(self, app, client):
        """Admin approves pending hospital: status becomes VERIFIED and app records are updated."""
        with app.app_context():
            admin = self._create_admin()
            hosp = self._create_hospital(name="Apollo Care", status="PENDING")
            admin_email = admin.email
            org_id = hosp['org_id']
            hosp_user_id = hosp['user_id']

        # Login as Admin
        client.post('/auth/login', data={'email': admin_email, 'password': 'AdminPass123!'}, follow_redirects=True)

        # Approve hospital
        res = client.post(f'/admin/verifications/organization/{org_id}/approve', data={
            'review_method': 'STATE_MEDICAL_REGISTRY_LOOKUP'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"has been successfully APPROVED" in res.data

        with app.app_context():
            org = db.session.get(Organization, org_id)
            assert org.verification_status == 'VERIFIED'
            assert org.is_verified is True

            # Verify associated VerificationApplication record updated with audit metadata
            app_rec = VerificationApplication.query.filter_by(organization_id=org_id).first()
            assert app_rec is not None
            assert app_rec.verification_status == 'APPROVED'
            assert app_rec.reviewer_id is not None
            assert app_rec.reviewed_at is not None

    # =========================================================================
    # 3. HOSPITAL PORTAL DISPLAYS APPROVED STATUS
    # =========================================================================
    def test_hospital_portal_reflects_approved_status(self, app, client):
        """Approved hospital logs in: enters dashboard directly and verification-status shows STATUS: VERIFIED."""
        with app.app_context():
            admin = self._create_admin()
            hosp = self._create_hospital(name="Fortis Care", status="PENDING")
            admin_email = admin.email
            org_id = hosp['org_id']
            hosp_email = hosp['email']

        # Admin approves
        client.post('/auth/login', data={'email': admin_email, 'password': 'AdminPass123!'}, follow_redirects=True)
        client.post(f'/admin/verifications/organization/{org_id}/approve', follow_redirects=True)
        client.get('/auth/logout')

        # Hospital logs in
        login_res = client.post('/auth/login', data={'email': hosp_email, 'password': 'HospitalPass123!'}, follow_redirects=True)
        assert login_res.status_code == 200

        # Hospital should NOT be redirected to /auth/verification-status on login; should enter /hospital/dashboard
        assert b"Clinical Requests Overview" in login_res.data or b"Verified Hospital" in login_res.data
        assert b"Accreditation Audit in Progress" not in login_res.data

        # If hospital explicitly visits /auth/verification-status
        status_res = client.get('/auth/verification-status')
        assert status_res.status_code == 200
        html = status_res.data.decode('utf-8')
        assert "STATUS: VERIFIED" in html
        assert "Facility Accreditation Verified &amp; Active" in html or "Facility Accreditation Verified & Active" in html
        assert "Operational Clinical Privileges Activated:" in html
        assert "Accreditation Audit in Progress" not in html
        assert "STATUS: PENDING VERIFICATION" not in html

    # =========================================================================
    # 4. NOTIFICATION AND DATABASE STATUS AGREE
    # =========================================================================
    def test_notification_and_database_status_agree(self, app, client):
        """Approval creates notification and database verification_status is synchronously VERIFIED."""
        with app.app_context():
            admin = self._create_admin()
            hosp = self._create_hospital(name="Manipal Care", status="PENDING")
            admin_email = admin.email
            org_id = hosp['org_id']
            hosp_user_id = hosp['user_id']

        client.post('/auth/login', data={'email': admin_email, 'password': 'AdminPass123!'}, follow_redirects=True)
        client.post(f'/admin/verifications/organization/{org_id}/approve', follow_redirects=True)

        with app.app_context():
            org = db.session.get(Organization, org_id)
            assert org.verification_status == 'VERIFIED'

            notifs = Notification.query.filter_by(recipient_id=hosp_user_id).all()
            assert len(notifs) >= 1
            appr_notif = next((n for n in notifs if "Registration Approved" in n.title), None)
            assert appr_notif is not None
            assert "verified and approved by platform administrators" in appr_notif.message

    # =========================================================================
    # 5. PENDING HOSPITALS REMAIN PENDING UNTIL APPROVED
    # =========================================================================
    def test_pending_hospitals_remain_pending_until_approved(self, app, client):
        """Pending hospital login is redirected to verification-status desk showing STATUS: PENDING VERIFICATION."""
        with app.app_context():
            hosp = self._create_hospital(name="Sunrise Hospital", status="PENDING")
            hosp_email = hosp['email']
            org_id = hosp['org_id']

        res = client.post('/auth/login', data={'email': hosp_email, 'password': 'HospitalPass123!'}, follow_redirects=True)
        assert res.status_code == 200

        html = res.data.decode('utf-8')
        assert "STATUS: PENDING VERIFICATION" in html
        assert "Accreditation Audit in Progress" in html
        assert "Protected Functions (Disabled Until Approval)" in html

        # Protected hospital action (e.g., create request) must be blocked
        req_res = client.get('/hospital/request/new', follow_redirects=True)
        assert req_res.status_code == 200
        assert b"Access restricted: Your organization account is pending administrator verification" in req_res.data

    # =========================================================================
    # 6. REJECTED HOSPITALS REMAIN REJECTED
    # =========================================================================
    def test_rejected_hospitals_remain_rejected(self, app, client):
        """Admin rejects hospital: status becomes REJECTED and portal displays STATUS: REJECTED with reason."""
        with app.app_context():
            admin = self._create_admin()
            hosp = self._create_hospital(name="Shady Clinic", status="PENDING")
            admin_email = admin.email
            org_id = hosp['org_id']
            hosp_email = hosp['email']

        client.post('/auth/login', data={'email': admin_email, 'password': 'AdminPass123!'}, follow_redirects=True)
        rej_res = client.post(f'/admin/verifications/organization/{org_id}/reject', data={
            'reason': 'Invalid and unverified state medical license registration certificate'
        }, follow_redirects=True)
        assert rej_res.status_code == 200
        assert b"marked as REJECTED" in rej_res.data

        client.get('/auth/logout')

        # Hospital logs in
        login_res = client.post('/auth/login', data={'email': hosp_email, 'password': 'HospitalPass123!'}, follow_redirects=True)
        assert login_res.status_code == 200

        html = login_res.data.decode('utf-8')
        assert "STATUS: REJECTED" in html
        assert "Accreditation Application Rejected" in html
        assert "Invalid and unverified state medical license" in html

        with app.app_context():
            org = db.session.get(Organization, org_id)
            assert org.verification_status == 'REJECTED'
            assert org.is_verified is False

    # =========================================================================
    # 7. UNAUTHORIZED USERS CANNOT APPROVE HOSPITALS
    # =========================================================================
    def test_unauthorized_users_cannot_approve_hospitals(self, app, client):
        """Unauthenticated users and non-admin users cannot trigger approval endpoint."""
        with app.app_context():
            hosp = self._create_hospital(name="Global Hospital", status="PENDING")
            donor = self._create_donor()
            org_id = hosp['org_id']
            donor_email = donor.email
            hosp_email = hosp['email']

        # 1. Anonymous user
        anon_res = client.post(f'/admin/verifications/organization/{org_id}/approve', follow_redirects=False)
        assert anon_res.status_code in [302, 401, 403]

        # 2. Voluntary donor
        client.post('/auth/login', data={'email': donor_email, 'password': 'DonorPass123!'}, follow_redirects=True)
        donor_res = client.post(f'/admin/verifications/organization/{org_id}/approve', follow_redirects=False)
        assert donor_res.status_code in [302, 403]
        client.get('/auth/logout')

        # 3. Hospital representative cannot approve themselves
        client.post('/auth/login', data={'email': hosp_email, 'password': 'HospitalPass123!'}, follow_redirects=True)
        self_res = client.post(f'/admin/verifications/organization/{org_id}/approve', follow_redirects=False)
        assert self_res.status_code in [302, 403]

        with app.app_context():
            org = db.session.get(Organization, org_id)
            assert org.verification_status == 'PENDING'
            assert org.is_verified is False

    # =========================================================================
    # 8. APPROVAL DOES NOT ACCIDENTALLY UPDATE ANOTHER HOSPITAL
    # =========================================================================
    def test_approval_does_not_accidentally_update_another_hospital(self, app, client):
        """Approving Hospital A leaves Hospital B in PENDING status."""
        with app.app_context():
            admin = self._create_admin()
            hosp_a = self._create_hospital(name="Hospital Alpha", status="PENDING")
            hosp_b = self._create_hospital(name="Hospital Beta", status="PENDING")
            admin_email = admin.email
            id_a = hosp_a['org_id']
            id_b = hosp_b['org_id']

        client.post('/auth/login', data={'email': admin_email, 'password': 'AdminPass123!'}, follow_redirects=True)
        client.post(f'/admin/verifications/organization/{id_a}/approve', follow_redirects=True)

        with app.app_context():
            org_a = db.session.get(Organization, id_a)
            org_b = db.session.get(Organization, id_b)
            assert org_a.verification_status == 'VERIFIED'
            assert org_a.is_verified is True

            # Hospital B must remain PENDING
            assert org_b.verification_status == 'PENDING'
            assert org_b.is_verified is False

    # =========================================================================
    # 9. REPEATED APPROVAL REQUESTS DO NOT CREATE INCONSISTENT RECORDS
    # =========================================================================
    def test_repeated_approval_does_not_create_inconsistent_records(self, app, client):
        """Repeated approval requests gracefully notify and do not duplicate notifications."""
        with app.app_context():
            admin = self._create_admin()
            hosp = self._create_hospital(name="Delta Multispecialty", status="PENDING")
            admin_email = admin.email
            org_id = hosp['org_id']
            hosp_user_id = hosp['user_id']

        client.post('/auth/login', data={'email': admin_email, 'password': 'AdminPass123!'}, follow_redirects=True)

        # First approval
        res1 = client.post(f'/admin/verifications/organization/{org_id}/approve', follow_redirects=True)
        assert res1.status_code == 200
        assert b"has been successfully APPROVED" in res1.data

        # Second repeated approval
        res2 = client.post(f'/admin/verifications/organization/{org_id}/approve', follow_redirects=True)
        assert res2.status_code == 200
        assert b"has already been verified and approved" in res2.data

        with app.app_context():
            org = db.session.get(Organization, org_id)
            assert org.verification_status == 'VERIFIED'

            # Notifications should not be spammed
            notifs = Notification.query.filter_by(recipient_id=hosp_user_id).all()
            assert len(notifs) == 1
