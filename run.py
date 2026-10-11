import os
import sys
from datetime import datetime, timezone, date, timedelta
from dotenv import load_dotenv
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest
from app.models.donation import Donation
from app.models.rewards import RewardTransaction, Coupon, CouponRedemption
from app.models.notification import Notification
from app.models.audit import AuditLog
from app.matching.prioritization import update_request_priority
from app.matching.engine import run_donor_matching

from app.seeds.india_demo_data import seed_india_wide_demo_dataset

# Load environment variables
load_dotenv()

app = create_app(os.environ.get('FLASK_ENV', 'development'))


def seed_synthetic_demo_data():
    """Populate database with pan-India synthetic demonstration data clearly marked as demonstration records."""
    with app.app_context():
        db.create_all()
        seed_india_wide_demo_dataset(app)
        print("[+] Pan-India synthetic demonstration dataset initialized!")


if __name__ == '__main__':
    seed_synthetic_demo_data()
    port = int(os.environ.get('PORT', 5000))
    print(f"[+] BloodLink AI server running on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
