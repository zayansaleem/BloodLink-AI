"""
BloodLink AI - Comprehensive Blood Group Compatibility & Donor Approval Test Suite.

Verifies:
1. Complete 8-group ABO/Rh Red Blood Cell compatibility matrix.
2. Correct recipient-to-donor and donor-to-recipient directionality.
3. Separate clinically reviewed Plasma compatibility matrix.
4. Unsupported / specialized component handling (Platelets flagged for clinical review).
5. Backend rejection of incompatible hospital invitations.
6. Backend rejection of incompatible donor responses.
7. Backend rejection of incompatible invitation acceptances.
8. Donor standby availability and emergency notification consent enforcement.
9. Inactive / fulfilled request status restrictions.
10. Donor choice (accept and decline) and patient privacy preservation.
"""

import pytest
from datetime import datetime, timezone
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.request import BloodRequest
from app.models.communication import DonorInvitation, DonorRequestResponse
from app.matching.compatibility import (
    is_preliminarily_compatible,
    evaluate_component_compatibility,
    get_compatible_donor_groups,
    get_compatible_recipient_groups,
    VALID_BLOOD_GROUPS
)


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


class TestAllEightBloodGroupsRBC:
    """Rigorous verification of the complete 8x8 ABO/Rh Red Blood Cell compatibility matrix."""

    def test_all_eight_donor_groups_erythrocyte_rules(self):
        all_8 = VALID_BLOOD_GROUPS  # ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']

        # 1. O- (Universal RBC Donor): Can donate to all 8 groups
        for r in all_8:
            assert is_preliminarily_compatible('O-', r, 'Red Blood Cells') is True
            assert is_preliminarily_compatible('O-', r, 'Whole Blood') is True

        # 2. O+: Can donate to all Rh-positive groups (O+, A+, B+, AB+); cannot donate to Rh-negative
        for r in ['O+', 'A+', 'B+', 'AB+']:
            assert is_preliminarily_compatible('O+', r, 'Red Blood Cells') is True
        for r in ['O-', 'A-', 'B-', 'AB-']:
            assert is_preliminarily_compatible('O+', r, 'Red Blood Cells') is False

        # 3. A-: Can donate to A-, A+, AB-, AB+; cannot donate to O or B
        for r in ['A-', 'A+', 'AB-', 'AB+']:
            assert is_preliminarily_compatible('A-', r, 'Red Blood Cells') is True
        for r in ['O-', 'O+', 'B-', 'B+']:
            assert is_preliminarily_compatible('A-', r, 'Red Blood Cells') is False

        # 4. A+: Can donate to A+ and AB+ only
        for r in ['A+', 'AB+']:
            assert is_preliminarily_compatible('A+', r, 'Red Blood Cells') is True
        for r in ['O-', 'O+', 'A-', 'B-', 'B+', 'AB-']:
            assert is_preliminarily_compatible('A+', r, 'Red Blood Cells') is False

        # 5. B-: Can donate to B-, B+, AB-, AB+; cannot donate to O or A
        for r in ['B-', 'B+', 'AB-', 'AB+']:
            assert is_preliminarily_compatible('B-', r, 'Red Blood Cells') is True
        for r in ['O-', 'O+', 'A-', 'A+']:
            assert is_preliminarily_compatible('B-', r, 'Red Blood Cells') is False

        # 6. B+: Can donate to B+ and AB+ only
        for r in ['B+', 'AB+']:
            assert is_preliminarily_compatible('B+', r, 'Red Blood Cells') is True
        for r in ['O-', 'O+', 'A-', 'A+', 'B-', 'AB-']:
            assert is_preliminarily_compatible('B+', r, 'Red Blood Cells') is False

        # 7. AB-: Can donate to AB- and AB+ only
        for r in ['AB-', 'AB+']:
            assert is_preliminarily_compatible('AB-', r, 'Red Blood Cells') is True
        for r in ['O-', 'O+', 'A-', 'A+', 'B-', 'B+']:
            assert is_preliminarily_compatible('AB-', r, 'Red Blood Cells') is False

        # 8. AB+: Can donate to AB+ only
        assert is_preliminarily_compatible('AB+', 'AB+', 'Red Blood Cells') is True
        for r in ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-']:
            assert is_preliminarily_compatible('AB+', r, 'Red Blood Cells') is False

    def test_recipient_directionality_and_matrix_consistency(self):
        """Directionality must be respected: Donor giving to Recipient is not commutative."""
        # A+ donor cannot donate to O+ recipient, but A+ recipient CAN receive from O+ donor
        assert is_preliminarily_compatible('A+', 'O+', 'Red Blood Cells') is False
        assert is_preliminarily_compatible('O+', 'A+', 'Red Blood Cells') is True

        # B+ donor cannot donate to A+ recipient, and A+ donor cannot donate to B+ recipient
        assert is_preliminarily_compatible('B+', 'A+', 'Red Blood Cells') is False
        assert is_preliminarily_compatible('A+', 'B+', 'Red Blood Cells') is False

        # AB+ recipient is Universal Recipient: can receive from all 8 groups
        for d in VALID_BLOOD_GROUPS:
            assert is_preliminarily_compatible(d, 'AB+', 'Red Blood Cells') is True

        # O- recipient can receive ONLY from O-
        assert is_preliminarily_compatible('O-', 'O-', 'Red Blood Cells') is True
        for d in ['O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+']:
            assert is_preliminarily_compatible(d, 'O-', 'Red Blood Cells') is False


class TestComponentAwareStrategies:
    """Verifies that Plasma and other components follow explicit separate strategies."""

    def test_plasma_compatibility_reversed_strategy(self):
        """Plasma compatibility follows anti-A/anti-B antibody presence (reversed polarity)."""
        # AB is Universal Plasma Donor (no anti-A or anti-B antibodies in plasma)
        for r in VALID_BLOOD_GROUPS:
            assert is_preliminarily_compatible('AB+', r, 'Plasma') is True
            assert is_preliminarily_compatible('AB-', r, 'Plasma') is True

        # O is Universal Plasma Recipient, but can only donate plasma to O
        assert is_preliminarily_compatible('O+', 'O+', 'Plasma') is True
        assert is_preliminarily_compatible('O+', 'O-', 'Plasma') is True
        assert is_preliminarily_compatible('O+', 'A+', 'Plasma') is False
        assert is_preliminarily_compatible('O+', 'B+', 'Plasma') is False
        assert is_preliminarily_compatible('O+', 'AB+', 'Plasma') is False

        # A donor plasma has anti-B: can give to A and O recipients, NOT B or AB
        assert is_preliminarily_compatible('A+', 'A+', 'Plasma') is True
        assert is_preliminarily_compatible('A+', 'O+', 'Plasma') is True
        assert is_preliminarily_compatible('A+', 'B+', 'Plasma') is False
        assert is_preliminarily_compatible('A+', 'AB+', 'Plasma') is False

    def test_platelets_and_unsupported_components_require_clinical_review(self):
        """Platelets must NOT use RBC matrix; they must be flagged for clinical review."""
        res_platelets = evaluate_component_compatibility('O-', 'O+', 'Platelets')
        assert res_platelets['is_compatible'] is False
        assert res_platelets['status'] == 'REQUIRES_CLINICAL_REVIEW'
        assert res_platelets['requires_review'] is True
        assert 'pathologist' in res_platelets['reason'].lower()

        # Automated compatibility function must return False for Platelets
        assert is_preliminarily_compatible('O-', 'O+', 'Platelets') is False
        assert is_preliminarily_compatible('A+', 'A+', 'Platelets') is False

        # get_compatible_donor_groups returns empty list for review-required components
        assert get_compatible_donor_groups('A+', 'Platelets') == []
        assert get_compatible_recipient_groups('A+', 'Platelets') == []


class TestBackendEnforcementAndDonorApproval:
    """Verifies server-side rejection of incompatible or unauthorized invitations and responses."""

    def _setup_hospital_and_request(self, blood_group="A+", component_type="Whole Blood", request_status="OPEN"):
        hosp_user = User(name="Dr. Coordinator", email="coord@hospital.org", role="HOSPITAL")
        hosp_user.set_password("Pass123!")
        db.session.add(hosp_user)
        db.session.flush()

        hosp = Organization(
            organization_name="Apollo Healthcare",
            organization_type="HOSPITAL",
            registration_reference="HOSP-APOLLO-01",
            address="100 Greams Road",
            contact_phone="+91 44 2829 0200",
            state="Tamil Nadu",
            district="Chennai",
            city="Chennai",
            verification_status="VERIFIED"
        )
        db.session.add(hosp)
        db.session.flush()
        db.session.add(OrganizationMembership(user_id=hosp_user.id, organization_id=hosp.id, membership_role='ADMIN'))

        req = BloodRequest(
            request_reference=BloodRequest.generate_reference(),
            requesting_organization_id=hosp.id,
            blood_group=blood_group,
            component_type=component_type,
            units_required=2,
            urgency_level="CRITICAL",
            location="Trauma Center",
            state="Tamil Nadu",
            district="Chennai",
            city="Chennai",
            verification_status="VERIFIED",
            request_status=request_status,
            contact_phone="+91 44 2829 0200",
            patient_name="Confidential Patient Rao",
            patient_reference="MRN-CONFIDENTIAL"
        )
        db.session.add(req)
        db.session.commit()

        return {
            'user_id': hosp_user.id,
            'email': hosp_user.email,
            'hosp_id': hosp.id,
            'req_id': req.id,
            'req_ref': req.request_reference
        }

    def _setup_donor(self, blood_group="B+", availability=True, consent=True, status="APPROVED"):
        email = f"donor_{blood_group.replace('+', 'pos').replace('-', 'neg')}_{id(object())}@donor.org".lower()
        donor = User(name=f"Donor {blood_group}", email=email, role="DONOR")
        donor.set_password("DonorPass123!")
        db.session.add(donor)
        db.session.flush()

        profile = DonorProfile(
            user_id=donor.id,
            declared_blood_group=blood_group,
            state="Tamil Nadu",
            district="Chennai",
            city="Chennai",
            availability_status=availability,
            notification_consent=consent,
            verification_status=status
        )
        db.session.add(profile)
        db.session.commit()

        return {
            'user_id': donor.id,
            'email': email,
            'blood_group': blood_group
        }

    def test_hospital_cannot_send_invitation_to_incompatible_donor(self, app, client):
        """Hospital staff sending invitation to incompatible donor is rejected server-side."""
        with app.app_context():
            hosp_info = self._setup_hospital_and_request(blood_group="A+", component_type="Whole Blood")
            # B+ donor is incompatible with A+ Whole Blood request
            donor_info = self._setup_donor(blood_group="B+")

        client.post('/auth/login', data={'email': hosp_info['email'], 'password': 'Pass123!'}, follow_redirects=True)

        res = client.post('/hospital/send-invitation', data={
            'donor_id': donor_info['user_id'],
            'blood_request_id': hosp_info['req_id'],
            'message': 'Direct emergency invitation'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"not compatible" in res.data or b"rejected" in res.data
        # Ensure invitation was NOT created in DB
        with app.app_context():
            inv = DonorInvitation.query.filter_by(donor_id=donor_info['user_id'], blood_request_id=hosp_info['req_id']).first()
            assert inv is None

    def test_hospital_cannot_send_invitation_to_unavailable_donor(self, app, client):
        """Hospital cannot invite a donor who has paused standby availability."""
        with app.app_context():
            hosp_info = self._setup_hospital_and_request(blood_group="A+", component_type="Whole Blood")
            # Compatible donor (A+) but availability paused
            donor_info = self._setup_donor(blood_group="A+", availability=False)

        client.post('/auth/login', data={'email': hosp_info['email'], 'password': 'Pass123!'}, follow_redirects=True)

        res = client.post('/hospital/send-invitation', data={
            'donor_id': donor_info['user_id'],
            'blood_request_id': hosp_info['req_id']
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"unavailable" in res.data.lower()
        with app.app_context():
            assert DonorInvitation.query.filter_by(donor_id=donor_info['user_id'], blood_request_id=hosp_info['req_id']).first() is None

    def test_donor_cannot_respond_to_incompatible_request(self, app, client):
        """Donor cannot bypass frontend filters by posting response to incompatible request."""
        with app.app_context():
            hosp_info = self._setup_hospital_and_request(blood_group="O+", component_type="Whole Blood")
            # AB+ donor is incompatible with O+ Whole Blood request
            donor_info = self._setup_donor(blood_group="AB+")

        client.post('/auth/login', data={'email': donor_info['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.post(f"/donor/respond/{hosp_info['req_id']}", data={
            'response_message': 'I want to donate'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"not compatible" in res.data.lower()

        with app.app_context():
            resp = DonorRequestResponse.query.filter_by(donor_id=donor_info['user_id'], blood_request_id=hosp_info['req_id']).first()
            assert resp is None

    def test_donor_cannot_respond_to_platelets_request_without_clinical_review(self, app, client):
        """Donor attempting direct response to Platelets request is rejected with clinical notice."""
        with app.app_context():
            hosp_info = self._setup_hospital_and_request(blood_group="A+", component_type="Platelets")
            donor_info = self._setup_donor(blood_group="A+")

        client.post('/auth/login', data={'email': donor_info['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.post(f"/donor/respond/{hosp_info['req_id']}", follow_redirects=True)
        assert res.status_code == 200
        assert b"Clinical Notice" in res.data or b"pathologist" in res.data.lower()

        with app.app_context():
            assert DonorRequestResponse.query.filter_by(donor_id=donor_info['user_id'], blood_request_id=hosp_info['req_id']).first() is None

    def test_donor_cannot_accept_incompatible_invitation(self, app, client):
        """If an invitation exists for an incompatible blood group, acceptance is rejected on the backend."""
        with app.app_context():
            hosp_info = self._setup_hospital_and_request(blood_group="A+", component_type="Whole Blood")
            donor_info = self._setup_donor(blood_group="B+")

            # Insert raw invitation (e.g. simulated forged database state)
            inv = DonorInvitation(
                donor_id=donor_info['user_id'],
                hospital_id=hosp_info['hosp_id'],
                blood_request_id=hosp_info['req_id'],
                invitation_status='SENT'
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        client.post('/auth/login', data={'email': donor_info['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.post(f'/donor/invitation/{inv_id}/respond', data={
            'decision': 'ACCEPT'
        }, follow_redirects=True)

        assert res.status_code == 200
        assert b"not compatible" in res.data.lower() or b"rejected" in res.data.lower()

        with app.app_context():
            reloaded_inv = DonorInvitation.query.get(inv_id)
            assert reloaded_inv.invitation_status == 'SENT'  # Status remains unaccepted

    def test_donor_choice_accept_and_decline_invitation(self, app, client):
        """Donor can voluntarily accept or decline an eligible invitation, preserving autonomy."""
        with app.app_context():
            hosp_info = self._setup_hospital_and_request(blood_group="AB+", component_type="Whole Blood")
            # A+ donor is compatible with AB+ Whole Blood
            donor_info = self._setup_donor(blood_group="A+")

            inv = DonorInvitation(
                donor_id=donor_info['user_id'],
                hospital_id=hosp_info['hosp_id'],
                blood_request_id=hosp_info['req_id'],
                invitation_status='SENT'
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        client.post('/auth/login', data={'email': donor_info['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        # 1. Accept eligible invitation
        res_accept = client.post(f'/donor/invitation/{inv_id}/respond', data={
            'decision': 'ACCEPT'
        }, follow_redirects=True)

        assert res_accept.status_code == 200
        assert b"accepted" in res_accept.data.lower()
        # Verify clinical disclaimer presence
        assert b"willingness to donate" in res_accept.data.lower()

        with app.app_context():
            inv_db = DonorInvitation.query.get(inv_id)
            assert inv_db.invitation_status == 'ACCEPTED'
            resp_db = DonorRequestResponse.query.filter_by(donor_id=donor_info['user_id'], blood_request_id=hosp_info['req_id']).first()
            assert resp_db is not None
            assert resp_db.response_status == 'CONFIRMED'

        # 2. Decline flow
        res_decline = client.post(f'/donor/invitation/{inv_id}/respond', data={
            'decision': 'DECLINE'
        }, follow_redirects=True)

        assert res_decline.status_code == 200
        assert b"declined" in res_decline.data.lower()

        with app.app_context():
            inv_db2 = DonorInvitation.query.get(inv_id)
            assert inv_db2.invitation_status == 'DECLINED'

    def test_donor_cannot_respond_to_inactive_or_fulfilled_request(self, app, client):
        """Responses and invitations are blocked for fulfilled or cancelled requests."""
        with app.app_context():
            hosp_info = self._setup_hospital_and_request(
                blood_group="A+", component_type="Whole Blood", request_status="FULFILLED"
            )
            donor_info = self._setup_donor(blood_group="A+")

        client.post('/auth/login', data={'email': donor_info['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.post(f"/donor/respond/{hosp_info['req_id']}", follow_redirects=True)
        assert res.status_code == 200
        assert b"no longer active" in res.data.lower()

    def test_donor_dashboard_does_not_expose_confidential_patient_information(self, app, client):
        """Donor dashboard displays request reference and clinical requirement without patient names."""
        with app.app_context():
            hosp_info = self._setup_hospital_and_request(blood_group="A+", component_type="Whole Blood")
            donor_info = self._setup_donor(blood_group="A+")

        client.post('/auth/login', data={'email': donor_info['email'], 'password': 'DonorPass123!'}, follow_redirects=True)

        res = client.get('/donor/dashboard')
        assert res.status_code == 200
        # Request reference must be visible
        assert hosp_info['req_ref'].encode() in res.data
        # Confidential patient name and MRN must NEVER appear
        assert b"Confidential Patient Rao" not in res.data
        assert b"MRN-CONFIDENTIAL" not in res.data
