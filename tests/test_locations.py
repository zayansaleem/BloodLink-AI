import pytest
from app import create_app, db
from app.locations import (
    INDIAN_STATES,
    UNION_TERRITORIES,
    INDIA_DISTRICTS,
    get_all_states,
    get_states_only,
    get_union_territories_only,
    get_districts_for_state,
    is_valid_state,
    is_valid_district,
    get_all_locations_hierarchy
)
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization
from app.models.request import BloodRequest
from app.matching.engine import calculate_donor_match_score


@pytest.fixture
def test_client():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        client = app.test_client()
        yield client
        db.session.remove()
        db.drop_all()


def test_all_28_states_and_8_union_territories():
    """Verify that all 28 Indian States and 8 Union Territories are defined."""
    states_only = get_states_only()
    uts_only = get_union_territories_only()
    all_states = get_all_states()

    assert len(states_only) == 28, f"Expected 28 states, got {len(states_only)}"
    assert len(uts_only) == 8, f"Expected 8 UTs, got {len(uts_only)}"
    assert len(all_states) == 36, f"Expected 36 total territories, got {len(all_states)}"

    expected_states = [
        "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
        "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
        "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
        "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
        "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
        "Uttar Pradesh", "Uttarakhand", "West Bengal"
    ]
    for state in expected_states:
        assert state in states_only, f"Missing state: {state}"
        assert is_valid_state(state) is True

    expected_uts = [
        "Andaman and Nicobar Islands", "Chandigarh",
        "Dadra and Nagar Haveli and Daman and Diu", "Delhi",
        "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry"
    ]
    for ut in expected_uts:
        assert ut in uts_only, f"Missing union territory: {ut}"
        assert is_valid_state(ut) is True


def test_district_mappings_and_validation():
    """Verify district mappings and validate combinations."""
    # Test Maharashtra districts
    mh_districts = get_districts_for_state("Maharashtra")
    assert "Pune" in mh_districts
    assert "Nagpur" in mh_districts
    assert "Nashik" in mh_districts
    assert is_valid_district("Maharashtra", "Pune") is True
    assert is_valid_district("Maharashtra", "Nagpur") is True

    # Test Kerala districts
    kl_districts = get_districts_for_state("Kerala")
    assert "Ernakulam" in kl_districts
    assert "Kozhikode" in kl_districts
    assert "Thrissur" in kl_districts
    assert "Kollam" in kl_districts
    assert is_valid_district("Kerala", "Ernakulam") is True

    # Test Karnataka districts
    ka_districts = get_districts_for_state("Karnataka")
    assert "Bengaluru Urban" in ka_districts
    assert "Mysuru" in ka_districts
    assert is_valid_district("Karnataka", "Bengaluru Urban") is True

    # Test invalid combinations
    assert is_valid_state("Atlantis") is False
    assert is_valid_district("Maharashtra", "Ernakulam") is False
    assert is_valid_district("Kerala", "Pune") is False
    assert is_valid_district("Atlantis", "Pune") is False


def test_location_rest_api_endpoints(test_client):
    """Test location REST API endpoints."""
    # /api/locations/states
    res = test_client.get('/api/locations/states')
    assert res.status_code == 200
    data = res.get_json()
    assert data['count'] == 36
    assert len(data['states']) == 36

    # /api/locations/districts?state=Maharashtra
    res = test_client.get('/api/locations/districts?state=Maharashtra')
    assert res.status_code == 200
    data = res.get_json()
    assert data['state'] == 'Maharashtra'
    assert 'Pune' in data['districts']

    # /api/locations/hierarchy
    res = test_client.get('/api/locations/hierarchy')
    assert res.status_code == 200
    data = res.get_json()
    assert len(data) == 36
    assert 'Kerala' in data
    assert 'Ernakulam' in data['Kerala']

    # /api/locations/validate
    res = test_client.get('/api/locations/validate?state=Maharashtra&district=Pune')
    assert res.status_code == 200
    assert res.get_json()['valid'] is True

    res = test_client.get('/api/locations/validate?state=Maharashtra&district=Ernakulam')
    assert res.status_code == 200
    assert res.get_json()['valid'] is False


def test_search_scope_and_filters(test_client):
    """Test blood availability search with state, district and search scopes."""
    # Test GET /search with various params
    res = test_client.get('/search?scope=all_india')
    assert res.status_code == 200
    assert b"Blood Availability Search" in res.data

    res = test_client.get('/search?scope=state&state=Maharashtra')
    assert res.status_code == 200

    res = test_client.get('/search?scope=district&state=Maharashtra&district=Pune')
    assert res.status_code == 200

    # With invalid state, should flash warning or handle gracefully
    res = test_client.get('/search?state=InvalidStateXYZ', follow_redirects=True)
    assert res.status_code == 200


def test_coarse_location_matching_fallback(test_client):
    """Test matching engine fallback when coordinates are missing."""
    donor_user = User(
        name="Test Pune Donor",
        email="pune_donor@example.com",
        role="DONOR",
        is_active=True
    )
    donor_user.set_password("pass123")
    db.session.add(donor_user)
    db.session.commit()

    donor = DonorProfile(
        user_id=donor_user.id,
        declared_blood_group='O+',
        state='Maharashtra',
        district='Pune',
        city='Pune',
        latitude=None,
        longitude=None,
        availability_status=True,
        notification_consent=True
    )
    db.session.add(donor)
    db.session.commit()

    request_same_district = BloodRequest(
        request_reference='REQ-COARSE-01',
        requesting_organization_id=1,
        blood_group='O+',
        component_type='Whole Blood',
        units_required=1,
        urgency_level='HIGH',
        state='Maharashtra',
        district='Pune',
        city='Pune',
        latitude=None,
        longitude=None
    )

    request_diff_district_same_state = BloodRequest(
        request_reference='REQ-COARSE-02',
        requesting_organization_id=1,
        blood_group='O+',
        component_type='Whole Blood',
        units_required=1,
        urgency_level='HIGH',
        state='Maharashtra',
        district='Nagpur',
        city='Nagpur',
        latitude=None,
        longitude=None
    )

    score_same_district, factors_district = calculate_donor_match_score(donor_user, request_same_district)
    score_same_state, factors_state = calculate_donor_match_score(donor_user, request_diff_district_same_state)

    # Same district should have higher score than different district in same state
    assert score_same_district > score_same_state
    assert score_same_district >= 75.0
    assert factors_district['proximity_score'] == 85.0
    assert factors_state['proximity_score'] == 50.0


def test_donor_registration_location_validation(test_client):
    """Test that donor registration enforces genuine Indian state and district pairing."""
    # 1. Invalid State should be rejected
    res_bad_state = test_client.post('/auth/register', data={
        'reg_type': 'donor',
        'name': 'Test User',
        'email': 'bad_state@test.com',
        'password': 'password123',
        'confirm_password': 'password123',
        'blood_group': 'B+',
        'state': 'FictionalState',
        'district': 'Pune',
        'city': 'SampleCity'
    }, follow_redirects=True)
    assert b"Invalid State" in res_bad_state.data

    # 2. Mismatched District should be rejected
    res_bad_pair = test_client.post('/auth/register', data={
        'reg_type': 'donor',
        'name': 'Test User',
        'email': 'bad_pair@test.com',
        'password': 'password123',
        'confirm_password': 'password123',
        'blood_group': 'B+',
        'state': 'Maharashtra',
        'district': 'Ernakulam',  # Ernakulam belongs to Kerala, not Maharashtra
        'city': 'SampleCity'
    }, follow_redirects=True)
    assert b"Invalid District" in res_bad_pair.data

    # 3. Valid State and District should succeed
    res_valid = test_client.post('/auth/register', data={
        'reg_type': 'donor',
        'name': 'Valid Donor',
        'email': 'valid_donor_india@test.com',
        'password': 'password123',
        'confirm_password': 'password123',
        'blood_group': 'O+',
        'state': 'Kerala',
        'district': 'Ernakulam',
        'city': 'Kochi',
        'notification_consent': 'on'
    }, follow_redirects=True)
    assert res_valid.status_code == 200
    donor_created = User.query.filter_by(email='valid_donor_india@test.com').first()
    assert donor_created is not None
    assert donor_created.donor_profile.state == 'Kerala'
    assert donor_created.donor_profile.district == 'Ernakulam'
    assert donor_created.donor_profile.city == 'Kochi'

