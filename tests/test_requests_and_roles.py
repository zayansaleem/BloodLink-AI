import pytest
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.organization import Organization, OrganizationMembership
from app.models.request import BloodRequest


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


class TestRolesAndPermissionsWorkflow:
    """End-to-end integration tests for role separation and verification barriers."""

    def test_unauthenticated_redirect(self, client):
        # Accessing protected dashboards must redirect to login
        res = client.get('/donor/dashboard')
        assert res.status_code == 302
        assert '/auth/login' in res.headers['Location']

        res_admin = client.get('/admin/dashboard')
        assert res_admin.status_code == 302
        assert '/auth/login' in res_admin.headers['Location']

    def test_donor_cannot_access_admin_dashboard(self, app, client):
        donor = User(name="Donor Test", email="donor1@test.com", role="DONOR")
        donor.set_password("pass123")
        db.session.add(donor)
        db.session.commit()

        # Login as donor
        client.post('/auth/login', data={'email': 'donor1@test.com', 'password': 'pass123'})

        # Try to access admin dashboard -> 403 Forbidden
        res = client.get('/admin/dashboard')
        assert res.status_code == 403

    def test_unverified_hospital_cannot_create_trusted_request(self, app, client):
        hosp_org = Organization(
            organization_name="Pending Hospital", organization_type="HOSPITAL",
            address="Addr", contact_phone="123", verification_status="PENDING"
        )
        db.session.add(hosp_org)
        db.session.flush()

        hosp_user = User(name="Dr. Pending", email="pending@hosp.com", role="HOSPITAL")
        hosp_user.set_password("pass123")
        db.session.add(hosp_user)
        db.session.flush()

        db.session.add(OrganizationMembership(organization_id=hosp_org.id, user_id=hosp_user.id, membership_role="ADMIN"))
        db.session.commit()

        # Login as hospital
        client.post('/auth/login', data={'email': 'pending@hosp.com', 'password': 'pass123'})

        # Try accessing request creation -> redirected back to dashboard with warning
        res = client.get('/hospital/request/new')
        assert res.status_code == 302
        assert '/hospital/dashboard' in res.headers['Location']

        # Now approve verification
        hosp_org.verification_status = "VERIFIED"
        db.session.commit()

        # Now authorized
        res_ok = client.get('/hospital/request/new')
        assert res_ok.status_code == 200
