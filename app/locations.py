"""
Official Indian Administrative Location System.
Covers all 28 States and 8 Union Territories with official district listings.
"""

# Categorization of States and Union Territories
INDIAN_STATES = [
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal"
]

UNION_TERRITORIES = [
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry"
]

# Complete district registry mapped to each State / Union Territory
INDIA_DISTRICTS = {
    # 28 States
    "Andhra Pradesh": [
        "Alluri Sitharama Raju", "Anakapalli", "Ananthapuramu", "Annamayya", "Bapatla",
        "Chittoor", "East Godavari", "Eluru", "Guntur", "Kakinada", "Konaseema", "Krishna",
        "Kurnool", "Nandyal", "NTR", "Palnadu", "Parvathipuram Manyam", "Prakasam",
        "Sri Potti Sriramulu Nellore", "Sri Sathya Sai", "Srikakulam", "Tirupati",
        "Visakhapatnam", "Vizianagaram", "West Godavari", "YSR Kadapa"
    ],
    "Arunachal Pradesh": [
        "Anjaw", "Changlang", "Dibang Valley", "East Kameng", "East Siang", "Itanagar Capital Complex",
        "Kamle", "Kra Daadi", "Kurung Kumey", "Lepa Rada", "Lohit", "Longding",
        "Lower Dibang Valley", "Lower Siang", "Lower Subansiri", "Namsai", "Pakke Kessang",
        "Papum Pare", "Shi Yomi", "Siang", "Tawang", "Tirap", "Upper Siang", "Upper Subansiri",
        "West Kameng", "West Siang"
    ],
    "Assam": [
        "Bajali", "Baksa", "Barpeta", "Biswanath", "Bongaigaon", "Cachar", "Charaideo",
        "Chirang", "Darrang", "Dhemaji", "Dhubri", "Dibrugarh", "Dima Hasao", "Goalpara",
        "Golaghat", "Hailakandi", "Hojai", "Jorhat", "Kamrup", "Kamrup Metropolitan",
        "Karbi Anglong", "Karimganj", "Kokrajhar", "Lakhimpur", "Majuli", "Morigaon",
        "Nagaon", "Nalbari", "Sivasagar", "Sonitpur", "South Salmara-Mankachar",
        "Tamulpur", "Tinsukia", "Udalguri", "West Karbi Anglong"
    ],
    "Bihar": [
        "Araria", "Arwal", "Aurangabad", "Banka", "Begusarai", "Bhagalpur", "Bhojpur",
        "Buxar", "Darbhanga", "East Champaran", "Gaya", "Gopalganj", "Jamui", "Jehanabad",
        "Kaimur", "Katihar", "Khagaria", "Kishanganj", "Lakhisarai", "Madhepura",
        "Madhubani", "Munger", "Muzaffarpur", "Nalanda", "Nawada", "Patna", "Purnia",
        "Rohtas", "Saharsa", "Samastipur", "Saran", "Sheikhpura", "Sheohar", "Sitamarhi",
        "Siwan", "Supaul", "Vaishali", "West Champaran"
    ],
    "Chhattisgarh": [
        "Balod", "Baloda Bazar", "Balrampur", "Bastar", "Bemetara", "Bijapur", "Bilaspur",
        "Dantewada", "Dhamtari", "Durg", "Gariaband", "Gaurela Pendra Marwahi", "Janjgir Champa",
        "Jashpur", "Kabirdham", "Kanker", "Khairagarh", "Kondagaon", "Korba", "Koriya",
        "Mahasamund", "Manendragarh", "Mohla Manpur", "Mungeli", "Narayanpur", "Raigarh",
        "Raipur", "Rajnandgaon", "Sakti", "Sarangarh", "Sukma", "Surajpur", "Surguja"
    ],
    "Goa": [
        "North Goa", "South Goa"
    ],
    "Gujarat": [
        "Ahmedabad", "Amreli", "Anand", "Aravalli", "Banaskantha", "Bharuch", "Bhavnagar",
        "Botad", "Chhota Udaipur", "Dahod", "Dang", "Devbhoomi Dwarka", "Gandhinagar",
        "Gir Somnath", "Jamnagar", "Junagadh", "Kheda", "Kutch", "Mahisagar", "Mehsana",
        "Morbi", "Narmada", "Navsari", "Panchmahal", "Patan", "Porbandar", "Rajkot",
        "Sabarkantha", "Surat", "Surendranagar", "Tapi", "Vadodara", "Valsad"
    ],
    "Haryana": [
        "Ambala", "Bhiwani", "Charkhi Dadri", "Faridabad", "Fatehabad", "Gurugram", "Hisar",
        "Jhajjar", "Jind", "Kaithal", "Karnal", "Kurukshetra", "Mahendragarh", "Nuh",
        "Palwal", "Panchkula", "Panipat", "Rewari", "Rohtak", "Sirsa", "Sonipat", "Yamunanagar"
    ],
    "Himachal Pradesh": [
        "Bilaspur", "Chamba", "Hamirpur", "Kangra", "Kinnaur", "Kullu", "Lahaul and Spiti",
        "Mandi", "Shimla", "Sirmaur", "Solan", "Una"
    ],
    "Jharkhand": [
        "Bokaro", "Chatra", "Deoghar", "Dhanbad", "Dumka", "East Singhbhum", "Garhwa",
        "Giridih", "Godda", "Gumla", "Hazaribagh", "Jamtara", "Khunti", "Koderma",
        "Latehar", "Lohardaga", "Pakur", "Palamu", "Ramgarh", "Ranchi", "Sahibganj",
        "Seraikela Kharsawan", "Simdega", "West Singhbhum"
    ],
    "Karnataka": [
        "Bagalkot", "Ballari", "Belagavi", "Bengaluru Rural", "Bengaluru Urban", "Bidar",
        "Chamarajanagar", "Chikkaballapura", "Chikkamagaluru", "Chitradurga", "Dakshina Kannada",
        "Davanagere", "Dharwad", "Gadag", "Hassan", "Haveri", "Kalaburagi", "Kodagu",
        "Kolar", "Koppal", "Mandya", "Mysuru", "Raichur", "Ramanagara", "Shivamogga",
        "Tumakuru", "Udupi", "Uttara Kannada", "Vijayanagara", "Vijayapura", "Yadgir"
    ],
    "Kerala": [
        "Alappuzha", "Ernakulam", "Idukki", "Kannur", "Kasaragod", "Kollam", "Kottayam",
        "Kozhikode", "Malappuram", "Palakkad", "Pathanamthitta", "Thiruvananthapuram",
        "Thrissur", "Wayanad"
    ],
    "Madhya Pradesh": [
        "Agar Malwa", "Alirajpur", "Anuppur", "Ashoknagar", "Balaghat", "Barwani", "Betul",
        "Bhind", "Bhopal", "Burhanpur", "Chhatarpur", "Chhindwara", "Damoh", "Datia",
        "Dewas", "Dhar", "Dindori", "Guna", "Gwalior", "Harda", "Hoshangabad", "Indore",
        "Jabalpur", "Jhabua", "Katni", "Khandwa", "Khargone", "Maihar", "Mandla",
        "Mandsaur", "Mauganj", "Morena", "Narsinghpur", "Neemuch", "Niwari", "Pandhurna",
        "Panna", "Raisen", "Rajgarh", "Ratlam", "Rewa", "Sagar", "Satna", "Sehore",
        "Seoni", "Shahdol", "Shajapur", "Sheopur", "Shivpuri", "Sidhi", "Singrauli",
        "Tikamgarh", "Ujjain", "Umaria", "Vidisha"
    ],
    "Maharashtra": [
        "Ahmednagar", "Akola", "Amravati", "Beed", "Bhandara", "Buldhana", "Chandrapur",
        "Chhatrapati Sambhajinagar", "Dharashiv", "Dhule", "Gadchiroli", "Gondia", "Hingoli",
        "Jalgaon", "Jalna", "Kolhapur", "Latur", "Mumbai City", "Mumbai Suburban", "Nagpur",
        "Nanded", "Nandurbar", "Nashik", "Palghar", "Parbhani", "Pune", "Raigad", "Ratnagiri",
        "Sangli", "Satara", "Sindhudurg", "Solapur", "Thane", "Wardha", "Washim", "Yavatmal"
    ],
    "Manipur": [
        "Bishnupur", "Chandel", "Churachandpur", "Imphal East", "Imphal West", "Jiribam",
        "Kakching", "Kamjong", "Kangpokpi", "Noney", "Pherzawl", "Senapati", "Tamenglong",
        "Tengnoupal", "Thoubal", "Ukhrul"
    ],
    "Meghalaya": [
        "East Garo Hills", "East Jaintia Hills", "East Khasi Hills", "Eastern West Khasi Hills",
        "North Garo Hills", "Ri Bhoi", "South Garo Hills", "South West Garo Hills",
        "South West Khasi Hills", "West Garo Hills", "West Jaintia Hills", "West Khasi Hills"
    ],
    "Mizoram": [
        "Aizawl", "Champhai", "Hnahthial", "Khawzawl", "Kolasib", "Lawngtlai", "Lunglei",
        "Mamit", "Saitual", "Serchhip", "Siaha"
    ],
    "Nagaland": [
        "Chumoukedima", "Dimapur", "Kiphire", "Kohima", "Longleng", "Mokokchung", "Mon",
        "Niuland", "Noklak", "Peren", "Phek", "Shamator", "Tseminyu", "Tuensang", "Wokha", "Zunheboto"
    ],
    "Odisha": [
        "Angul", "Balangir", "Balasore", "Bargarh", "Bhadrak", "Boudh", "Cuttack", "Deogarh",
        "Dhenkanal", "Gajapati", "Ganjam", "Jagatsinghpur", "Jajpur", "Jharsuguda", "Kalahandi",
        "Kandhamal", "Kendrapara", "Kendujhar", "Khordha", "Koraput", "Malkangiri", "Mayurbhanj",
        "Nabarangpur", "Nayagarh", "Nuapada", "Puri", "Rayagada", "Sambalpur", "Subarnapur", "Sundargarh"
    ],
    "Punjab": [
        "Amritsar", "Barnala", "Bathinda", "Faridkot", "Fatehgarh Sahib", "Fazilka", "Ferozepur",
        "Gurdaspur", "Hoshiarpur", "Jalandhar", "Kapurthala", "Ludhiana", "Malerkotla", "Mansa",
        "Moga", "Muktsar", "Pathankot", "Patiala", "Rupnagar", "Sahibzada Ajit Singh Nagar",
        "Sangrur", "Shahid Bhagat Singh Nagar", "Tarn Taran"
    ],
    "Rajasthan": [
        "Ajmer", "Alwar", "Anupgarh", "Balotra", "Banswara", "Baran", "Barmer", "Beawar",
        "Bharatpur", "Bhilwara", "Bikaner", "Bundi", "Chittorgarh", "Churu", "Dausa", "Deeg",
        "Dholpur", "Didwana Kuchaman", "Dudu", "Dungarpur", "Gangapur City", "Hanumangarh",
        "Jaipur", "Jaipur Rural", "Jaisalmer", "Jalore", "Jhalawar", "Jhunjhunu", "Jodhpur",
        "Jodhpur Rural", "Karauli", "Kekri", "Khairthal Tijara", "Kota", "Kotputli Behror",
        "Nagaur", "Neem Ka Thana", "Pali", "Phalodi", "Pratapgarh", "Rajsamand", "Salumbar",
        "Sanchore", "Sawai Madhopur", "Shahpura", "Sikar", "Sirohi", "Sri Ganganagar", "Tonk", "Udaipur"
    ],
    "Sikkim": [
        "Gangtok", "Geyzing", "Mangan", "Namchi", "Pakyong", "Soreng"
    ],
    "Tamil Nadu": [
        "Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore", "Dharmapuri", "Dindigul",
        "Erode", "Kallakurichi", "Kanchipuram", "Kanyakumari", "Karur", "Krishnagiri", "Madurai",
        "Mayiladuthurai", "Nagapattinam", "Namakkal", "Nilgiris", "Perambalur", "Pudukkottai",
        "Ramanathapuram", "Ranipet", "Salem", "Sivaganga", "Tenkasi", "Thanjavur", "Theni",
        "Thoothukudi", "Tiruchirappalli", "Tirunelveli", "Tirupathur", "Tiruppur", "Tiruvallur",
        "Tiruvannamalai", "Tiruvarur", "Vellore", "Viluppuram", "Virudhunagar"
    ],
    "Telangana": [
        "Adilabad", "Bhadradri Kothagudem", "Hanumakonda", "Hyderabad", "Jagtial", "Jangaon",
        "Jayashankar Bhupalpally", "Jogulamba Gadwal", "Kamareddy", "Karimnagar", "Khammam",
        "Kumuram Bheem Asifabad", "Mahabubabad", "Mahabubnagar", "Mancherial", "Medak",
        "Medchal Malkajgiri", "Mulugu", "Nagarkurnool", "Nalgonda", "Narayanpet", "Nirmal",
        "Nizamabad", "Peddapalli", "Rajanna Sircilla", "Ranga Reddy", "Sangareddy", "Siddipet",
        "Suryapet", "Vikarabad", "Wanaparthy", "Warangal", "Yadadri Bhuvanagiri"
    ],
    "Tripura": [
        "Dhalai", "Gomati", "Khowai", "North Tripura", "Sepahijala", "South Tripura", "Unakoti", "West Tripura"
    ],
    "Uttar Pradesh": [
        "Agra", "Aligarh", "Ambedkar Nagar", "Amethi", "Amroha", "Auraiya", "Ayodhya", "Azamgarh",
        "Baghpat", "Bahraich", "Ballia", "Balrampur", "Banda", "Barabanki", "Bareilly", "Basti",
        "Bhadohi", "Bijnor", "Budaun", "Bulandshahr", "Chandauli", "Chitrakoot", "Deoria",
        "Etah", "Etawah", "Farrukhabad", "Fatehpur", "Firozabad", "Gautam Buddha Nagar", "Ghaziabad",
        "Ghazipur", "Gonda", "Gorakhpur", "Hamirpur", "Hapur", "Hardoi", "Hathras", "Jalaun",
        "Jaunpur", "Jhansi", "Kannauj", "Kanpur Dehat", "Kanpur Nagar", "Kasganj", "Kaushambi",
        "Kheri", "Kushinagar", "Lalitpur", "Lucknow", "Maharajganj", "Mahoba", "Mainpuri",
        "Mathura", "Mau", "Meerut", "Mirzapur", "Moradabad", "Muzaffarnagar", "Pilibhit",
        "Pratapgarh", "Prayagraj", "Raebareli", "Rampur", "Saharanpur", "Sambhal", "Sant Kabir Nagar",
        "Shahjahanpur", "Shamli", "Shravasti", "Siddharthnagar", "Sitapur", "Sonbhadra",
        "Sultanpur", "Unnao", "Varanasi"
    ],
    "Uttarakhand": [
        "Almora", "Bageshwar", "Chamoli", "Champawat", "Dehradun", "Haridwar", "Nainital",
        "Pauri Garhwal", "Pithoragarh", "Rudraprayag", "Tehri Garhwal", "Udham Singh Nagar", "Uttarkashi"
    ],
    "West Bengal": [
        "Alipurduar", "Bankura", "Birbhum", "Cooch Behar", "Dakshin Dinajpur", "Darjeeling",
        "Hooghly", "Howrah", "Jalpaiguri", "Jhargram", "Kalimpong", "Kolkata", "Malda",
        "Murshidabad", "Nadia", "North 24 Parganas", "Paschim Bardhaman", "Paschim Medinipur",
        "Purba Bardhaman", "Purba Medinipur", "Purulia", "South 24 Parganas", "Uttar Dinajpur"
    ],

    # 8 Union Territories
    "Andaman and Nicobar Islands": [
        "Nicobars", "North and Middle Andaman", "South Andaman"
    ],
    "Chandigarh": [
        "Chandigarh"
    ],
    "Dadra and Nagar Haveli and Daman and Diu": [
        "Dadra and Nagar Haveli", "Daman", "Diu"
    ],
    "Delhi": [
        "Central Delhi", "East Delhi", "New Delhi", "North Delhi", "North East Delhi",
        "North West Delhi", "Shahdara", "South Delhi", "South East Delhi", "South West Delhi", "West Delhi"
    ],
    "Jammu and Kashmir": [
        "Anantnag", "Bandipora", "Baramulla", "Budgam", "Doda", "Ganderbal", "Jammu", "Kathua",
        "Kishtwar", "Kulgam", "Kupwara", "Poonch", "Pulwama", "Rajouri", "Ramban", "Reasi",
        "Samba", "Shopian", "Srinagar", "Udhampur"
    ],
    "Ladakh": [
        "Kargil", "Leh"
    ],
    "Lakshadweep": [
        "Lakshadweep"
    ],
    "Puducherry": [
        "Karaikal", "Mahe", "Puducherry", "Yanam"
    ]
}


def get_all_states():
    """Returns sorted list of all 28 states and 8 union territories (36 total)."""
    return sorted(list(INDIA_DISTRICTS.keys()))


def get_states_only():
    """Returns 28 Indian States."""
    return sorted(INDIAN_STATES)


def get_union_territories_only():
    """Returns 8 Union Territories."""
    return sorted(UNION_TERRITORIES)


def get_districts_for_state(state_name):
    """Returns list of districts for a given state or union territory."""
    if not state_name:
        return []
    # Case-insensitive lookup matching
    for s, dists in INDIA_DISTRICTS.items():
        if s.lower() == state_name.strip().lower():
            return sorted(dists)
    return []


def is_valid_state(state_name):
    """Check if state_name is a valid Indian State or Union Territory."""
    if not state_name:
        return False
    state_clean = state_name.strip().lower()
    return any(s.lower() == state_clean for s in INDIA_DISTRICTS.keys())


def is_valid_district(state_name, district_name):
    """Check if district_name is valid for the given state_name."""
    if not state_name or not district_name:
        return False
    valid_districts = get_districts_for_state(state_name)
    district_clean = district_name.strip().lower()
    return any(d.lower() == district_clean for d in valid_districts)


def get_all_locations_hierarchy():
    """Returns full dictionary of States/UTs to Districts."""
    return {state: sorted(dists) for state, dists in INDIA_DISTRICTS.items()}
