import pytest
from datetime import datetime, timezone, timedelta
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.request import BloodRequest
from app.models.communication import DonorRequestResponse, DonorInvitation, Conversation, Message
from app.models.notification import Notification


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


class TestDonorEmergencyRequestsView:
    """Rigorous verification of the 10 donor request-response and emergency requests workflow criteria."""

    def _setup_hospital(self, name="Aster Medcity", state="Kerala", district="Ernakulam", city="Kochi"):
        coord = User(name=f"Coordinator {name}", email=f"coord_{name.lower().replace(' ', '_')}@hospital.org", role="HOSPITAL")
        coord.set_password("HospPass123!")
        db.session.add(coord)
        db.session.flush()

        org = Organization(
            organization_name=name,
            organization_type="HOSPITAL",
            registration_reference=f"REG-{name[:4].upper()}-01",
            address="National Highway 66, Cheranalloor",
            contact_phone="+91 484 669 9999",
            country="India",
            state=state,
            district=district,
            city=city,
            latitude=10.0450,
            longitude=76.2890,
            verification_status="VERIFIED"
        )
        db.session.add(org)
        db.session.flush()

        membership = OrganizationMembership(user_id=coord.id, organization_id=org.id, membership_role='ADMIN')
        db.session.add(membership)
        return {'user_id': coord.id, 'org_id': org.id, 'org': org, 'email': coord.email}

    def _setup_donor(self, name="Rahul Donor", email="rahul@donor.org", blood_group="A+", state="Kerala", district="Ernakulam", city="Kochi", available=True, cooldown_days_ago=70):
        user = User(name=name, email=email, role="DONOR")
        user.set_password("DonorPass123!")
        db.session.add(user)
        db.session.flush()

        last_donation = datetime.now(timezone.utc).date() - timedelta(days=cooldown_days_ago) if cooldown_days_ago else None

        profile = DonorProfile(
            user_id=user.id,
            declared_blood_group=blood_group,
            country="India",
            state=state,
            district=district,
            city=city,
            phone="+91 98470 12345",
            availability_status=available,
            verification_status="APPROVED",
            notification_consent=True,
            last_donation_date=last_donation
        )
        db.session.add(profile)
        return {'user_id': user.id, 'email': email, 'profile': profile, 'user': user}

    # -------------------------------------------------------------------------
    # TEST 1: Compatible, available donor sees the relevant invitation & Ready button
    # -------------------------------------------------------------------------
    def test_1_compatible_available_donor_sees_relevant_invitation(self, app, client):
        """A compatible, available donor viewing Emergency Blood Requests sees the request and 'I'm Ready to Donate' button."""
        with app.app_context():
            hosp = self._setup_hospital()
            donor = self._setup_donor(blood_group="A+")

            # Create verified emergency request in Kerala for A+
            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group="A+",
                component_type="Whole Blood",
                units_required=2,
                urgency_level="CRITICAL",
                location="Aster Medcity ICU",
                country="India",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 669 9999",
                verification_status="VERIFIED",
                request_status="ACTIVE_MATCHING"
            )
            db.session.add(req)
            db.session.flush()

            # Hospital creates invitation for this donor
            inv = DonorInvitation(
                hospital_id=hosp['org_id'],
                donor_id=donor['user_id'],
                blood_request_id=req.id,
                invitation_status="SENT"
            )
            db.session.add(inv)
            db.session.commit()
            req_id = req.id

        # Donor logs in
        client.post('/auth/login', data={'email': 'rahul@donor.org', 'password': 'DonorPass123!'}, follow_redirects=True)

        # 1. Check Emergency Requests page
        res = client.get('/emergency-requests?state=Kerala&blood_group=A+')
        assert res.status_code == 200
        assert b"Aster Medcity" in res.data
        assert b"I'm Ready to Donate" in res.data
        assert b"Direct Transfusion Invitation" in res.data
        assert b"Decline" in res.data

        # Also check /requests alias
        res_alias = client.get('/requests?state=Kerala&blood_group=A+')
        assert res_alias.status_code == 200
        assert b"I'm Ready to Donate" in res_alias.data

    # -------------------------------------------------------------------------
    # TEST 2: Incompatible donor does not see Ready button or accept an invitation
    # -------------------------------------------------------------------------
    def test_2_incompatible_donor_does_not_see_or_accept_invitation(self, app, client):
        """An incompatible donor (B+ viewing A+ request) does not see 'I'm Ready to Donate' and cannot respond."""
        with app.app_context():
            hosp = self._setup_hospital()
            incompat_donor = self._setup_donor(name="B Positive Donor", email="b_donor@donor.org", blood_group="B+")

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group="A+",
                component_type="Whole Blood",
                units_required=1,
                urgency_level="HIGH",
                location="Cardiology Bed 2",
                country="India",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 669 9999",
                verification_status="VERIFIED",
                request_status="ACTIVE_MATCHING"
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id

        client.post('/auth/login', data={'email': 'b_donor@donor.org', 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.get('/emergency-requests')
        assert res.status_code == 200
        assert b"Incompatible (B+)" in res.data
        # Ensure the active "I'm Ready to Donate" submit button is NOT shown for this incompatible card
        assert b'data-bs-target="#donateModal' + str(req_id).encode() not in res.data

        # Server-side enforcement: Direct POST attempt must be rejected
        res_post = client.post(f'/donor/request/{req_id}/respond', follow_redirects=True)
        assert res_post.status_code == 200
        assert b"not compatible" in res_post.data

        with app.app_context():
            resp_count = DonorRequestResponse.query.filter_by(blood_request_id=req_id, donor_id=incompat_donor['user_id']).count()
            assert resp_count == 0

    # -------------------------------------------------------------------------
    # TEST 3: Eligible donor can accept an invitation
    # -------------------------------------------------------------------------
    def test_3_eligible_donor_can_accept_invitation(self, app, client):
        """An eligible donor accepts a hospital invitation: records status, notifies hospital, updates request."""
        with app.app_context():
            hosp = self._setup_hospital()
            donor = self._setup_donor(blood_group="O-")

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group="AB+",
                component_type="Whole Blood",
                units_required=1,
                urgency_level="CRITICAL",
                location="Emergency Room",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 669 9999",
                verification_status="VERIFIED",
                request_status="ACTIVE_MATCHING"
            )
            db.session.add(req)
            db.session.flush()

            inv = DonorInvitation(
                hospital_id=hosp['org_id'],
                donor_id=donor['user_id'],
                blood_request_id=req.id,
                invitation_status="SENT"
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id
            req_id = req.id

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.post(f'/donor/invitation/{inv_id}/respond', data={'decision': 'ACCEPT'}, follow_redirects=True)
        assert res.status_code == 200
        assert b"accepted the donation invitation" in res.data
        # Verify clinical disclaimer regarding willingness only
        assert b"willingness to donate" in res.data

        with app.app_context():
            updated_inv = db.session.get(DonorInvitation, inv_id)
            assert updated_inv.invitation_status == "ACCEPTED"
            assert updated_inv.responded_at is not None

            resp = DonorRequestResponse.query.filter_by(blood_request_id=req_id, donor_id=donor['user_id']).first()
            assert resp is not None
            assert resp.response_status == "CONFIRMED"

            updated_req = db.session.get(BloodRequest, req_id)
            assert updated_req.request_status == "DONOR_RESPONDED"

            # Hospital coordinator received notification
            notifs = Notification.query.filter_by(recipient_id=hosp['user_id']).all()
            assert any("Invitation Accepted" in n.title for n in notifs)

    # -------------------------------------------------------------------------
    # TEST 4: Donor can decline an invitation
    # -------------------------------------------------------------------------
    def test_4_donor_can_decline_invitation(self, app, client):
        """A donor can decline an invitation cleanly."""
        with app.app_context():
            hosp = self._setup_hospital()
            donor = self._setup_donor(blood_group="A+")

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group="A+",
                component_type="Whole Blood",
                units_required=1,
                urgency_level="HIGH",
                location="OT 3",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 669 9999",
                verification_status="VERIFIED",
                request_status="ACTIVE_MATCHING"
            )
            db.session.add(req)
            db.session.flush()

            inv = DonorInvitation(
                hospital_id=hosp['org_id'],
                donor_id=donor['user_id'],
                blood_request_id=req.id,
                invitation_status="SENT"
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.post(f'/donor/invitation/{inv_id}/respond', data={'decision': 'DECLINE'}, follow_redirects=True)
        assert res.status_code == 200
        assert b"declined the donation invitation" in res.data

        with app.app_context():
            updated_inv = db.session.get(DonorInvitation, inv_id)
            assert updated_inv.invitation_status == "DECLINED"

            notifs = Notification.query.filter_by(recipient_id=hosp['user_id']).all()
            assert any("Invitation Declined" in n.title for n in notifs)

    # -------------------------------------------------------------------------
    # TEST 5: Duplicate responses are prevented
    # -------------------------------------------------------------------------
    def test_5_duplicate_responses_prevented(self, app, client):
        """Duplicate responses to the same request or invitation are strictly prevented."""
        with app.app_context():
            hosp = self._setup_hospital()
            donor = self._setup_donor(blood_group="A+")

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group="A+",
                component_type="Whole Blood",
                units_required=1,
                urgency_level="HIGH",
                location="Dialysis Ward",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 669 9999",
                verification_status="VERIFIED",
                request_status="ACTIVE_MATCHING"
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        # First response
        res1 = client.post(f'/donor/request/{req_id}/respond', data={'response_message': 'Ready to help'}, follow_redirects=True)
        assert res1.status_code == 200
        assert b"has been transmitted to" in res1.data

        # Second response attempt
        res2 = client.post(f'/donor/request/{req_id}/respond', data={'response_message': 'Another attempt'}, follow_redirects=True)
        assert res2.status_code == 200
        assert b"already responded" in res2.data

        with app.app_context():
            count = DonorRequestResponse.query.filter_by(blood_request_id=req_id, donor_id=donor['user_id']).count()
            assert count == 1, "There must be exactly one response record!"

    # -------------------------------------------------------------------------
    # TEST 6: Closed requests cannot be accepted
    # -------------------------------------------------------------------------
    def test_6_closed_requests_cannot_be_accepted(self, app, client):
        """Requests that are fulfilled or cancelled cannot be accepted."""
        with app.app_context():
            hosp = self._setup_hospital()
            donor = self._setup_donor(blood_group="O+")

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group="O+",
                component_type="Whole Blood",
                units_required=1,
                urgency_level="ROUTINE",
                location="Ward 1",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 669 9999",
                verification_status="VERIFIED",
                request_status="FULFILLED"  # Closed!
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.post(f'/donor/request/{req_id}/respond', follow_redirects=True)
        assert res.status_code == 200
        assert b"no longer active" in res.data

        with app.app_context():
            count = DonorRequestResponse.query.filter_by(blood_request_id=req_id, donor_id=donor['user_id']).count()
            assert count == 0

    # -------------------------------------------------------------------------
    # TEST 7: Unauthenticated users cannot respond
    # -------------------------------------------------------------------------
    def test_7_unauthenticated_users_cannot_respond(self, app, client):
        """Unauthenticated visitors see 'Sign in as Donor' and cannot POST state changes."""
        with app.app_context():
            hosp = self._setup_hospital()
            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group="B+",
                component_type="Whole Blood",
                units_required=1,
                urgency_level="CRITICAL",
                location="ICU",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 669 9999",
                verification_status="VERIFIED",
                request_status="ACTIVE_MATCHING"
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id

        # Anonymous view of emergency requests
        res = client.get('/emergency-requests')
        assert res.status_code == 200
        assert b"Sign in as Donor to Respond" in res.data

        # Anonymous attempt to POST respond
        res_post = client.post(f'/donor/request/{req_id}/respond')
        assert res_post.status_code == 302
        assert "/auth/login" in res_post.headers['Location']

    # -------------------------------------------------------------------------
    # TEST 8: Hospital requests are not incorrectly exposed to unrelated donors
    # -------------------------------------------------------------------------
    def test_8_hospital_requests_not_incorrectly_exposed_to_unrelated_donors(self, app, client):
        """Patient confidential names are hidden, and Donor B cannot view or act on Donor A's invitations."""
        with app.app_context():
            hosp = self._setup_hospital()
            donor_a = self._setup_donor(name="Donor Alice", email="alice@donor.org", blood_group="A+")
            donor_b = self._setup_donor(name="Donor Bob", email="bob@donor.org", blood_group="A+")

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group="A+",
                component_type="Whole Blood",
                units_required=1,
                urgency_level="HIGH",
                location="Private Room 101",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 669 9999",
                verification_status="VERIFIED",
                request_status="ACTIVE_MATCHING",
                patient_name="Confidential Alice Smith",
                patient_reference="MRN-CONF-999"
            )
            db.session.add(req)
            db.session.flush()

            # Invitation meant ONLY for Donor Alice
            inv_a = DonorInvitation(
                hospital_id=hosp['org_id'],
                donor_id=donor_a['user_id'],
                blood_request_id=req.id,
                invitation_status="SENT"
            )
            db.session.add(inv_a)
            db.session.commit()
            inv_a_id = inv_a.id
            req_id = req.id

        # 1. Donor Bob logs in
        client.post('/auth/login', data={'email': 'bob@donor.org', 'password': 'DonorPass123!'}, follow_redirects=True)

        # Bob views emergency requests: MUST NOT see patient private name
        res_reqs = client.get('/emergency-requests')
        assert b"Confidential Alice Smith" not in res_reqs.data
        assert b"MRN-CONF-999" not in res_reqs.data

        # Bob views dashboard: MUST NOT see Alice's invitation
        res_dash = client.get('/donor/dashboard')
        assert b"Confidential Alice Smith" not in res_dash.data
        assert b"No Pending Emergency Invitations" in res_dash.data

        # IDOR protection: Bob attempts to accept Alice's invitation -> 403 Forbidden
        res_tamper = client.post(f'/donor/invitation/{inv_a_id}/respond', data={'decision': 'ACCEPT'})
        assert res_tamper.status_code == 403

    # -------------------------------------------------------------------------
    # TEST 9: Blood compatibility rules work correctly
    # -------------------------------------------------------------------------
    def test_9_blood_compatibility_rules_work_correctly(self, app):
        """Standard RBC and plasma compatibility rules and clinical review components behave accurately."""
        from app.matching.compatibility import evaluate_component_compatibility

        # Standard Red Cells:
        # O- gives to all
        assert evaluate_component_compatibility('O-', 'AB+', 'Whole Blood')['is_compatible'] is True
        assert evaluate_component_compatibility('O-', 'O-', 'Whole Blood')['is_compatible'] is True

        # A+ gives only to A+ and AB+
        assert evaluate_component_compatibility('A+', 'A+', 'Whole Blood')['is_compatible'] is True
        assert evaluate_component_compatibility('A+', 'AB+', 'Packed Red Blood Cells')['is_compatible'] is True
        assert evaluate_component_compatibility('A+', 'B+', 'Whole Blood')['is_compatible'] is False
        assert evaluate_component_compatibility('A+', 'O+', 'Whole Blood')['is_compatible'] is False

        # AB+ gives only to AB+
        assert evaluate_component_compatibility('AB+', 'AB+', 'Whole Blood')['is_compatible'] is True
        assert evaluate_component_compatibility('AB+', 'A+', 'Whole Blood')['is_compatible'] is False

        # Plasma (Reversed polarity):
        # AB+ is universal plasma donor
        assert evaluate_component_compatibility('AB+', 'O+', 'Fresh Frozen Plasma')['is_compatible'] is True
        assert evaluate_component_compatibility('AB+', 'A+', 'Plasma')['is_compatible'] is True
        # O+ can only give plasma to O
        assert evaluate_component_compatibility('O+', 'A+', 'Fresh Frozen Plasma')['is_compatible'] is False

        # Specialized components require clinical review
        platelet_eval = evaluate_component_compatibility('O+', 'O+', 'Platelets')
        assert platelet_eval['status'] == 'REQUIRES_CLINICAL_REVIEW'
        assert platelet_eval['is_compatible'] is False

    # -------------------------------------------------------------------------
    # TEST 10: The donor dashboard updates after responding
    # -------------------------------------------------------------------------
    def test_10_donor_dashboard_updates_after_responding(self, app, client):
        """Donor dashboard displays updated responses and invitation statuses immediately."""
        with app.app_context():
            hosp = self._setup_hospital()
            donor = self._setup_donor(blood_group="A+")

            req = BloodRequest(
                request_reference=BloodRequest.generate_reference(),
                requesting_organization_id=hosp['org_id'],
                blood_group="A+",
                component_type="Whole Blood",
                units_required=2,
                urgency_level="HIGH",
                location="Pediatric Ward",
                state="Kerala",
                district="Ernakulam",
                city="Kochi",
                contact_phone="+91 484 669 9999",
                verification_status="VERIFIED",
                request_status="ACTIVE_MATCHING"
            )
            db.session.add(req)
            db.session.commit()
            req_id = req.id

        client.post('/auth/login', data={'email': donor['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        # Donor responds on the emergency requests board
        client.post(
            f'/donor/request/{req_id}/respond',
            data={'response_message': 'Can arrive in 30 minutes'},
            follow_redirects=True
        )

        # Donor visits dashboard
        res_dash = client.get('/donor/dashboard')
        assert res_dash.status_code == 200
        assert b"My Blood Request Responses" in res_dash.data
        assert b"INTERESTED" in res_dash.data
        assert b"Pediatric Ward" in res_dash.data or b"Aster Medcity" in res_dash.data
        assert b"Withdraw" in res_dash.data
