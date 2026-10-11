"""
BloodLink AI - Visual Redesign & Public Views Test Suite.
Verifies the newly elevated public experiences:
- Landing Page (Hero, Compact Search, 8 Blood Groups, 4 Steps)
- Blood Availability Search (/search)
- Dedicated Blood Bank Directory (/blood-banks)
- Dedicated Donor Information & Eligibility Experience (/become-a-donor, /donors)
- Emergency Requests Triage Board (/emergency-requests, /requests)
"""

import pytest
from app import create_app
from app.extensions import db
from app.seeds.india_demo_data import seed_india_wide_demo_dataset


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        seed_india_wide_demo_dataset(app)
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


class TestRedesignViews:
    """Verifies all redesigned views, public routes, and e-RaktKosh inspired features."""

    def test_homepage_redesign_elements(self, client):
        """Homepage must display the official tagline, search card, and 8 blood groups."""
        res = client.get('/')
        assert res.status_code == 200
        assert b"Every Drop Connects a Life." in res.data
        assert b"Every Second Counts." in res.data
        assert b"Find Blood Near You" in res.data
        assert b"How BloodLink AI Works" in res.data
        assert b"Find Blood by Group" in res.data
        # Verify presence of all 8 blood groups on homepage
        for bg in [b"A+", b"A-", b"B+", b"B-", b"AB+", b"AB-", b"O+", b"O-"]:
            assert bg in res.data

    def test_search_page_title_and_indicators(self, client):
        """Search page must have required title and stock indicators."""
        res = client.get('/search?scope=all_india')
        assert res.status_code == 200
        assert b"Find Blood. Find Hope." in res.data
        assert b"Blood Availability Search" in res.data
        assert b"Units Available" in res.data or b"Reported" in res.data

    def test_dedicated_blood_banks_directory(self, client):
        """Blood bank directory page loads facilities, search filters, and map data."""
        res = client.get('/blood-banks')
        assert res.status_code == 200
        assert b"Explore Blood Banks Across India" in res.data
        assert b"Verified Blood Bank" in res.data

        # Filter by state
        res_mh = client.get('/blood-banks?state=Maharashtra')
        assert res_mh.status_code == 200
        assert b"Maharashtra" in res_mh.data

    def test_dedicated_become_a_donor_page(self, client):
        """Donor information page explains the 3 visual steps and clinical guidelines."""
        res = client.get('/become-a-donor')
        assert res.status_code == 200
        assert b"Be Someone's Reason to Smile." in res.data
        assert b"1. Register as a Donor" in res.data
        assert b"2. Donate at an Authorized Center" in res.data
        assert b"3. Have Donation Verified" in res.data
        assert b"WHO &amp; NBTC Clinical Eligibility Guidelines" in res.data

        # Alias /donors route
        res_alias = client.get('/donors')
        assert res_alias.status_code == 200
        assert b"Be Someone's Reason to Smile." in res_alias.data

    def test_dedicated_emergency_requests_triage(self, client):
        """Emergency requests board displays verified hospital requests with AI priority."""
        res = client.get('/emergency-requests')
        assert res.status_code == 200
        assert b"Emergency Blood Requests" in res.data
        assert b"AI Priority Score" in res.data or b"PRIORITY" in res.data

        # Alias /requests route
        res_alias = client.get('/requests')
        assert res_alias.status_code == 200
        assert b"Emergency Blood Requests" in res_alias.data
