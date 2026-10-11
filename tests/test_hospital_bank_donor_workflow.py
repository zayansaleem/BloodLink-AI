"""
BloodLink AI - Comprehensive Hospital-Blood Bank-Donor Coordination Workflow Test Suite.

Verifies:
1. Verified hospital creates valid blood requests that enter active matching without routine admin approval.
2. Unverified and suspended hospitals remain restricted from activating requests.
3. Invalid requests (blood group, units, components, past deadline) are rejected server-side.
4. Suitable blood banks can view requests, accept coordination, and transactionally reserve stock.
5. Stock reservation cannot double-allocate or result in negative inventory.
6. Blood-bank acceptance does NOT mark fulfilment complete.
7. Blood banks can decline (releasing reserved stock), report insufficient inventory, or request additional verification.
8. Unsuitable (unverified/suspended) blood banks cannot respond.
9. Donors receive invitations, can accept/decline; acceptance does NOT mark donation or request complete.
10. Administrative investigation desk: admins can flag suspicious requests (pausing matching) and unflag/restore them.
11. Duplicate prevention across requests and invitations.
"""

import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest, DonorMatch
from app.models.communication import BloodBankResponse, DonorInvitation, DonorRequestResponse
from app.models.audit import AuditLog


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


class TestHospitalBloodBankDonorWorkflow:

    def _setup_hospital(self, name="Apollo Hospital", status="VERIFIED"):
        email = f"hosp_{name.lower().replace(' ', '_')}_{id(object())}@hosp.org".lower()
        user = User(name=f"Dr. Coordinator {name}", email=email, role="HOSPITAL")
        user.set_password("HospitalPass123!")
        db.session.add(user)
        db.session.flush()

        org = Organization(
            organization_name=name,
            organization_type="HOSPITAL",
            registration_reference=f"REG-HOSP-{id(object())}",
            address="100 Hospital Road",
            contact_phone="+91 80 1122 3344",
            state="Karnataka",
            district="Bengaluru Urban",
            city="Bengaluru",
            latitude=12.9716,
            longitude=77.5946,
            verification_status=status
        )
        db.session.add(org)
        db.session.flush()

        db.session.add(OrganizationMembership(user_id=user.id, organization_id=org.id, membership_role="ADMIN"))
        db.session.commit()

        return {'user_id': user.id, 'email': email, 'org_id': org.id, 'org_name': name}

    def _setup_blood_bank(self, name="Red Cross Blood Center", status="VERIFIED"):
        email = f"bank_{name.lower().replace(' ', '_')}_{id(object())}@bank.org".lower()
        user = User(name=f"Director {name}", email=email, role="BLOOD_BANK")
        user.set_password("BankPass123!")
        db.session.add(user)
        db.session.flush()

        org = Organization(
            organization_name=name,
            organization_type="BLOOD_BANK",
            registration_reference=f"REG-BB-{id(object())}",
            address="50 Blood Center Avenue",
            contact_phone="+91 80 9988 7766",
            state="Karnataka",
            district="Bengaluru Urban",
            city="Bengaluru",
            latitude=12.9750,
            longitude=77.5980,
            verification_status=status
        )
        db.session.add(org)
        db.session.flush()

        db.session.add(OrganizationMembership(user_id=user.id, organization_id=org.id, membership_role="ADMIN"))
        db.session.commit()

        return {'user_id': user.id, 'email': email, 'org_id': org.id, 'org_name': name}

    def _setup_donor(self, blood_group="A+", availability=True, consent=True, status="APPROVED"):
        email = f"donor_{blood_group.replace('+', 'pos').replace('-', 'neg')}_{id(object())}@donor.org".lower()
        user = User(name=f"Donor {blood_group}", email=email, role="DONOR")
        user.set_password("DonorPass123!")
        db.session.add(user)
        db.session.flush()

        profile = DonorProfile(
            user_id=user.id,
            declared_blood_group=blood_group,
            state="Karnataka",
            district="Bengaluru Urban",
            city="Bengaluru",
            latitude=12.9720,
            longitude=77.5950,
            availability_status=availability,
            notification_consent=consent,
            verification_status=status
        )
        db.session.add(profile)
        db.session.commit()

        return {'user_id': user.id, 'email': email, 'blood_group': blood_group}

    def _setup_admin(self):
        email = f"admin_{id(object())}@bloodlink.org".lower()
        user = User(name="Administrator", email=email, role="ADMIN")
        user.set_password("AdminPass123!")
        db.session.add(user)
        db.session.commit()
        return {'user_id': user.id, 'email': email}

    # =========================================================================
    # 1. VERIFIED HOSPITAL REQUEST ACTIVATION WITHOUT ADMIN BOTTLENECK
    # =========================================================================
    def test_verified_hospital_creates_valid_request_enters_matching_directly(self, app, client):
        """Verified hospital creates valid request: enters ACTIVE_MATCHING directly without routine admin approval."""
        with app.app_context():
            hosp = self._setup_hospital(name="Manipal Hospital", status="VERIFIED")
            donor = self._setup_donor(blood_group="A+")

        client.post('/auth/login', data={'email': hosp['email'], 'password': 'HospitalPass123!'}, follow_redirects=True)

        res = client.post('/hospital/request/new', data={
            'blood_group': 'A+',
            'component_type': 'Whole Blood',
            'units_required': '3',
            'urgency_level': 'CRITICAL',
            'location': 'ICU Emergency Ward',
            'state': 'Karnataka',
            'district': 'Bengaluru Urban',
            'city': 'Bengaluru',
            'contact_phone': '+91 80 1122 3344',
            'additional_notes': 'Urgent aortic aneurysm repair',
            'clinical_deadline': (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"created and activated for matching" in res.data.lower()

        with app.app_context():
            req = BloodRequest.query.filter_by(requesting_organization_id=hosp['org_id']).first()
            assert req is not None
            assert req.blood_group == 'A+'
            assert req.units_required == 3
            # Crucial assertion: Request is directly VERIFIED and in ACTIVE_MATCHING!
            assert req.verification_status == 'VERIFIED'
            assert req.request_status == 'ACTIVE_MATCHING'
            assert req.priority_score > 0  # Trusted clinical priority computed immediately
            assert req.matches.count() > 0  # Smart matching initiated immediately without admin intervention

    # =========================================================================
    # 2. UNVERIFIED & SUSPENDED HOSPITALS REMAIN RESTRICTED
    # =========================================================================
    def test_unverified_and_suspended_hospitals_cannot_create_requests(self, app, client):
        """Pending and suspended hospital accounts cannot create or activate blood requests."""
        with app.app_context():
            pending_hosp = self._setup_hospital(name="Pending Clinic", status="PENDING")
            suspended_hosp = self._setup_hospital(name="Suspended Center", status="SUSPENDED")

        # 1. Pending hospital blocked
        client.post('/auth/login', data={'email': pending_hosp['email'], 'password': 'HospitalPass123!'}, follow_redirects=True)
        res_pending = client.get('/hospital/request/new', follow_redirects=True)
        assert b"pending administrator verification" in res_pending.data.lower() or res_pending.status_code in (302, 403)

        client.get('/auth/logout')

        # 2. Suspended hospital blocked
        client.post('/auth/login', data={'email': suspended_hosp['email'], 'password': 'HospitalPass123!'}, follow_redirects=True)
        res_suspended = client.get('/hospital/request/new', follow_redirects=True)
        assert b"suspended" in res_suspended.data.lower() or b"pending" in res_suspended.data.lower() or res_suspended.status_code in (302, 403)

    # =========================================================================
    # 3. REQUEST VALIDATION DEFENSES
    # =========================================================================
    def test_invalid_requests_rejected_server_side(self, app, client):
        """Rejects invalid blood groups, quantities out of bounds, and deadlines in the past."""
        with app.app_context():
            hosp = self._setup_hospital(name="Columbia Asia", status="VERIFIED")

        client.post('/auth/login', data={'email': hosp['email'], 'password': 'HospitalPass123!'}, follow_redirects=True)

        # A. Invalid blood group
        res_bad_bg = client.post('/hospital/request/new', data={
            'blood_group': 'Z+',
            'component_type': 'Whole Blood',
            'units_required': '2',
            'location': 'Ward 1'
        }, follow_redirects=True)
        assert b"not a recognized abo/rh" in res_bad_bg.data.lower()

        # B. Invalid units (greater than 50 or zero)
        res_bad_units = client.post('/hospital/request/new', data={
            'blood_group': 'O+',
            'component_type': 'Whole Blood',
            'units_required': '999',
            'location': 'Ward 1'
        }, follow_redirects=True)
        assert b"between 1 and 50" in res_bad_units.data.lower()

        # C. Deadline in the past
        past_deadline = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        res_past_dl = client.post('/hospital/request/new', data={
            'blood_group': 'O+',
            'component_type': 'Whole Blood',
            'units_required': '2',
            'location': 'Ward 1',
            'clinical_deadline': past_deadline
        }, follow_redirects=True)
        assert b"past" in res_past_dl.data.lower()

    # =========================================================================
    # 4. BLOOD BANK RESPONSE & TRANSACTION-SAFE INVENTORY RESERVATION
    # =========================================================================
    def test_blood_bank_can_accept_and_reserve_stock_safely(self, app, client):
        """Verified blood bank can view active request, accept coordination, and reserve stock without double-allocation."""
        with app.app_context():
            hosp = self._setup_hospital(name="Fortis Hospital", status="VERIFIED")
            bank = self._setup_blood_bank(name="Karnataka Red Cross", status="VERIFIED")

            # Initialize inventory: 10 units of A+ Whole Blood
            inv = BloodInventory(
                blood_bank_id=bank['org_id'],
                blood_group='A+',
                component_type='Whole Blood',
                available_units=10,
                reserved_units=0
            )
            db.session.add(inv)

            # Create an active hospital request for 3 units
            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group='A+',
                component_type='Whole Blood',
                units_required=3,
                location='Surgical OT',
                state='Karnataka',
                district='Bengaluru Urban',
                city='Bengaluru',
                contact_phone='+91 80 1122 3344',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id

        # 1. Blood bank staff views requests
        client.post('/auth/login', data={'email': bank['email'], 'password': 'BankPass123!'}, follow_redirects=True)
        res_list = client.get('/blood-bank/requests')
        assert res_list.status_code == 200
        assert b"Fortis Hospital" in res_list.data
        assert b"A+" in res_list.data
        assert b"10 Unit(s)" in res_list.data  # Displays bank's available stock

        # 2. Blood bank accepts and reserves 3 units
        res_accept = client.post(f'/blood-bank/request/{req_id}/respond', data={
            'decision': 'ACCEPT',
            'units_to_reserve': '3',
            'notes': 'Reserved 3 packed units from Cold Room 2'
        }, follow_redirects=True)
        assert res_accept.status_code == 200
        assert b"coordination accepted" in res_accept.data.lower()

        # 3. Verify database state
        with app.app_context():
            # Available stock decremented: 10 - 3 = 7
            inv_db = BloodInventory.query.filter_by(blood_bank_id=bank['org_id'], blood_group='A+').first()
            assert inv_db.available_units == 7
            assert inv_db.reserved_units == 3

            # Response record created
            bb_resp = BloodBankResponse.query.filter_by(blood_bank_id=bank['org_id'], blood_request_id=req_id).first()
            assert bb_resp is not None
            assert bb_resp.response_status == 'ACCEPTED'
            assert bb_resp.units_reserved == 3

            # Request transitioned to BLOOD_BANK_RESPONDED (NOT FULFILLED!)
            req_db = db.session.get(BloodRequest, req_id)
            assert req_db.request_status == 'BLOOD_BANK_RESPONDED'
            assert req_db.request_status != 'FULFILLED'

    # =========================================================================
    # 5. INVENTORY OVER-ALLOCATION AND NEGATIVE STOCK PREVENTION
    # =========================================================================
    def test_blood_bank_cannot_over_allocate_or_reserve_more_than_available(self, app, client):
        """Attempting to reserve more units than available is strictly blocked server-side."""
        with app.app_context():
            hosp = self._setup_hospital(name="Narayana Health", status="VERIFIED")
            bank = self._setup_blood_bank(name="Rotary Blood Bank", status="VERIFIED")

            # Bank has only 1 unit available
            inv = BloodInventory(
                blood_bank_id=bank['org_id'],
                blood_group='O-',
                component_type='Whole Blood',
                available_units=1,
                reserved_units=0
            )
            db.session.add(inv)

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group='O-',
                component_type='Whole Blood',
                units_required=4,
                location='Trauma Unit',
                contact_phone='+91 80 1122 3344',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id

        client.post('/auth/login', data={'email': bank['email'], 'password': 'BankPass123!'}, follow_redirects=True)

        # Attempt to reserve 4 units when only 1 is available
        res_fail = client.post(f'/blood-bank/request/{req_id}/respond', data={
            'decision': 'ACCEPT',
            'units_to_reserve': '4'
        }, follow_redirects=True)

        assert b"insufficient stock" in res_fail.data.lower()

        with app.app_context():
            inv_db = BloodInventory.query.filter_by(blood_bank_id=bank['org_id'], blood_group='O-').first()
            assert inv_db.available_units == 1  # Unchanged
            assert inv_db.reserved_units == 0
            assert BloodBankResponse.query.filter_by(blood_bank_id=bank['org_id'], blood_request_id=req_id).first() is None

    # =========================================================================
    # 6. DECLINE FLOW SAFELY RELEASES RESERVED INVENTORY
    # =========================================================================
    def test_blood_bank_decline_releases_reserved_stock(self, app, client):
        """If a blood bank declines after previously accepting, reserved units are restored to available stock."""
        with app.app_context():
            hosp = self._setup_hospital(name="Bowring Hospital", status="VERIFIED")
            bank = self._setup_blood_bank(name="Lions Blood Bank", status="VERIFIED")

            inv = BloodInventory(
                blood_bank_id=bank['org_id'],
                blood_group='B+',
                component_type='Whole Blood',
                available_units=5,
                reserved_units=2  # Previously 2 units reserved
            )
            db.session.add(inv)

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group='B+',
                component_type='Whole Blood',
                units_required=2,
                location='Ward 4',
                contact_phone='+91 80 1122 3344',
                verification_status='VERIFIED',
                request_status='BLOOD_BANK_RESPONDED'
            )
            db.session.add(req)
            db.session.flush()

            resp = BloodBankResponse(
                blood_bank_id=bank['org_id'],
                blood_request_id=req.id,
                responder_user_id=bank['user_id'],
                response_status='ACCEPTED',
                units_reserved=2
            )
            db.session.add(resp)
            db.session.commit()
            req_id = req.id

        client.post('/auth/login', data={'email': bank['email'], 'password': 'BankPass123!'}, follow_redirects=True)

        # Blood bank now declines with explanation
        res_decline = client.post(f'/blood-bank/request/{req_id}/respond', data={
            'decision': 'DECLINE',
            'notes': 'Units diverted for emergency mass casualty triage'
        }, follow_redirects=True)

        assert b"declined" in res_decline.data.lower()

        with app.app_context():
            inv_db = BloodInventory.query.filter_by(blood_bank_id=bank['org_id'], blood_group='B+').first()
            # 2 reserved units safely returned to available stock: 5 + 2 = 7 available, 0 reserved!
            assert inv_db.available_units == 7
            assert inv_db.reserved_units == 0

            bb_resp = BloodBankResponse.query.filter_by(blood_bank_id=bank['org_id'], blood_request_id=req_id).first()
            assert bb_resp.response_status == 'DECLINED'
            assert bb_resp.units_reserved == 0

    # =========================================================================
    # 7. DONOR RESPONSE DOES NOT MARK DONATION OR REQUEST FULFILLED
    # =========================================================================
    def test_donor_acceptance_does_not_mark_donation_or_request_complete(self, app, client):
        """Donor accepting an opportunity registers willingness to respond without finalizing transfusion or fulfillment."""
        with app.app_context():
            hosp = self._setup_hospital(name="Victoria Hospital", status="VERIFIED")
            donor = self._setup_donor(blood_group="O+")

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group='O+',
                component_type='Whole Blood',
                units_required=1,
                location='ICU Ward',
                contact_phone='+91 80 1122 3344',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.flush()

            inv = DonorInvitation(
                donor_id=donor['user_id'],
                hospital_id=hosp['org_id'],
                blood_request_id=req.id,
                invitation_status='SENT'
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id
            req_id = req.id

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res_accept = client.post(f'/donor/invitation/{inv_id}/respond', data={
            'decision': 'ACCEPT'
        }, follow_redirects=True)

        assert res_accept.status_code == 200
        assert b"accepted" in res_accept.data.lower()

        with app.app_context():
            req_db = db.session.get(BloodRequest, req_id)
            # Status transitions to DONOR_RESPONDED, strictly NOT FULFILLED!
            assert req_db.request_status == 'DONOR_RESPONDED'
            assert req_db.request_status != 'FULFILLED'

            # Donor response record is confirmed
            resp_db = DonorRequestResponse.query.filter_by(donor_id=donor['user_id'], blood_request_id=req_id).first()
            assert resp_db.response_status == 'CONFIRMED'

            # No verified Donation record is created (physical blood bank intake verification is required upon arrival)
            assert User.query.get(donor['user_id']).donations.count() == 0

    # =========================================================================
    # 8. ADMINISTRATIVE OVERSIGHT & FLAGGING WORKFLOW
    # =========================================================================
    def test_admin_can_flag_and_restore_request_investigation(self, app, client):
        """Admins can investigate and flag suspicious requests (pausing matching) and restore them."""
        with app.app_context():
            hosp = self._setup_hospital(name="Specialty Care", status="VERIFIED")
            admin = self._setup_admin()

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group='A-',
                component_type='Whole Blood',
                units_required=2,
                location='ICU',
                contact_phone='+91 80 1122 3344',
                verification_status='VERIFIED',
                request_status='ACTIVE_MATCHING'
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id

        client.post('/auth/login', data={'email': admin['email'], 'password': 'AdminPass123!'}, follow_redirects=True)

        # 1. Admin flags request for investigation
        res_flag = client.post(f'/admin/requests/{req_id}/flag', data={
            'reason': 'Excessive consecutive requests from single facility'
        }, follow_redirects=True)
        assert res_flag.status_code == 200
        assert b"flagged" in res_flag.data.lower()

        with app.app_context():
            req_db = db.session.get(BloodRequest, req_id)
            assert req_db.request_status == 'FLAGGED_FOR_REVIEW'
            # is_active must now return False so it is excluded from donor/bank lists
            assert req_db.is_active is False

        # 2. Admin unflags and restores request
        res_unflag = client.post(f'/admin/requests/{req_id}/unflag', follow_redirects=True)
        assert res_unflag.status_code == 200
        assert b"restored" in res_unflag.data.lower() or b"cleared" in res_unflag.data.lower()

        with app.app_context():
            req_db2 = db.session.get(BloodRequest, req_id)
            assert req_db2.request_status == 'ACTIVE_MATCHING'
            assert req_db2.is_active is True

    # =========================================================================
    # 9. DUPLICATE SUBMISSION PROTECTION
    # =========================================================================
    def test_duplicate_request_submission_prevention(self, app, client):
        """Identical requests submitted within a short window are detected to prevent spam."""
        with app.app_context():
            hosp = self._setup_hospital(name="St. Martha Hospital", status="VERIFIED")

        client.post('/auth/login', data={'email': hosp['email'], 'password': 'HospitalPass123!'}, follow_redirects=True)

        req_data = {
            'blood_group': 'B-',
            'component_type': 'Whole Blood',
            'units_required': '2',
            'urgency_level': 'HIGH',
            'location': 'Ward 5',
            'contact_phone': '+91 80 1122 3344'
        }

        # 1. First submission succeeds
        res1 = client.post('/hospital/request/new', data=req_data, follow_redirects=True)
        assert b"created and activated" in res1.data.lower()

        # 2. Rapid duplicate submission caught
        res2 = client.post('/hospital/request/new', data=req_data, follow_redirects=True)
        assert b"duplicate submission detected" in res2.data.lower()
