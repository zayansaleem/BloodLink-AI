# 🩸 BloodLink AI

> **Connected Blood Banks, Smart Donor Matching & Reward System**  
> *AI-Powered HealthTech Web Application for Emergency Blood Donation Coordination*  
> *Built for Royal Hackathon 2026*

BloodLink AI is a centralized, digital healthcare platform that bridges voluntary blood donors, blood banks, hospitals, and coordinators during life-threatening blood shortages. It optimizes clinical response times through an explainable emergency prioritization algorithm, preliminary component-level donor matching, real-time blood bank inventory monitoring, and a verified donation rewards ledger with an interactive coupon marketplace.

---

## 🏗️ System Architecture & Workflow

```text
    [ Hospital Request ]
             │
             ▼
   [ Request Verification ]  <── Administrative verification barrier
             │
             ▼
[ Emergency Priority Calculation ]  <── Urgency, Scarcity, Quantity, Waiting Time
             │
             ▼
[ Blood Bank Inventory Search ]    <── Real-time 8 blood groups × 4 components
             │
             ▼
[ Preliminary Donor Matching ]     <── Compatibility, Haversine geo-distance, 56d cooldown
             │
             ▼
 [ Authorized Notifications ]      <── In-app alerts + optional SMTP email
             │
             ▼
  [ Donation Coordination ]        <── Hospital / Blood Bank appointment scheduling
             │
             ▼
  [ Donation Verification ]        <── Blood bank staff confirms actual donation
             │
             ▼
    [ Reward Points Ledgers ]      <── Transactional double-entry points credit
             │
             ▼
   [ Coupon Redemption ]           <── Partner voucher codes with expiry checks
```

---

## 📁 Repository Structure

```text
BloodLink_AI/
├── app/
│   ├── __init__.py                 # Flask application factory with CSRF & LoginManager
│   ├── extensions.py               # Shared extensions (SQLAlchemy, Migrate, LoginManager, CSRF)
│   ├── auth/                       # Authentication blueprint (Login, Register, Logout)
│   │   └── routes.py
│   ├── main/                       # Public landing, availability search, map, how-it-works
│   │   └── routes.py
│   ├── donor/                      # Donor portal (dashboard, eligibility, profile, perks)
│   │   └── routes.py
│   ├── hospital/                   # Hospital portal (request creator, live triage, donor match)
│   │   └── routes.py
│   ├── blood_bank/                 # Blood bank portal (inventory matrix, donation verification)
│   │   └── routes.py
│   ├── admin/                      # Admin portal (organization approval, requests, audit log, analytics)
│   │   └── routes.py
│   ├── matching/                   # Explainable algorithms
│   │   ├── compatibility.py        # ABO/Rh matrix for RBC, Platelets, Plasma, Whole Blood
│   │   ├── engine.py               # Haversine distance, match scoring, duplicate prevention
│   │   └── prioritization.py       # Explainable 0-100 triage scoring engine
│   ├── rewards/                    # Gamification and reward services
│   │   └── services.py             # Idempotent points issuance, atomic coupon redemptions
│   ├── notifications/              # Multichannel notification dispatch (in-app + SMTP)
│   │   └── services.py
│   ├── models/                     # SQLAlchemy relational schema
│   │   ├── user.py                 # User model (DONOR, HOSPITAL, BLOOD_BANK, ADMIN)
│   │   ├── donor.py                # DonorProfile, location, eligibility cooldown
│   │   ├── organization.py         # Organization (HOSPITAL, BLOOD_BANK) & membership
│   │   ├── inventory.py            # BloodInventory (8 groups × 4 components, freshness flags)
│   │   ├── request.py              # BloodRequest & DonorMatch tracking
│   │   ├── donation.py             # Donation lifecycle & verification records
│   │   ├── rewards.py              # RewardTransaction ledger, Coupon, CouponRedemption
│   │   ├── notification.py         # In-app notifications
│   │   └── audit.py                # Security & operational audit trail
│   ├── templates/                  # Bootstrap 5 responsive templates
│   │   ├── base.html               # HealthTech navbar, flash toasts, notification dropdown
│   │   ├── index.html              # Landing page with demo statistics disclosure
│   │   ├── search.html             # Real-time blood availability search
│   │   ├── map.html                # Leaflet & OpenStreetMap interactive facilities map
│   │   ├── about.html              # Mission, transparency, and clinical disclosures
│   │   ├── how_it_works.html       # Visual 4-step workflow walkthrough
│   │   ├── auth/                   # Login & registration forms with CSRF protection
│   │   ├── donor/                  # Donor dashboard, profile settings, and coupon shop
│   │   ├── hospital/               # Hospital request creation and match details
│   │   ├── blood_bank/             # Blood bank inventory manager and donation verification queue
│   │   ├── admin/                  # Admin organization verification, analytics, audit log
│   │   └── errors/                 # 403, 404, and 500 branded error pages
│   └── static/
│       ├── css/style.css           # Healthcare theme, crimson accents, subtle shadows
│       └── js/main.js              # Leaflet map initializers, tooltips, dynamic forms
├── migrations/                     # Database migration scripts (Flask-Migrate / Alembic)
├── tests/
│   ├── test_auth_and_security.py   # Password hashing, RBAC barrier, negative inventory check
│   ├── test_matching.py            # Clinical compatibility, Haversine, duplicate match prevention
│   ├── test_priority.py            # Triage weights, inactive rejection, deadline sensitivity
│   ├── test_requests_and_roles.py  # Unauthenticated redirects, 403 barriers, unverified org rules
│   └── test_rewards.py             # Atomic ledger transactions, overspending rejection, expiry
├── config.py                       # Development, Testing, and Production configurations
├── run.py                          # CLI runner, synthetic demo data seed function, admin creator
├── render.yaml                     # Render cloud deployment configuration with PostgreSQL
├── requirements.txt                # Production dependencies
├── .env.example                    # Template environment variables
├── .gitignore                      # Python, SQLite, cache ignore rules
└── README.md                       # Comprehensive platform documentation
```

---

## 🛡️ Enterprise Security & Hardening Architecture

BloodLink AI integrates a comprehensive multi-layered defensive security model:

### 1. Brute-Force Defense & Rate Limiting
- **Flask-Limiter Integration**: Distributed rate limiting (`RATELIMIT_STORAGE_URI` supports Redis in multi-worker environments, defaulting to in-memory store in development).
- **Endpoint Throttling**: Strict limits applied across authentication endpoints:
  - Login: `10 per minute; 50 per hour`
  - Registration: `5 per minute; 20 per hour`
  - Password Reset: `3 per minute; 10 per hour`
- **Account-Level Temporary Lockout**: Tracks consecutive failed login attempts on a per-account basis. After 5 consecutive failures, the account is temporarily locked for 15 minutes (`is_temporarily_locked()`).
- **Generic Error Responses**: Rejects account enumeration attacks by returning generic error messages (*"Unable to sign in with the supplied credentials."*) for nonexistent emails, incorrect passwords, and locked or inactive states.
- **Session Fixation Prevention**: Session state is cleared and regenerated upon authentication (`session.clear()` before `login_user()`).
- **Open-Redirect Protection**: Incoming `?next=` parameters are strictly validated using `is_safe_url()` to verify that redirects remain within the application domain.

### 2. Multi-Factor Authentication (Admin MFA / TOTP)
- **Time-Based One-Time Passwords (RFC 6238)**: Built using `pyotp` for platform super-administrators.
- **Enforcement Policy**: Mandatory in production (`REQUIRE_ADMIN_MFA = True`) and for enrolled accounts. Step-up verification intercepts access to `/admin/*` consoles until the 6-digit TOTP code is verified.
- **MFA Enrollment Workflow**: QR code generation and secret provisioning at `/auth/setup-mfa`.

### 3. Administrative Governance & User Management
- **Centralized Security Console**: Dedicated administrator console at `/admin/users` to audit account states, failed attempt counters, and MFA enrollment.
- **Manual Lockout Override**: Administrators can manually clear brute-force lockouts for legitimate users locked out by automated attacks (`/admin/users/<id>/unlock`), recording a mandatory audit justification and client IP.
- **Account Suspension & Reactivation**: Immediate revocation of compromised accounts (`/admin/users/<id>/toggle-status`), with self-suspension guardrails protecting active super-admins.
- **Immutable Audit Logging**: Every administrative action, organization approval, account lockout, suspension, and inventory change is recorded in `AuditLog` with timestamp, actor ID, client IP address, and justification details.

### 4. Cryptographic Password Reset Lifecycle
- **Single-Use Hashed Tokens**: Generates 32-byte cryptographic random reset tokens (`secrets.token_urlsafe(32)`).
- **Hashed at Rest**: Tokens are stored as SHA-256 hashes (`token_hash`), ensuring that database compromises do not expose valid reset credentials.
- **Expiration & Invalidation**: Tokens expire strictly after 15 minutes and are automatically invalidated upon first use or when a new token is requested.

### 5. HTTP Security Headers & Defense-in-Depth
Every HTTP response automatically includes defensive security headers via an application `after_request` filter:
- `Content-Security-Policy`: Restricts scripts, styles, fonts, frames, and prevents UI clickjacking (`frame-ancestors 'none'`).
- `X-Content-Type-Options: nosniff`: Prevents MIME-type sniffing.
- `X-Frame-Options: DENY`: Blocks embedding inside malicious `<iframe>` tags.
- `Referrer-Policy: strict-origin-when-cross-origin`: Shields referrer URLs on cross-origin requests.
- `Strict-Transport-Security (HSTS)`: Enforces HTTPS in production environments.

---

## 📱 Fully Responsive Design & UI/UX

BloodLink AI is engineered using a mobile-first responsive architecture supporting all viewports from **320px smartphones to 1920px large displays**:

- **Offcanvas Mobile Navigation**: Clean Bootstrap 5 Offcanvas drawer for screens `< 992px`, with accessible touch target padding ($\ge 44\text{px}$), ARIA attributes, and automatic menu dismissal on navigation.
- **Touch-Optimized Form Controls**: Form inputs enforce a minimum font size of `16px` on mobile viewports to eliminate automatic iOS Safari viewport zoom, and all interactive elements provide touch-friendly spacing.
- **Adaptive Leaflet Maps**: Leaflet OpenStreetMap containers adapt dynamically across breakpoints (`340px` on desktop, `290px` on tablet, `250px` on mobile), with automatic `map.invalidateSize()` triggered on container resize.
- **Responsive Chart.js Dashboards**: Charts maintain bounded aspect ratios (`maintainAspectRatio: false` within responsive `.chart-container-responsive` wrappers) to prevent vertical stretching and horizontal clipping.
- **Card-Based Mobile Table Layouts**: Data tables feature horizontal touch scrolling containers (`.table-responsive`) and compact card layouts for donor directories, blood inventory matrices, and audit trail logs.
- **Horizontal Overflow Defense**: Root styles enforce `overflow-x: clip; max-width: 100vw;` preventing accidental horizontal layout wobble across all devices.

---

## 👥 Role-Based Access Control (RBAC)

BloodLink AI enforces strict role isolation with custom decorators (`@role_required`, `@admin_required`, `@verified_org_required`):

| Role | Primary Dashboard | Key Permissions | Verification Required |
| :--- | :--- | :--- | :--- |
| **Donor** | `/donor/dashboard` | Update standby availability, view relevant verified requests, view donation records, redeem coupons | Automatic on registration |
| **Hospital** | `/hospital/dashboard` | Create blood requests, view explainable match rankings, track dispatch status | **Yes** (Admin approval required) |
| **Blood Bank** | `/blood-bank/dashboard` | Update 8-group component inventory matrix, verify incoming donations, issue reward points | **Yes** (Admin approval required) |
| **Administrator** | `/admin/dashboard` | Verify healthcare organizations, approve clinical blood requests, manage coupons, review audit logs, user security governance | Setup via secure CLI only |

> [!IMPORTANT]
> Unverified organizations cannot create trusted blood requests, update active public inventory, or verify donations until explicitly audited and approved by a platform administrator. Unverified accounts attempting trusted actions are directed to `/auth/verification-status`.

---

## 🔑 Pre-Seeded Demonstration Credentials

For evaluation and testing, the application comes seeded with synthetic demonstration datasets (explicitly tagged as demo records):

| Role | Email | Password | Organization / Notes |
| :--- | :--- | :--- | :--- |
| **Administrator** | `admin@bloodlink.ai` | `admin123` | Platform Super-Administrator |
| **Hospital Staff** | `apollo@hospital.com` | `hospital123` | Apollo Hospital Bannerghatta (Verified) |
| **Blood Bank Staff**| `redcross@bloodbank.org`| `bloodbank123` | Rotary Red Cross Central Blood Bank (Verified) |
| **Donor (O-)** | `arjun@donor.com` | `donor123` | Arjun Sharma (Universal RBC Donor, 300 pts) |
| **Donor (A+)** | `priya@donor.com` | `donor123` | Dr. Priya Patel (Active Donor, 150 pts) |
| **Donor (B-)** | `sneha@donor.com` | `donor123` | Sneha Reddy (Active Donor, 50 pts) |

---

## 🧠 Core Intelligent Algorithms

### 1. Explainable Emergency Prioritization Engine (`0` to `100` score)
Triage urgency is calculated mathematically across 4 clinical factors:
- **Clinical Urgency (Max 50 pts)**: `CRITICAL` (Immediate/ICU: 50 pts), `HIGH` (Within 6h: 35 pts), `MEDIUM` (Within 24h: 20 pts), `ROUTINE` (10 pts).
- **Population Scarcity (Max 25 pts)**: Accounts for ABO/Rh prevalence (AB-: 25 pts, O- universal deficit: 24 pts, B-: 22 pts, A-: 20 pts).
- **Volume Need (Max 15 pts)**: Scaled by units required (5+ units: 15 pts, 3-4 units: 10 pts, 2 units: 6 pts, 1 unit: 3 pts).
- **Waiting Time Decay (+1.5 pts/hr, Max 15 pts)**: Prevents starvation of unattended requests over elapsed time.
- **Deadline Proximity Boost**: Extra escalation for requests within 4 hours of their clinical deadline.

### 2. Multi-Factor Smart Donor Match Engine
- **Medical Component Compatibility**: Full support for Whole Blood, Packed Red Blood Cells (RBC), Platelets, and Plasma (where AB is the universal plasma donor).
- **Haversine Geo-Distance Decay**: Calculates great-circle distance in kilometers based on anonymized donor city/district coordinates.
- **56-Day Cooldown Validation**: Strictly enforces WHO/NACO recovery intervals since the donor's last recorded donation date.
- **Duplicate Match Prevention**: Database-level unique constraints and lookup checks prevent repetitive notifications for the same request.

### 3. Double-Entry Rewards & Coupon Marketplace
- Points are issued idempotently only after blood bank verification of actual donations.
- Coupon redemptions enforce atomic ledger debiting and generate cryptographically unique voucher codes (`VCHR-XXXX-XXXX`).
- Automatic prevention of overspending, concurrent double-claims, and expired voucher usage.

---

## 🛠️ Secure Administrator Setup Procedure

Platform administrator accounts cannot be self-registered through the web UI. To securely provision an administrator account:

### Using the Python CLI:
```bash
python -c "
from app import create_app, db
from app.models.user import User

app = create_app()
with app.app_context():
    admin = User(name='Lead Admin', email='admin@bloodlink.ai', role='ADMIN', is_active=True, email_verified=True)
    admin.set_password('SuperSecretAdminPassword!')
    db.session.add(admin)
    db.session.commit()
    print('Administrator created successfully!')
"
```

---

## 🚀 Local Development Setup

### 1. Prerequisites
- Python 3.10+ (Tested on Python 3.13)
- SQLite (built-in) or PostgreSQL

### 2. Installation
```bash
# Clone the repository
git clone <repository-url>
cd BloodLink_AI

# Create and activate a virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the Application
```bash
python run.py
```
> The startup script automatically initializes the database tables and seeds synthetic demonstration records.

Access the platform at: **`http://127.0.0.1:5000`**

---

## 🧪 Automated Test Suite

Run the comprehensive pytest suite verifying security, compatibility, priority, and ledger integrity:

```bash
python -m pytest -v
```

### Test Coverage Highlights (79 Passing Tests):
- `test_security_hardening.py`: Responsive meta viewports, offcanvas navigation, rate-limit 429 throttling, per-account brute-force temporary lockout, generic authentication errors, single-use cryptographic password reset tokens, admin TOTP MFA, account suspension/reactivation, manual lockout release, open-redirect defense, and HTTP security headers.
- `test_auth_and_security.py`: Password hashing, RBAC barriers, unverified organization flags, negative inventory constraints.
- `test_requests_and_roles.py`: Unauthenticated redirects, 403 forbidden responses, unverified organization access restrictions.
- `test_end_to_end_workflows.py`: Complete user journeys for Donors, Hospitals, Blood Banks, Rewards, and Administrators.
- `test_india_dataset.py`: All 36 Indian states & union territories represented, synthetic demo record flags, search breadth.
- `test_locations.py`: Hierarchy validation, district mapping integrity, and REST API lookup endpoints.
- `test_matching.py`: Component compatibility (Whole Blood, RBC, Plasma), Haversine geo-distance, duplicate match prevention.
- `test_persistence.py`: SQLite WAL transactions, rollback integrity, and cross-session persistence.
- `test_priority.py`: Triage weights, inactive request rejection, unverified request baseline, deadline proximity boost.
- `test_redesign_views.py`: Directory views, availability triage, and responsive layout elements.
- `test_rewards.py`: Idempotent points issuance, atomic coupon redemptions, expired coupon rejection.
- `test_audit_fixes.py`: Edge cases, scarcity calculations, and self-verification prevention.

**Result**: 79 passed with 0 failures and 0 regressions.

---

## ☁️ Production Deployment on Render

This repository is pre-configured for automated zero-downtime deployment on Render:

1. Connect your GitHub repository to [Render](https://render.com).
2. Create a new **Blueprint** and select `render.yaml`.
3. Render will provision:
   - A managed **PostgreSQL** database (`bloodlink-db`).
   - A **Python Web Service** running Gunicorn:
     ```bash
     gunicorn "run:app" --bind 0.0.0.0:$PORT
     ```
4. Set your production environment variables in the Render dashboard:
   - `SECRET_KEY`: High-entropy random string.
   - `DATABASE_URL`: Injected automatically from the Render PostgreSQL service.
   - `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`: (Optional) for live email dispatch.

---

## ⚖️ Ethics, Privacy, and Clinical Disclaimers
1. **Preliminary Matching Only**: Matches produced by BloodLink AI are preliminary coordination suggestions and do not replace mandatory laboratory cross-matching, serology screening, or medical donor interview protocols.
2. **Privacy Protection**: Exact residential addresses of voluntary donors are never collected or exposed. Only city and district approximations are stored.
3. **Synthetic Demonstration Data**: All pre-loaded statistics, donor profiles, hospital inventories, and requests are synthetic demonstration records for hackathon evaluation.

---

## 📄 License
MIT License. Developed for the **Royal Hackathon 2026**.
