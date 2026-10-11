"""
BloodLink AI - Comprehensive Pan-India Synthetic Demonstration Dataset.
Idempotent seeder covering all 28 Indian States & 8 Union Territories with official district hierarchies.
Every synthetic record is explicitly flagged with is_demo = True.
"""

from datetime import datetime, timezone, date, timedelta
from app.extensions import db
from app.models.user import User
from app.models.donor import DonorProfile
from app.models.organization import Organization, OrganizationMembership
from app.models.inventory import BloodInventory
from app.models.request import BloodRequest
from app.models.donation import Donation
from app.models.rewards import RewardTransaction, Coupon
from app.models.audit import AuditLog
from app.matching.prioritization import update_request_priority
from app.matching.engine import run_donor_matching
from app.locations import is_valid_state, is_valid_district


# =============================================================================
# DATA DEFINITIONS: PAN-INDIA HOSPITALS (~14 Across Multiple States & UTs)
# =============================================================================
HOSPITALS_DATA = [
    # 1. Karnataka - Bengaluru
    {
        "name": "Apollo Hospital Bannerghatta [DEMO]",
        "reference": "DEMO-HOSP-KA-01",
        "rep_email": "apollo@hospital.com",
        "rep_name": "Dr. Apollo Coordinator",
        "address": "154/11, Bannerghatta Main Road",
        "state": "Karnataka",
        "district": "Bengaluru Urban",
        "city": "Bengaluru",
        "lat": 12.8913, "lng": 77.5973,
        "phone": "+91 80 2630 4050",
        "status": "VERIFIED"
    },
    # 2. Kerala - Kochi / Ernakulam
    {
        "name": "Amrita Institute of Medical Sciences [DEMO]",
        "reference": "DEMO-HOSP-KL-01",
        "rep_email": "amrita.kochi@demo.bloodlink.ai",
        "rep_name": "Dr. Madhavan Nair",
        "address": "AIMS Ponekkara, Edappally",
        "state": "Kerala",
        "district": "Ernakulam",
        "city": "Kochi",
        "lat": 9.9816, "lng": 76.2999,
        "phone": "+91 484 285 1234",
        "status": "VERIFIED"
    },
    # 3. Maharashtra - Mumbai
    {
        "name": "KEM Hospital Parel [DEMO]",
        "reference": "DEMO-HOSP-MH-01",
        "rep_email": "kem.mumbai@demo.bloodlink.ai",
        "rep_name": "Dr. Ananya Deshmukh",
        "address": "Acharya Donde Marg, Parel",
        "state": "Maharashtra",
        "district": "Mumbai Suburban",
        "city": "Mumbai",
        "lat": 19.0024, "lng": 72.8427,
        "phone": "+91 22 2410 7000",
        "status": "VERIFIED"
    },
    # 4. Maharashtra - Pune
    {
        "name": "Sancheti Orthopedic Hospital [DEMO]",
        "reference": "DEMO-HOSP-MH-02",
        "rep_email": "sancheti.pune@demo.bloodlink.ai",
        "rep_name": "Dr. Parag Sancheti",
        "address": "16, Shivajinagar",
        "state": "Maharashtra",
        "district": "Pune",
        "city": "Pune",
        "lat": 18.5293, "lng": 73.8504,
        "phone": "+91 20 2899 9999",
        "status": "VERIFIED"
    },
    # 5. Tamil Nadu - Chennai
    {
        "name": "Apollo Children's Hospital [DEMO]",
        "reference": "DEMO-HOSP-TN-01",
        "rep_email": "apollo.chennai@demo.bloodlink.ai",
        "rep_name": "Dr. K. Swaminathan",
        "address": "No. 15, Shafee Mohammed Road, Thousand Lights",
        "state": "Tamil Nadu",
        "district": "Chennai",
        "city": "Chennai",
        "lat": 13.0617, "lng": 80.2520,
        "phone": "+91 44 2829 0200",
        "status": "VERIFIED"
    },
    # 6. Telangana - Hyderabad
    {
        "name": "Apollo Health City Jubilee Hills [DEMO]",
        "reference": "DEMO-HOSP-TG-01",
        "rep_email": "apollo.hyd@demo.bloodlink.ai",
        "rep_name": "Dr. Ramesh Rao",
        "address": "Road No. 72, Film Nagar, Jubilee Hills",
        "state": "Telangana",
        "district": "Hyderabad",
        "city": "Hyderabad",
        "lat": 17.4198, "lng": 78.4116,
        "phone": "+91 40 2360 7777",
        "status": "VERIFIED"
    },
    # 7. Delhi - New Delhi
    {
        "name": "Fortis Escorts Heart Institute [DEMO]",
        "reference": "DEMO-HOSP-DL-01",
        "rep_email": "fortis.delhi@demo.bloodlink.ai",
        "rep_name": "Dr. Naresh Trehan",
        "address": "Okhla Road, New Friends Colony",
        "state": "Delhi",
        "district": "New Delhi",
        "city": "New Delhi",
        "lat": 28.5604, "lng": 77.2797,
        "phone": "+91 11 4713 5000",
        "status": "VERIFIED"
    },
    # 8. West Bengal - Kolkata
    {
        "name": "Ruby General Hospital [DEMO]",
        "reference": "DEMO-HOSP-WB-01",
        "rep_email": "ruby.kolkata@demo.bloodlink.ai",
        "rep_name": "Dr. Kamal Dutta",
        "address": "Kasba Golpark, EM Bypass",
        "state": "West Bengal",
        "district": "Kolkata",
        "city": "Kolkata",
        "lat": 22.5135, "lng": 88.4013,
        "phone": "+91 33 3987 1800",
        "status": "VERIFIED"
    },
    # 9. Gujarat - Ahmedabad
    {
        "name": "Zydus Hospital SG Highway [DEMO]",
        "reference": "DEMO-HOSP-GJ-01",
        "rep_email": "zydus.ahmedabad@demo.bloodlink.ai",
        "rep_name": "Dr. Bhavesh Patel",
        "address": "Zydus Hospitals Road, SG Highway, Thaltej",
        "state": "Gujarat",
        "district": "Ahmedabad",
        "city": "Ahmedabad",
        "lat": 23.0560, "lng": 72.5050,
        "phone": "+91 79 6619 0201",
        "status": "VERIFIED"
    },
    # 10. Uttar Pradesh - Lucknow
    {
        "name": "SGPGI Apex Trauma Center [DEMO]",
        "reference": "DEMO-HOSP-UP-01",
        "rep_email": "sgpgi.lucknow@demo.bloodlink.ai",
        "rep_name": "Dr. Alok Verma",
        "address": "Raebareli Road",
        "state": "Uttar Pradesh",
        "district": "Lucknow",
        "city": "Lucknow",
        "lat": 26.7483, "lng": 80.9392,
        "phone": "+91 522 249 4000",
        "status": "VERIFIED"
    },
    # 11. Odisha - Bhubaneswar
    {
        "name": "AIIMS Bhubaneswar Trauma Care [DEMO]",
        "reference": "DEMO-HOSP-OD-01",
        "rep_email": "aiims.bbsr@demo.bloodlink.ai",
        "rep_name": "Dr. Subhasish Mohanty",
        "address": "Sijua, Patrapada",
        "state": "Odisha",
        "district": "Khordha",
        "city": "Bhubaneswar",
        "lat": 20.2312, "lng": 85.7766,
        "phone": "+91 674 247 6789",
        "status": "VERIFIED"
    },
    # 12. Haryana - Gurugram
    {
        "name": "Medanta The Medicity [DEMO]",
        "reference": "DEMO-HOSP-HR-01",
        "rep_email": "medanta.gurugram@demo.bloodlink.ai",
        "rep_name": "Dr. Rajiv Singhal",
        "address": "Sector 38, CH Bakhtawar Singh Road",
        "state": "Haryana",
        "district": "Gurugram",
        "city": "Gurugram",
        "lat": 28.4395, "lng": 77.0427,
        "phone": "+91 124 414 1414",
        "status": "VERIFIED"
    },
    # 13. Assam - Guwahati (PENDING Verification)
    {
        "name": "Guwahati Neurological & Trauma Institute [DEMO]",
        "reference": "DEMO-HOSP-AS-01",
        "rep_email": "gnti.assam@demo.bloodlink.ai",
        "rep_name": "Dr. Nabanita Barua",
        "address": "GS Road, Dispur",
        "state": "Assam",
        "district": "Kamrup Metropolitan",
        "city": "Guwahati",
        "lat": 26.1558, "lng": 91.7761,
        "phone": "+91 361 223 4567",
        "status": "PENDING"
    },
    # 14. Jammu and Kashmir - Srinagar (PENDING Verification)
    {
        "name": "SKIMS Regional Medical Institute [DEMO]",
        "reference": "DEMO-HOSP-JK-01",
        "rep_email": "skims.srinagar@demo.bloodlink.ai",
        "rep_name": "Dr. Tariq Lone",
        "address": "Soura",
        "state": "Jammu and Kashmir",
        "district": "Srinagar",
        "city": "Srinagar",
        "lat": 34.1287, "lng": 74.8016,
        "phone": "+91 194 240 1013",
        "status": "PENDING"
    }
]


# =============================================================================
# DATA DEFINITIONS: PAN-INDIA BLOOD BANKS (~22 Across Multiple States & UTs)
# =============================================================================
BLOOD_BANKS_DATA = [
    # 1. Karnataka - Bengaluru
    {
        "name": "Red Cross Society Central Blood Bank [DEMO]",
        "reference": "DEMO-BB-KA-01",
        "rep_email": "redcross@bloodbank.com",
        "rep_name": "Senior Blood Technologist",
        "address": "No. 26, Red Cross Bhavan, Race Course Road",
        "state": "Karnataka",
        "district": "Bengaluru Urban",
        "city": "Bengaluru",
        "lat": 12.9830, "lng": 77.5802,
        "phone": "+91 80 2226 8435",
        "status": "VERIFIED"
    },
    # 2. Kerala - Kochi / Ernakulam
    {
        "name": "IMA Voluntary Blood Bank Kochi [DEMO]",
        "reference": "DEMO-BB-KL-01",
        "rep_email": "ima.kochi@demo.bloodlink.ai",
        "rep_name": "B. Gopakumar",
        "address": "IMA House, Behind Jawaharlal Nehru Stadium, Kaloor",
        "state": "Kerala",
        "district": "Ernakulam",
        "city": "Kochi",
        "lat": 9.9926, "lng": 76.2991,
        "phone": "+91 484 234 5800",
        "status": "VERIFIED"
    },
    # 3. Kerala - Thiruvananthapuram
    {
        "name": "Sree Chitra Tirunal Blood Center [DEMO]",
        "reference": "DEMO-BB-KL-02",
        "rep_email": "sct.tvm@demo.bloodlink.ai",
        "rep_name": "Dr. Radhika Nair",
        "address": "Medical College PO, Thiruvananthapuram",
        "state": "Kerala",
        "district": "Thiruvananthapuram",
        "city": "Thiruvananthapuram",
        "lat": 8.5241, "lng": 76.9366,
        "phone": "+91 471 252 4444",
        "status": "VERIFIED"
    },
    # Kerala - Thrissur
    {
        "name": "Government Medical College Blood Centre Thrissur [DEMO]",
        "reference": "DEMO-BB-KL-03",
        "rep_email": "gmc.thrissur@demo.bloodlink.ai",
        "rep_name": "Dr. Varghese Mathew",
        "address": "Medical College Road, Mulamkunnathukavu",
        "state": "Kerala",
        "district": "Thrissur",
        "city": "Thrissur",
        "lat": 10.6200, "lng": 76.2050,
        "phone": "+91 487 220 0310",
        "status": "VERIFIED"
    },
    # 4. Maharashtra - Mumbai
    {
        "name": "KEM Hospital Regional Blood Center [DEMO]",
        "reference": "DEMO-BB-MH-01",
        "rep_email": "kem.bb.mumbai@demo.bloodlink.ai",
        "rep_name": "P. K. Sawant",
        "address": "Acharya Donde Marg, Parel",
        "state": "Maharashtra",
        "district": "Mumbai Suburban",
        "city": "Mumbai",
        "lat": 19.0028, "lng": 72.8425,
        "phone": "+91 22 2410 7070",
        "status": "VERIFIED"
    },
    # 5. Maharashtra - Pune
    {
        "name": "Jankalyan Blood Centre Pune [DEMO]",
        "reference": "DEMO-BB-MH-02",
        "rep_email": "jankalyan.pune@demo.bloodlink.ai",
        "rep_name": "Dr. Atul Kulkarni",
        "address": "1003, Shukrawar Peth, Sarasbaug Road",
        "state": "Maharashtra",
        "district": "Pune",
        "city": "Pune",
        "lat": 18.5167, "lng": 73.8562,
        "phone": "+91 20 2444 4444",
        "status": "VERIFIED"
    },
    # 6. Maharashtra - Nagpur
    {
        "name": "Jeevan Jyoti Blood Bank Nagpur [DEMO]",
        "reference": "DEMO-BB-MH-03",
        "rep_email": "jeevan.nagpur@demo.bloodlink.ai",
        "rep_name": "Dr. Sunita Sharma",
        "address": "Dharampeth, Nagpur",
        "state": "Maharashtra",
        "district": "Nagpur",
        "city": "Nagpur",
        "lat": 21.1458, "lng": 79.0882,
        "phone": "+91 712 254 3210",
        "status": "VERIFIED"
    },
    # 7. Tamil Nadu - Chennai
    {
        "name": "Lions Blood Bank & Research Foundation [DEMO]",
        "reference": "DEMO-BB-TN-01",
        "rep_email": "lions.chennai@demo.bloodlink.ai",
        "rep_name": "V. Rangarajan",
        "address": "130, Marshalls Road, Egmore",
        "state": "Tamil Nadu",
        "district": "Chennai",
        "city": "Chennai",
        "lat": 13.0620, "lng": 80.2530,
        "phone": "+91 44 2841 4949",
        "status": "VERIFIED"
    },
    # 8. Tamil Nadu - Coimbatore
    {
        "name": "Ganga Hospital Blood Center [DEMO]",
        "reference": "DEMO-BB-TN-02",
        "rep_email": "ganga.coimbatore@demo.bloodlink.ai",
        "rep_name": "Dr. Rajasekaran",
        "address": "313, Mettupalayam Road",
        "state": "Tamil Nadu",
        "district": "Coimbatore",
        "city": "Coimbatore",
        "lat": 11.0168, "lng": 76.9558,
        "phone": "+91 422 248 5000",
        "status": "VERIFIED"
    },
    # 9. Telangana - Hyderabad
    {
        "name": "Chiranjeevi Eye & Blood Center [DEMO]",
        "reference": "DEMO-BB-TG-01",
        "rep_email": "chiranjeevi.hyd@demo.bloodlink.ai",
        "rep_name": "Dr. K. Srinivas",
        "address": "Road No. 1, Jubilee Hills",
        "state": "Telangana",
        "district": "Hyderabad",
        "city": "Hyderabad",
        "lat": 17.4300, "lng": 78.4480,
        "phone": "+91 40 2355 5000",
        "status": "VERIFIED"
    },
    # 10. Delhi - New Delhi
    {
        "name": "Rotary Blood Bank New Delhi [DEMO]",
        "reference": "DEMO-BB-DL-01",
        "rep_email": "rotary.delhi@demo.bloodlink.ai",
        "rep_name": "Dr. Sudarshan Kumari",
        "address": "56-57, Tughlakabad Institutional Area",
        "state": "Delhi",
        "district": "New Delhi",
        "city": "New Delhi",
        "lat": 28.5670, "lng": 77.2100,
        "phone": "+91 11 2995 5000",
        "status": "VERIFIED"
    },
    # 11. West Bengal - Kolkata
    {
        "name": "Central Blood Bank Kolkata [DEMO]",
        "reference": "DEMO-BB-WB-01",
        "rep_email": "cbb.kolkata@demo.bloodlink.ai",
        "rep_name": "Dr. Prasanta Roy",
        "address": "205, Vivekananda Road, Maniktala",
        "state": "West Bengal",
        "district": "Kolkata",
        "city": "Kolkata",
        "lat": 22.5726, "lng": 88.3639,
        "phone": "+91 33 2350 2419",
        "status": "VERIFIED"
    },
    # 12. Gujarat - Ahmedabad
    {
        "name": "Red Cross Society Ahmedabad Blood Bank [DEMO]",
        "reference": "DEMO-BB-GJ-01",
        "rep_email": "redcross.ahmedabad@demo.bloodlink.ai",
        "rep_name": "Dr. J. C. Shah",
        "address": "Paldi Cross Road, Ellisbridge",
        "state": "Gujarat",
        "district": "Ahmedabad",
        "city": "Ahmedabad",
        "lat": 23.0225, "lng": 72.5714,
        "phone": "+91 79 2657 8888",
        "status": "VERIFIED"
    },
    # 13. Rajasthan - Jaipur
    {
        "name": "Swasthya Kalyan Blood Center Jaipur [DEMO]",
        "reference": "DEMO-BB-RJ-01",
        "rep_email": "swasthya.jaipur@demo.bloodlink.ai",
        "rep_name": "Dr. S. S. Agarwal",
        "address": "10, Janpath, Nirman Nagar",
        "state": "Rajasthan",
        "district": "Jaipur",
        "city": "Jaipur",
        "lat": 26.9124, "lng": 75.7873,
        "phone": "+91 141 281 1111",
        "status": "VERIFIED"
    },
    # 14. Uttar Pradesh - Lucknow
    {
        "name": "Civil Hospital Regional Blood Bank Lucknow [DEMO]",
        "reference": "DEMO-BB-UP-01",
        "rep_email": "civil.lucknow@demo.bloodlink.ai",
        "rep_name": "Dr. R. K. Saxena",
        "address": "Park Road, Hazratganj",
        "state": "Uttar Pradesh",
        "district": "Lucknow",
        "city": "Lucknow",
        "lat": 26.8467, "lng": 80.9462,
        "phone": "+91 522 223 9000",
        "status": "VERIFIED"
    },
    # 15. Bihar - Patna
    {
        "name": "Patna Medical College Blood Bank [DEMO]",
        "reference": "DEMO-BB-BR-01",
        "rep_email": "pmch.patna@demo.bloodlink.ai",
        "rep_name": "Dr. U. P. Sinha",
        "address": "Ashok Rajpath, Patna",
        "state": "Bihar",
        "district": "Patna",
        "city": "Patna",
        "lat": 25.6207, "lng": 85.1666,
        "phone": "+91 612 230 0045",
        "status": "VERIFIED"
    },
    # 16. Odisha - Bhubaneswar
    {
        "name": "Red Cross Blood Center Bhubaneswar [DEMO]",
        "reference": "DEMO-BB-OD-01",
        "rep_email": "redcross.bbsr@demo.bloodlink.ai",
        "rep_name": "Dr. B. K. Jena",
        "address": "Unit-IV, Madhusudan Nagar",
        "state": "Odisha",
        "district": "Khordha",
        "city": "Bhubaneswar",
        "lat": 20.2961, "lng": 85.8245,
        "phone": "+91 674 239 1234",
        "status": "VERIFIED"
    },
    # 17. Punjab - Ludhiana
    {
        "name": "Civil Hospital Blood Center Ludhiana [DEMO]",
        "reference": "DEMO-BB-PB-01",
        "rep_email": "civil.ludhiana@demo.bloodlink.ai",
        "rep_name": "Dr. Manjit Singh",
        "address": "Near Clock Tower",
        "state": "Punjab",
        "district": "Ludhiana",
        "city": "Ludhiana",
        "lat": 30.9010, "lng": 75.8573,
        "phone": "+91 161 240 1200",
        "status": "VERIFIED"
    },
    # 18. Madhya Pradesh - Bhopal
    {
        "name": "Red Cross Blood Bank Bhopal [DEMO]",
        "reference": "DEMO-BB-MP-01",
        "rep_email": "redcross.bhopal@demo.bloodlink.ai",
        "rep_name": "Dr. Rajiv Gupta",
        "address": "Shivaji Nagar",
        "state": "Madhya Pradesh",
        "district": "Bhopal",
        "city": "Bhopal",
        "lat": 23.2599, "lng": 77.4126,
        "phone": "+91 755 255 1200",
        "status": "VERIFIED"
    },
    # 19. Assam - Guwahati
    {
        "name": "Gauhati Medical College Blood Center [DEMO]",
        "reference": "DEMO-BB-AS-01",
        "rep_email": "gmch.guwahati@demo.bloodlink.ai",
        "rep_name": "Dr. Hemanta Kalita",
        "address": "Narakasur Hilltop, Bhangagarh",
        "state": "Assam",
        "district": "Kamrup Metropolitan",
        "city": "Guwahati",
        "lat": 26.1584, "lng": 91.7712,
        "phone": "+91 361 252 8417",
        "status": "VERIFIED"
    },
    # 20. Goa - Panaji
    {
        "name": "Goa Medical College Blood Center [DEMO]",
        "reference": "DEMO-BB-GA-01",
        "rep_email": "gmc.panaji@demo.bloodlink.ai",
        "rep_name": "Dr. Sanjay Fernandes",
        "address": "Bambolim",
        "state": "Goa",
        "district": "North Goa",
        "city": "Panaji",
        "lat": 15.4633, "lng": 73.8540,
        "phone": "+91 832 245 8700",
        "status": "VERIFIED"
    },
    # 21. Uttarakhand - Dehradun
    {
        "name": "Doon Hospital Blood Bank Dehradun [DEMO]",
        "reference": "DEMO-BB-UK-01",
        "rep_email": "doon.dehradun@demo.bloodlink.ai",
        "rep_name": "Dr. Vijay Rawat",
        "address": "Court Road, Dehradun",
        "state": "Uttarakhand",
        "district": "Dehradun",
        "city": "Dehradun",
        "lat": 30.3165, "lng": 78.0322,
        "phone": "+91 135 265 9000",
        "status": "VERIFIED"
    },
    # 22. Puducherry (UT) - Puducherry
    {
        "name": "Puducherry Government General Hospital Blood Bank [DEMO]",
        "reference": "DEMO-BB-PY-01",
        "rep_email": "gh.puducherry@demo.bloodlink.ai",
        "rep_name": "Dr. S. Radhakrishnan",
        "address": "Victor Simonel Street",
        "state": "Puducherry",
        "district": "Puducherry",
        "city": "Puducherry",
        "lat": 11.9416, "lng": 79.8083,
        "phone": "+91 413 233 6050",
        "status": "VERIFIED"
    }
]


# =============================================================================
# DATA DEFINITIONS: PAN-INDIA VOLUNTARY DONORS (~54 Across 36 States & UTs)
# =============================================================================
DONORS_DATA = [
    # Core Demo Users (Preserved identity & credentials)
    ("Arjun Sharma [DEMO]", "arjun@donor.com", "O-", "Karnataka", "Bengaluru Urban", "Bengaluru", 12.9716, 77.5946, 90),
    ("Dr. Priya Patel [DEMO]", "priya@donor.com", "A+", "Karnataka", "Bengaluru Urban", "Bengaluru", 12.9352, 77.6245, 60),
    ("Vikram Singh [DEMO]", "vikram@donor.com", "B+", "Karnataka", "Bengaluru Urban", "Bengaluru", 12.9279, 77.6271, 100),
    ("Sneha Reddy [DEMO]", "sneha@donor.com", "B-", "Karnataka", "Bengaluru Urban", "Bengaluru", 12.9141, 77.6109, 80),
    ("Rahul Verma [DEMO]", "rahul@donor.com", "O+", "Karnataka", "Bengaluru Urban", "Bengaluru", 12.9784, 77.6408, 15),

    # Kerala
    ("Ananya Menon [DEMO]", "ananya.menon@demo.bloodlink.ai", "O+", "Kerala", "Ernakulam", "Kochi", 9.9312, 76.2673, 75),
    ("Kavitha Nair [DEMO]", "kavitha.nair@demo.bloodlink.ai", "A+", "Kerala", "Thiruvananthapuram", "Thiruvananthapuram", 8.5241, 76.9366, 65),
    ("Fahad Rahman [DEMO]", "fahad.rahman@demo.bloodlink.ai", "B+", "Kerala", "Kozhikode", "Kozhikode", 11.2588, 75.7804, 110),

    # Maharashtra
    ("Rohan Deshmukh [DEMO]", "rohan.deshmukh@demo.bloodlink.ai", "O+", "Maharashtra", "Pune", "Pune", 18.5204, 73.8567, 95),
    ("Tanvi Joshi [DEMO]", "tanvi.joshi@demo.bloodlink.ai", "A-", "Maharashtra", "Pune", "Pune", 18.5314, 73.8446, 70),
    ("Amitabh Sawant [DEMO]", "amitabh.sawant@demo.bloodlink.ai", "AB+", "Maharashtra", "Mumbai Suburban", "Mumbai", 19.0760, 72.8777, 85),
    ("Pooja Kadam [DEMO]", "pooja.kadam@demo.bloodlink.ai", "O-", "Maharashtra", "Nagpur", "Nagpur", 21.1458, 79.0882, 120),

    # Tamil Nadu
    ("Karthik Sundaram [DEMO]", "karthik.sundaram@demo.bloodlink.ai", "O+", "Tamil Nadu", "Chennai", "Chennai", 13.0827, 80.2707, 105),
    ("Deepa Subramaniam [DEMO]", "deepa.subramaniam@demo.bloodlink.ai", "A+", "Tamil Nadu", "Chennai", "Chennai", 13.0475, 80.2090, 60),
    ("Senthil Nathan [DEMO]", "senthil.nathan@demo.bloodlink.ai", "B+", "Tamil Nadu", "Coimbatore", "Coimbatore", 11.0168, 76.9558, 80),
    ("Meenakshi Iyer [DEMO]", "meenakshi.iyer@demo.bloodlink.ai", "O-", "Tamil Nadu", "Madurai", "Madurai", 9.9252, 78.1198, 90),

    # Telangana
    ("Siddharth Rao [DEMO]", "siddharth.rao@demo.bloodlink.ai", "O+", "Telangana", "Hyderabad", "Hyderabad", 17.3850, 78.4867, 70),
    ("Navya Teja [DEMO]", "navya.teja@demo.bloodlink.ai", "A+", "Telangana", "Hyderabad", "Hyderabad", 17.4400, 78.3800, 85),
    ("Rajesh Goud [DEMO]", "rajesh.goud@demo.bloodlink.ai", "B+", "Telangana", "Warangal", "Warangal", 17.9689, 79.5941, 100),

    # Andhra Pradesh
    ("Chaitanya Varma [DEMO]", "chaitanya.varma@demo.bloodlink.ai", "O+", "Andhra Pradesh", "Visakhapatnam", "Visakhapatnam", 17.6868, 83.2185, 90),
    ("Bhavani Prasad [DEMO]", "bhavani.prasad@demo.bloodlink.ai", "B-", "Andhra Pradesh", "NTR", "Vijayawada", 16.5062, 80.6480, 75),

    # Delhi
    ("Aditya Malhotra [DEMO]", "aditya.malhotra@demo.bloodlink.ai", "O+", "Delhi", "New Delhi", "New Delhi", 28.6139, 77.2090, 80),
    ("Simran Kaur [DEMO]", "simran.kaur@demo.bloodlink.ai", "A+", "Delhi", "Central Delhi", "New Delhi", 28.6448, 77.2167, 65),

    # West Bengal
    ("Sourav Banerjee [DEMO]", "sourav.banerjee@demo.bloodlink.ai", "O+", "West Bengal", "Kolkata", "Kolkata", 22.5726, 88.3639, 90),
    ("Debolina Mukherjee [DEMO]", "debolina.mukherjee@demo.bloodlink.ai", "B+", "West Bengal", "Kolkata", "Kolkata", 22.5354, 88.3473, 110),

    # Gujarat
    ("Harshil Mehta [DEMO]", "harshil.mehta@demo.bloodlink.ai", "O+", "Gujarat", "Ahmedabad", "Ahmedabad", 23.0225, 72.5714, 85),
    ("Kinjal Shah [DEMO]", "kinjal.shah@demo.bloodlink.ai", "A-", "Gujarat", "Surat", "Surat", 21.1702, 72.8311, 75),

    # Rajasthan
    ("Manish Sharma [DEMO]", "manish.sharma@demo.bloodlink.ai", "O+", "Rajasthan", "Jaipur", "Jaipur", 26.9124, 75.7873, 90),
    ("Ritu Rathore [DEMO]", "ritu.rathore@demo.bloodlink.ai", "B+", "Rajasthan", "Jodhpur", "Jodhpur", 26.2389, 73.0243, 60),

    # Uttar Pradesh
    ("Gaurav Shukla [DEMO]", "gaurav.shukla@demo.bloodlink.ai", "O+", "Uttar Pradesh", "Lucknow", "Lucknow", 26.8467, 80.9462, 85),
    ("Shweta Mishra [DEMO]", "shweta.mishra@demo.bloodlink.ai", "A+", "Uttar Pradesh", "Kanpur Nagar", "Kanpur", 26.4499, 80.3319, 70),
    ("Vikas Pandey [DEMO]", "vikas.pandey@demo.bloodlink.ai", "AB+", "Uttar Pradesh", "Varanasi", "Varanasi", 25.3176, 82.9739, 95),

    # Bihar
    ("Prashant Kumar [DEMO]", "prashant.kumar@demo.bloodlink.ai", "O+", "Bihar", "Patna", "Patna", 25.5941, 85.1376, 80),
    ("Anjali Sinha [DEMO]", "anjali.sinha@demo.bloodlink.ai", "B+", "Bihar", "Gaya", "Gaya", 24.7914, 85.0002, 100),

    # Odisha
    ("Biswajit Das [DEMO]", "biswajit.das@demo.bloodlink.ai", "O+", "Odisha", "Khordha", "Bhubaneswar", 20.2961, 85.8245, 90),
    ("Swati Pattnaik [DEMO]", "swati.pattnaik@demo.bloodlink.ai", "A+", "Odisha", "Cuttack", "Cuttack", 20.4625, 85.8828, 75),

    # Punjab & Haryana
    ("Gurpreet Singh [DEMO]", "gurpreet.singh@demo.bloodlink.ai", "B+", "Punjab", "Ludhiana", "Ludhiana", 30.9010, 75.8573, 85),
    ("Amanpreet Kaur [DEMO]", "amanpreet.kaur@demo.bloodlink.ai", "O+", "Punjab", "Amritsar", "Amritsar", 31.6340, 74.8723, 110),
    ("Yashvardhan Hooda [DEMO]", "yash.hooda@demo.bloodlink.ai", "A+", "Haryana", "Gurugram", "Gurugram", 28.4595, 77.0266, 65),

    # Madhya Pradesh
    ("Abhishek Chouhan [DEMO]", "abhishek.chouhan@demo.bloodlink.ai", "O+", "Madhya Pradesh", "Bhopal", "Bhopal", 23.2599, 77.4126, 95),
    ("Pallavi Tiwari [DEMO]", "pallavi.tiwari@demo.bloodlink.ai", "B+", "Madhya Pradesh", "Indore", "Indore", 22.7196, 75.8577, 80),

    # Assam & Northeast States
    ("Bhaskar Saikia [DEMO]", "bhaskar.saikia@demo.bloodlink.ai", "O+", "Assam", "Kamrup Metropolitan", "Guwahati", 26.1445, 91.7362, 90),
    ("Jumoni Borah [DEMO]", "jumoni.borah@demo.bloodlink.ai", "A+", "Assam", "Dibrugarh", "Dibrugarh", 27.4728, 94.9120, 70),
    ("Taba Taku [DEMO]", "taba.taku@demo.bloodlink.ai", "B+", "Arunachal Pradesh", "Itanagar Capital Complex", "Itanagar", 27.0844, 93.6053, 85),
    ("Thoiba Singh [DEMO]", "thoiba.singh@demo.bloodlink.ai", "O+", "Manipur", "Imphal West", "Imphal", 24.8170, 93.9368, 75),
    ("Wandashisha Marbaniang [DEMO]", "wanda.marbaniang@demo.bloodlink.ai", "AB+", "Meghalaya", "East Khasi Hills", "Shillong", 25.5788, 91.8933, 90),
    ("Lalremruata Colney [DEMO]", "lalremruata.colney@demo.bloodlink.ai", "O+", "Mizoram", "Aizawl", "Aizawl", 23.7271, 92.7176, 80),
    ("Temjen Jamir [DEMO]", "temjen.jamir@demo.bloodlink.ai", "B+", "Nagaland", "Kohima", "Kohima", 25.6751, 94.1086, 95),
    ("Sonam Bhutia [DEMO]", "sonam.bhutia@demo.bloodlink.ai", "A+", "Sikkim", "Gangtok", "Gangtok", 27.3389, 88.6065, 85),
    ("Debasish Debbarma [DEMO]", "debasish.deb@demo.bloodlink.ai", "O-", "Tripura", "West Tripura", "Agartala", 23.8315, 91.2868, 100),

    # Additional States & Union Territories
    ("Clinton Coutinho [DEMO]", "clinton.coutinho@demo.bloodlink.ai", "O+", "Goa", "North Goa", "Panaji", 15.4909, 73.8278, 80),
    ("Alok Rawat [DEMO]", "alok.rawat@demo.bloodlink.ai", "B+", "Uttarakhand", "Dehradun", "Dehradun", 30.3165, 78.0322, 90),
    ("Sunil Thakur [DEMO]", "sunil.thakur@demo.bloodlink.ai", "A+", "Himachal Pradesh", "Shimla", "Shimla", 31.1048, 77.1734, 75),
    ("Brijesh Baghel [DEMO]", "brijesh.baghel@demo.bloodlink.ai", "O+", "Chhattisgarh", "Raipur", "Raipur", 21.2514, 81.6296, 85),
    ("Prashant Soren [DEMO]", "prashant.soren@demo.bloodlink.ai", "B+", "Jharkhand", "Ranchi", "Ranchi", 23.3441, 85.3096, 95),
    ("Junaid Dar [DEMO]", "junaid.dar@demo.bloodlink.ai", "O-", "Jammu and Kashmir", "Srinagar", "Srinagar", 34.0837, 74.7973, 90),
    ("Stanzin Norbu [DEMO]", "stanzin.norbu@demo.bloodlink.ai", "A+", "Ladakh", "Leh", "Leh", 34.1526, 77.5771, 100),
    ("Selvamani K [DEMO]", "selvamani.k@demo.bloodlink.ai", "O+", "Puducherry", "Puducherry", "Puducherry", 11.9416, 79.8083, 75),
    ("Manpreet Chawla [DEMO]", "manpreet.chawla@demo.bloodlink.ai", "AB+", "Chandigarh", "Chandigarh", "Chandigarh", 30.7333, 76.7794, 85),
    ("Ronald Dsouza [DEMO]", "ronald.dsouza@demo.bloodlink.ai", "B+", "Andaman and Nicobar Islands", "South Andaman", "Port Blair", 11.6234, 92.7265, 90),
    ("Mohammed Koya [DEMO]", "mohammed.koya@demo.bloodlink.ai", "O+", "Lakshadweep", "Lakshadweep", "Kavaratti", 10.5669, 72.6420, 80),
    ("Dipen Patel [DEMO]", "dipen.patel@demo.bloodlink.ai", "A+", "Dadra and Nagar Haveli and Daman and Diu", "Daman", "Daman", 20.3974, 72.8328, 85),
]


# =============================================================================
# DATA DEFINITIONS: PAN-INDIA REWARDS COUPONS (Nationwide Healthcare Partners)
# =============================================================================
COUPONS_DATA = [
    {
        "partner": "Apollo Diagnostics India",
        "title": "Comprehensive Full Body Health Screening Voucher [DEMO]",
        "description": "60+ parameters comprehensive diagnostic screening voucher redeemable across all Apollo diagnostic centers in India.",
        "points": 300,
        "category": "Healthcare",
        "icon": "bi-heart-pulse"
    },
    {
        "partner": "Dr. Lal PathLabs",
        "title": "Complete Blood Count (CBC) & Ferritin Profile [DEMO]",
        "description": "Complete blood hemogram and ferritin diagnostic screening voucher at partner laboratories nationwide.",
        "points": 150,
        "category": "Diagnostics",
        "icon": "bi-flask"
    },
    {
        "partner": "Tata 1mg Health Network",
        "title": "Pharmacy & Vital Vitamins Voucher (Rs. 500 Value) [DEMO]",
        "description": "Applicable across all dietary supplements, iron tonics, and health goods on the Tata 1mg nationwide platform.",
        "points": 100,
        "category": "Pharmacy",
        "icon": "bi-capsule"
    },
    {
        "partner": "PharmEasy India",
        "title": "Healthcare Wellness Consultation & Diagnostics Credit [DEMO]",
        "description": "Redeemable for physician tele-consultation and preventive health checkups across participating clinics in India.",
        "points": 200,
        "category": "Healthcare",
        "icon": "bi-shield-plus"
    },
    {
        "partner": "Cult.fit Wellness",
        "title": "30-Day Fitness & Yoga Digital Pass [DEMO]",
        "description": "Complimentary 30-day health fitness pass dedicated to voluntary lifesaver donors.",
        "points": 250,
        "category": "Fitness",
        "icon": "bi-activity"
    }
]


# =============================================================================
# SEED LOGIC: IDEMPOTENT GENERATOR
# =============================================================================
def seed_india_wide_demo_dataset(app_instance=None):
    """
    Safely seed or extend the database with the pan-India synthetic demonstration dataset.
    Idempotent: updates existing demo records if present, inserts new records without duplicates.
    Preserves all existing real records and pre-configured test users.
    """
    summary = {
        "hospitals_created": 0,
        "hospitals_updated": 0,
        "banks_created": 0,
        "banks_updated": 0,
        "donors_created": 0,
        "donors_updated": 0,
        "inventory_records": 0,
        "requests_created": 0,
        "coupons_created": 0,
        "states_represented": set()
    }

    print("[*] Beginning India-Wide Synthetic Demonstration Dataset seeding...")

    # 1. Administrator Account (Idempotent)
    admin = User.query.filter_by(email="admin@bloodlink.ai").first()
    if not admin:
        admin = User(
            name="Platform Administrator",
            email="admin@bloodlink.ai",
            role="ADMIN",
            is_active=True,
            email_verified=True,
            is_demo=True
        )
        admin.set_password("admin123")
        db.session.add(admin)
        db.session.flush()

    # 2. Seed / Update Hospital Organizations
    seeded_hospitals = []
    for h_data in HOSPITALS_DATA:
        # Validate state and district
        if not is_valid_district(h_data["state"], h_data["district"]):
            print(f"[!] Warning: Skipping invalid state-district in seed data: {h_data['state']} -> {h_data['district']}")
            continue

        summary["states_represented"].add(h_data["state"])

        org = Organization.query.filter_by(registration_reference=h_data["reference"]).first()
        if not org:
            org = Organization(
                organization_name=h_data["name"],
                organization_type="HOSPITAL",
                registration_reference=h_data["reference"],
                address=h_data["address"],
                country="India",
                state=h_data["state"],
                district=h_data["district"],
                city=h_data["city"],
                latitude=h_data["lat"],
                longitude=h_data["lng"],
                contact_phone=h_data["phone"],
                contact_email=h_data["rep_email"],
                verification_status=h_data["status"],
                is_demo=True
            )
            db.session.add(org)
            db.session.flush()
            summary["hospitals_created"] += 1
        else:
            org.organization_name = h_data["name"]
            org.address = h_data["address"]
            org.state = h_data["state"]
            org.district = h_data["district"]
            org.city = h_data["city"]
            org.latitude = h_data["lat"]
            org.longitude = h_data["lng"]
            org.verification_status = h_data["status"]
            org.is_demo = True
            summary["hospitals_updated"] += 1

        # Representative user
        rep_user = User.query.filter_by(email=h_data["rep_email"]).first()
        if not rep_user:
            rep_user = User(
                name=h_data["rep_name"],
                email=h_data["rep_email"],
                role="HOSPITAL",
                is_active=True,
                email_verified=True,
                is_demo=True
            )
            rep_user.set_password("hospital123")
            db.session.add(rep_user)
            db.session.flush()
            db.session.add(OrganizationMembership(organization_id=org.id, user_id=rep_user.id, membership_role="ADMIN"))

        seeded_hospitals.append((org, rep_user))

    # 3. Seed / Update Blood Bank Organizations
    seeded_banks = []
    for b_data in BLOOD_BANKS_DATA:
        if not is_valid_district(b_data["state"], b_data["district"]):
            print(f"[!] Warning: Skipping invalid state-district in seed data: {b_data['state']} -> {b_data['district']}")
            continue

        summary["states_represented"].add(b_data["state"])

        bank = Organization.query.filter_by(registration_reference=b_data["reference"]).first()
        if not bank:
            bank = Organization(
                organization_name=b_data["name"],
                organization_type="BLOOD_BANK",
                registration_reference=b_data["reference"],
                address=b_data["address"],
                country="India",
                state=b_data["state"],
                district=b_data["district"],
                city=b_data["city"],
                latitude=b_data["lat"],
                longitude=b_data["lng"],
                contact_phone=b_data["phone"],
                contact_email=b_data["rep_email"],
                verification_status=b_data["status"],
                is_demo=True
            )
            db.session.add(bank)
            db.session.flush()
            summary["banks_created"] += 1
        else:
            bank.organization_name = b_data["name"]
            bank.address = b_data["address"]
            bank.state = b_data["state"]
            bank.district = b_data["district"]
            bank.city = b_data["city"]
            bank.latitude = b_data["lat"]
            bank.longitude = b_data["lng"]
            bank.verification_status = b_data["status"]
            bank.is_demo = True
            summary["banks_updated"] += 1

        # Representative user
        rep_user = User.query.filter_by(email=b_data["rep_email"]).first()
        if not rep_user:
            rep_user = User(
                name=b_data["rep_name"],
                email=b_data["rep_email"],
                role="BLOOD_BANK",
                is_active=True,
                email_verified=True,
                is_demo=True
            )
            rep_user.set_password("bank123")
            db.session.add(rep_user)
            db.session.flush()
            db.session.add(OrganizationMembership(organization_id=bank.id, user_id=rep_user.id, membership_role="ADMIN"))

        seeded_banks.append((bank, rep_user))

    # 4. Seed / Update Blood Inventories Across Blood Banks (~80+ Inventory Records)
    blood_groups = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
    components = ['Whole Blood', 'Red Blood Cells', 'Platelets', 'Plasma']

    # Distribute stock patterns across the verified blood banks
    for idx, (bank, rep_user) in enumerate(seeded_banks):
        if bank.verification_status != 'VERIFIED':
            continue

        # Choose 3-4 groups per bank to simulate diverse real-world inventories
        if bank.district == 'Thrissur':
            assigned_groups = ['O+', 'A+', 'B+', 'O-', 'AB+']
        else:
            assigned_groups = blood_groups[idx % len(blood_groups): (idx % len(blood_groups)) + 4]
            if len(assigned_groups) < 4:
                assigned_groups += blood_groups[:4 - len(assigned_groups)]

        for bg in assigned_groups:
            # Whole Blood or RBC
            comp = 'Whole Blood' if (idx + hash(bg)) % 2 == 0 else 'Red Blood Cells'
            # Determine units with realistic deficit simulation (O- and AB- are scarcer)
            if bg in ['O-', 'AB-']:
                units = 1 if idx % 2 == 0 else 2
            elif bg in ['B-', 'A-']:
                units = 3 if idx % 2 == 0 else 5
            else:
                units = 10 + (idx * 2) % 15

            inv = BloodInventory.query.filter_by(
                blood_bank_id=bank.id,
                blood_group=bg,
                component_type=comp
            ).first()

            if not inv:
                inv = BloodInventory(
                    blood_bank_id=bank.id,
                    blood_group=bg,
                    component_type=comp,
                    available_units=units,
                    is_demo=True,
                    last_updated_at=datetime.now(timezone.utc) - timedelta(hours=(idx * 3) % 48),
                    updated_by=rep_user.id
                )
                db.session.add(inv)
                summary["inventory_records"] += 1
            else:
                inv.available_units = units
                inv.is_demo = True
                inv.last_updated_at = datetime.now(timezone.utc)

    # 5. Seed / Update Voluntary Donors (~54 Donors Across 36 States & UTs)
    seeded_donors = []
    for d_name, d_email, bg, st, dist, city, lat, lng, days_ago in DONORS_DATA:
        if not is_valid_district(st, dist):
            print(f"[!] Warning: Skipping invalid state-district in donor seed: {st} -> {dist}")
            continue

        summary["states_represented"].add(st)

        d_user = User.query.filter_by(email=d_email).first()
        if not d_user:
            d_user = User(
                name=d_name,
                email=d_email,
                role="DONOR",
                is_active=True,
                email_verified=True,
                is_demo=True
            )
            d_user.set_password("donor123")
            db.session.add(d_user)
            db.session.flush()

            profile = DonorProfile(
                user_id=d_user.id,
                declared_blood_group=bg,
                country="India",
                state=st,
                district=dist,
                city=city,
                latitude=lat,
                longitude=lng,
                phone="+91 98765 00000",
                availability_status=True,
                notification_consent=True,
                is_demo=True,
                last_donation_date=date.today() - timedelta(days=days_ago)
            )
            db.session.add(profile)
            summary["donors_created"] += 1
        else:
            d_user.name = d_name
            d_user.is_demo = True
            if d_user.donor_profile:
                d_user.donor_profile.state = st
                d_user.donor_profile.district = dist
                d_user.donor_profile.city = city
                d_user.donor_profile.latitude = lat
                d_user.donor_profile.longitude = lng
                d_user.donor_profile.is_demo = True
            summary["donors_updated"] += 1

        seeded_donors.append(d_user)

    # 6. Seed / Update Partner Marketplace Coupons
    for c_data in COUPONS_DATA:
        coupon = Coupon.query.filter_by(title=c_data["title"]).first()
        if not coupon:
            coupon = Coupon(
                partner_name=c_data["partner"],
                title=c_data["title"],
                description=c_data["description"],
                points_required=c_data["points"],
                category=c_data["category"],
                icon=c_data["icon"],
                coupon_status="ACTIVE",
                is_demo=True,
                created_at=datetime.now(timezone.utc) - timedelta(days=30)
            )
            db.session.add(coupon)
            summary["coupons_created"] += 1

    # 7. Seed Past Verified Donations & Ledger for Core Donors
    if seeded_donors and seeded_banks:
        arjun_user = User.query.filter_by(email="arjun@donor.com").first()
        first_bank = seeded_banks[0][0]
        first_bank_user = seeded_banks[0][1]

        if arjun_user and first_bank:
            existing_don = Donation.query.filter_by(donor_id=arjun_user.id, blood_bank_id=first_bank.id).first()
            if not existing_don:
                don = Donation(
                    donor_id=arjun_user.id,
                    blood_bank_id=first_bank.id,
                    units=1,
                    component_type="Whole Blood",
                    donation_date=datetime.now(timezone.utc) - timedelta(days=90),
                    verification_status="VERIFIED",
                    verified_by=first_bank_user.id,
                    verified_at=datetime.now(timezone.utc) - timedelta(days=90),
                    is_demo=True
                )
                db.session.add(don)
                db.session.flush()

                tx = RewardTransaction(
                    donor_id=arjun_user.id,
                    donation_id=don.id,
                    points=250,
                    transaction_type="CREDIT",
                    description="Verified voluntary donation + regional emergency bonus [DEMO]",
                    created_at=datetime.now(timezone.utc) - timedelta(days=90)
                )
                db.session.add(tx)

    # 8. Seed Clinical Emergency Requests Across Various States (~20 Requests)
    clinical_requests_data = [
        # Apollo Bengaluru (Karnataka)
        ("REQ-DEMO-KA-01", "DEMO-HOSP-KA-01", "O-", "Whole Blood", 2, "CRITICAL", 3, "Karnataka", "Bengaluru Urban", "Bengaluru", 12.8913, 77.5973, "Severe obstetric trauma in ICU OT-2"),
        # Amrita Kochi (Kerala)
        ("REQ-DEMO-KL-01", "DEMO-HOSP-KL-01", "A+", "Red Blood Cells", 3, "HIGH", 6, "Kerala", "Ernakulam", "Kochi", 9.9816, 76.2999, "Emergency cardiovascular bypass procedure"),
        ("REQ-DEMO-KL-02", "DEMO-HOSP-KL-01", "O+", "Platelets", 4, "MEDIUM", 18, "Kerala", "Ernakulam", "Kochi", 9.9816, 76.2999, "Dengue hemorrhagic thrombocytopenia support"),
        # KEM Mumbai (Maharashtra)
        ("REQ-DEMO-MH-01", "DEMO-HOSP-MH-01", "AB-", "Whole Blood", 1, "CRITICAL", 2, "Maharashtra", "Mumbai Suburban", "Mumbai", 19.0024, 72.8427, "Ultra rare AB- pediatric trauma resuscitation"),
        # Sancheti Pune (Maharashtra)
        ("REQ-DEMO-MH-02", "DEMO-HOSP-MH-02", "B+", "Red Blood Cells", 2, "HIGH", 8, "Maharashtra", "Pune", "Pune", 18.5293, 73.8504, "Major bilateral hip replacement arthroplasty"),
        ("REQ-DEMO-MH-03", "DEMO-HOSP-MH-02", "O+", "Whole Blood", 2, "MEDIUM", 24, "Maharashtra", "Pune", "Pune", 18.5293, 73.8504, "Polytrauma spine surgical stabilization"),
        # Apollo Chennai (Tamil Nadu)
        ("REQ-DEMO-TN-01", "DEMO-HOSP-TN-01", "O-", "Red Blood Cells", 2, "CRITICAL", 4, "Tamil Nadu", "Chennai", "Chennai", 13.0617, 80.2520, "Emergency neonatal exchange transfusion"),
        ("REQ-DEMO-TN-02", "DEMO-HOSP-TN-01", "A-", "Platelets", 3, "HIGH", 7, "Tamil Nadu", "Chennai", "Chennai", 13.0617, 80.2520, "Oncology leukemia induction therapy support"),
        # Apollo Jubilee Hills (Telangana)
        ("REQ-DEMO-TG-01", "DEMO-HOSP-TG-01", "B-", "Whole Blood", 2, "HIGH", 5, "Telangana", "Hyderabad", "Hyderabad", 17.4198, 78.4116, "Liver transplant surgical blood demand"),
        # Fortis Escorts (Delhi)
        ("REQ-DEMO-DL-01", "DEMO-HOSP-DL-01", "O+", "Red Blood Cells", 4, "CRITICAL", 3, "Delhi", "New Delhi", "New Delhi", 28.5604, 77.2797, "Aortic aneurysm rupture repair"),
        # Ruby General (West Bengal)
        ("REQ-DEMO-WB-01", "DEMO-HOSP-WB-01", "A+", "Whole Blood", 2, "HIGH", 6, "West Bengal", "Kolkata", "Kolkata", 22.5135, 88.4013, "Gastric perforation trauma surgery"),
        # Zydus Ahmedabad (Gujarat)
        ("REQ-DEMO-GJ-01", "DEMO-HOSP-GJ-01", "B+", "Platelets", 3, "MEDIUM", 16, "Gujarat", "Ahmedabad", "Ahmedabad", 23.0560, 72.5050, "Aplastic anemia maintenance transfusion"),
        # SGPGI Lucknow (Uttar Pradesh)
        ("REQ-DEMO-UP-01", "DEMO-HOSP-UP-01", "O-", "Whole Blood", 3, "CRITICAL", 2, "Uttar Pradesh", "Lucknow", "Lucknow", 26.7483, 80.9392, "High-velocity highway collision trauma OT"),
        # AIIMS Bhubaneswar (Odisha)
        ("REQ-DEMO-OD-01", "DEMO-HOSP-OD-01", "AB+", "Plasma", 2, "MEDIUM", 20, "Odisha", "Khordha", "Bhubaneswar", 20.2312, 85.7766, "Coagulopathy fresh frozen plasma therapy"),
        # Medanta Gurugram (Haryana)
        ("REQ-DEMO-HR-01", "DEMO-HOSP-HR-01", "A+", "Red Blood Cells", 2, "HIGH", 5, "Haryana", "Gurugram", "Gurugram", 28.4395, 77.0427, "Emergency coronary artery bypass grafting"),
        # Guwahati Institute (Assam) - PENDING verification status
        ("REQ-DEMO-AS-01", "DEMO-HOSP-AS-01", "O+", "Whole Blood", 2, "HIGH", 12, "Assam", "Kamrup Metropolitan", "Guwahati", 26.1558, 91.7761, "Neurosurgical craniotomy procedure")
    ]

    for ref, hosp_ref, bg, comp, units, urgency, deadline_hrs, st, dist, city, lat, lng, notes in clinical_requests_data:
        hosp = Organization.query.filter_by(registration_reference=hosp_ref).first()
        if not hosp:
            continue

        req = BloodRequest.query.filter_by(request_reference=ref).first()
        if not req:
            req = BloodRequest(
                request_reference=ref,
                requesting_organization_id=hosp.id,
                blood_group=bg,
                component_type=comp,
                units_required=units,
                location=f"{hosp.organization_name}, {city}",
                country="India",
                state=st,
                district=dist,
                city=city,
                latitude=lat,
                longitude=lng,
                urgency_level=urgency,
                clinical_deadline=datetime.now(timezone.utc) + timedelta(hours=deadline_hrs),
                verification_status="VERIFIED" if hosp.is_verified else "PENDING",
                request_status="MATCHING" if hosp.is_verified else "SUBMITTED",
                additional_notes=notes,
                contact_phone=hosp.contact_phone,
                is_demo=True
            )
            db.session.add(req)
            db.session.flush()
            update_request_priority(req)

            # Trigger smart donor matching for verified requests
            if req.verification_status == "VERIFIED":
                run_donor_matching(req, notify_donors=False)

            summary["requests_created"] += 1

    # 9. Audit Log
    AuditLog.log(
        action="SEED_INDIA_WIDE_DEMO_DATA",
        entity_type="System",
        details=f"Seeded pan-India demo dataset across {len(summary['states_represented'])} states/UTs.",
        actor_id=admin.id
    )

    db.session.commit()
    print(f"[+] Pan-India demo dataset successfully seeded across {len(summary['states_represented'])} Indian States and UTs!")
    return summary


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        res = seed_india_wide_demo_dataset()
        print(f"Summary: {res}")
