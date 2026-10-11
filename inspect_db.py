"""
BloodLink AI - Database Diagnostic & Inspection Utility.
Provides safe, development-only inspection of the active database connection,
physical SQLite file path, table structures, and record counts without exposing credentials.
"""

import os
import sys
from pathlib import Path
from datetime import datetime

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import get_database_url
from app import create_app
from app.extensions import db
from sqlalchemy import inspect, text


def redact_uri(uri_str: str) -> str:
    """Safely redact credentials from database URI."""
    if not uri_str:
        return ""
    if "@" in uri_str:
        prefix, remainder = uri_str.split("@", 1)
        if "://" in prefix:
            scheme, _ = prefix.split("://", 1)
            return f"{scheme}://***:***@{remainder}"
    return uri_str


def run_database_inspection():
    print("=" * 70)
    print(" BLOODLINK AI — ACTIVE DATABASE DIAGNOSTIC REPORT")
    print("=" * 70)

    raw_uri = get_database_url()
    safe_uri = redact_uri(raw_uri)
    print(f"\n[1] CONFIGURATION:")
    print(f"    • Base Directory       : {BASE_DIR}")
    print(f"    • Database URI         : {safe_uri}")

    app = create_app('development')

    with app.app_context():
        engine_url = db.engine.url
        db_file = engine_url.database

        print(f"\n[2] ACTIVE DATABASE FILE ON DISK:")
        if db_file and db_file != ':memory:':
            abs_path = os.path.abspath(db_file)
            exists = os.path.exists(abs_path)
            print(f"    • Exact File Path      : {abs_path}")
            print(f"    • File Exists On Disk  : {'YES [OK]' if exists else 'NO [MISSING]'}")
            if exists:
                size_bytes = os.path.getsize(abs_path)
                mtime = datetime.fromtimestamp(os.path.getmtime(abs_path)).strftime('%Y-%m-%d %H:%M:%S')
                print(f"    • File Size            : {size_bytes:,} bytes ({size_bytes / 1024:.1f} KB)")
                print(f"    • Last Modified        : {mtime}")
        else:
            print(f"    • Type                 : In-Memory Database (:memory:)")

        # Pragmas
        if db.engine.url.drivername.startswith('sqlite'):
            try:
                journal_mode = db.session.execute(text("PRAGMA journal_mode;")).scalar()
                busy_timeout = db.session.execute(text("PRAGMA busy_timeout;")).scalar()
                print(f"    • SQLite Journal Mode  : {journal_mode}")
                print(f"    • SQLite Busy Timeout  : {busy_timeout} ms")
            except Exception as e:
                print(f"    • Pragma Query Error   : {e}")

        # Tables
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()
        print(f"\n[3] DATABASE SCHEMA & TABLES ({len(table_names)} tables found):")
        print(f"    • Tables: {', '.join(sorted(table_names))}")

        expected_core_tables = ['users', 'donor_profiles', 'organizations', 'blood_requests', 'blood_inventories', 'donations']
        missing_tables = [t for t in expected_core_tables if t not in table_names]
        if missing_tables:
            print(f"    • [WARNING] Missing core tables: {missing_tables}")
        else:
            print(f"    • Core Tables Check    : ALL REQUIRED TABLES PRESENT [OK]")

        # Record Counts
        print(f"\n[4] PERSISTED RECORD COUNTS:")
        from app.models.user import User
        from app.models.donor import DonorProfile
        from app.models.organization import Organization
        from app.models.inventory import BloodInventory
        from app.models.request import BloodRequest
        from app.models.donation import Donation
        from app.models.rewards import Coupon, RewardTransaction
        from app.models.audit import AuditLog

        total_users = User.query.count()
        total_donors = DonorProfile.query.count()
        total_orgs = Organization.query.count()
        total_hospitals = Organization.query.filter_by(organization_type='HOSPITAL').count()
        total_banks = Organization.query.filter_by(organization_type='BLOOD_BANK').count()
        total_requests = BloodRequest.query.count()
        total_inventory_records = BloodInventory.query.count()
        total_donations = Donation.query.count()
        total_coupons = Coupon.query.count()
        total_tx = RewardTransaction.query.count()
        total_audits = AuditLog.query.count()

        print(f"    • users                : {total_users} (DONOR: {User.query.filter_by(role='DONOR').count()}, HOSPITAL: {User.query.filter_by(role='HOSPITAL').count()}, BLOOD_BANK: {User.query.filter_by(role='BLOOD_BANK').count()}, ADMIN: {User.query.filter_by(role='ADMIN').count()})")
        print(f"    • donor_profiles       : {total_donors}")
        print(f"    • organizations        : {total_orgs} ({total_hospitals} Hospitals, {total_banks} Blood Banks)")
        print(f"    • blood_inventories    : {total_inventory_records}")
        print(f"    • blood_requests       : {total_requests}")
        print(f"    • donations            : {total_donations}")
        print(f"    • coupons              : {total_coupons}")
        print(f"    • reward_transactions  : {total_tx}")
        print(f"    • audit_logs           : {total_audits}")

        # Real Non-Demo Users (Zayan, Sarang, etc.)
        non_demo_users = User.query.filter_by(is_demo=False).all()
        print(f"\n[5] NON-DEMONSTRATION USERS ({len(non_demo_users)} verified accounts):")
        for u in non_demo_users:
            role_detail = f"Role: {u.role}"
            profile_detail = f"Blood Group: {u.donor_profile.declared_blood_group}, State: {u.donor_profile.state}" if u.donor_profile else "No profile"
            print(f"    • [User #{u.id}] {u.name} <{u.email}> | {role_detail} | {profile_detail}")

    print("\n" + "=" * 70)
    print(" INSTRUCTIONS FOR DB BROWSER FOR SQLITE:")
    print("=" * 70)
    if db_file and db_file != ':memory:':
        print(f" 1. Open DB Browser for SQLite.")
        print(f" 2. Click 'Open Database' and browse to this EXACT file:")
        print(f"    {os.path.abspath(db_file)}")
        print(f" 3. Switch to the 'Browse Data' tab.")
        print(f" 4. In the 'Table' dropdown, select 'users' or 'donor_profiles'.")
        print(f" 5. IMPORTANT: DB Browser DOES NOT auto-refresh! Press F5 or click the")
        print(f"    Refresh icon in DB Browser after submitting web forms.")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    run_database_inspection()
