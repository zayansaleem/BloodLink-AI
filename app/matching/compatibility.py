"""
Medical-grade preliminary blood compatibility rules across blood components.
Enforces standard ABO/Rh compatibility rules for Red Blood Cells, separate
clinically reviewed rules for Plasma, and explicit clinical-review flagging
for Platelets and other specialized blood components.

DISCLAIMER: Preliminary matching only assists logistical candidate selection.
Formal laboratory cross-matching, antibody screening, infectious marker testing,
and clinical donor suitability evaluation must always be conducted by qualified
medical personnel prior to any transfusion.
"""

from typing import Optional, Dict, List, Any

VALID_BLOOD_GROUPS = ['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']

# =========================================================================
# 1. RED BLOOD CELLS (RBC) & WHOLE BLOOD COMPATIBILITY
# =========================================================================
# Standard ABO/Rh donor-to-recipient red cell compatibility:
# Donors present antigens on erythrocytes; recipients must not have corresponding antibodies.

# Recipient Group -> List of Compatible Donor Blood Groups (Who can give to this recipient)
RECIPIENT_TO_DONOR_RBC: Dict[str, List[str]] = {
    'O-': ['O-'],
    'O+': ['O-', 'O+'],
    'A-': ['O-', 'A-'],
    'A+': ['O-', 'O+', 'A-', 'A+'],
    'B-': ['O-', 'B-'],
    'B+': ['O-', 'O+', 'B-', 'B+'],
    'AB-': ['O-', 'A-', 'B-', 'AB-'],
    'AB+': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],  # Universal recipient
}

# Donor Group -> List of Compatible Recipient Blood Groups (Whom this donor can give to)
DONOR_TO_RECIPIENT_RBC: Dict[str, List[str]] = {
    'O-': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],  # Universal donor
    'O+': ['O+', 'A+', 'B+', 'AB+'],  # All Rh-positive recipient groups
    'A-': ['A-', 'A+', 'AB-', 'AB+'],
    'A+': ['A+', 'AB+'],
    'B-': ['B-', 'B+', 'AB-', 'AB+'],
    'B+': ['B+', 'AB+'],
    'AB-': ['AB-', 'AB+'],
    'AB+': ['AB+'],  # Only AB+ recipients
}

# Backwards compatibility alias
RBC_COMPATIBILITY = RECIPIENT_TO_DONOR_RBC


# =========================================================================
# 2. FRESH FROZEN PLASMA (FFP) COMPATIBILITY
# =========================================================================
# Plasma transfusions have reversed ABO polarity because plasma contains antibodies
# and is acellular (no intact erythrocytes).
# Group AB plasma lacks anti-A and anti-B antibodies -> Universal Plasma Donor.
# Group O plasma contains both anti-A and anti-B antibodies -> Can only donate to O recipients.

# Recipient Group -> List of Compatible Plasma Donor Groups
RECIPIENT_TO_DONOR_PLASMA: Dict[str, List[str]] = {
    'O-': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],  # Universal recipient for plasma
    'O+': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],
    'A-': ['A-', 'A+', 'AB-', 'AB+'],
    'A+': ['A-', 'A+', 'AB-', 'AB+'],
    'B-': ['B-', 'B+', 'AB-', 'AB+'],
    'B+': ['B-', 'B+', 'AB-', 'AB+'],
    'AB-': ['AB-', 'AB+'],
    'AB+': ['AB-', 'AB+'],  # Only AB plasma
}

# Donor Group -> List of Compatible Plasma Recipient Groups
DONOR_TO_RECIPIENT_PLASMA: Dict[str, List[str]] = {
    'AB+': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],  # Universal plasma donor
    'AB-': ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'],
    'A+': ['O-', 'O+', 'A-', 'A+'],
    'A-': ['O-', 'O+', 'A-', 'A+'],
    'B+': ['O-', 'O+', 'B-', 'B+'],
    'B-': ['O-', 'O+', 'B-', 'B+'],
    'O+': ['O-', 'O+'],
    'O-': ['O-', 'O+'],
}

# Backwards compatibility alias
PLASMA_COMPATIBILITY = RECIPIENT_TO_DONOR_PLASMA


# =========================================================================
# 3. SPECIALIZED BLOOD COMPONENTS REQUIRING CLINICAL REVIEW
# =========================================================================
# Platelets, Cryoprecipitate, and Granulocytes:
# Platelet transfusions involve ABO-identical preferences, consideration of isohemagglutinins
# in suspending plasma, Rh immunoprophylaxis guidelines, and HLA alloimmunization.
# Automated RBC or Plasma matrices MUST NOT be blindly applied to platelets.
# If safe automated matching is not supported, the request is flagged for clinical review.
CLINICAL_REVIEW_COMPONENTS = {
    'PLATELETS', 'PLATELET', 'RANDOM DONOR PLATELETS', 'RDP',
    'SINGLE DONOR PLATELETS', 'SDP', 'APHERESIS PLATELETS',
    'CRYOPRECIPITATE', 'CRYO', 'GRANULOCYTES'
}


def normalize_component_type(component_type: Optional[str]) -> str:
    """Normalize blood component string for deterministic rule evaluation."""
    if not component_type:
        return 'Whole Blood'
    c = component_type.strip()
    c_upper = c.upper()
    if 'PLASMA' in c_upper or 'FFP' in c_upper:
        return 'Plasma'
    elif any(k in c_upper for k in ['PLATELET', 'RDP', 'SDP', 'CRYO', 'GRANULOCYTE']):
        return 'Platelets'
    elif any(k in c_upper for k in ['RED BLOOD', 'RBC', 'PACKED CELL', 'PRBC']):
        return 'Red Blood Cells'
    elif 'WHOLE' in c_upper:
        return 'Whole Blood'
    return c


def is_component_supported_for_automated_matching(component_type: Optional[str]) -> bool:
    """
    Check if the requested component supports automated algorithmic matching.
    Currently: 'Whole Blood', 'Red Blood Cells', and 'Plasma' are supported.
    'Platelets' and other specialized components require manual clinical review.
    """
    comp = normalize_component_type(component_type)
    return comp in ('Whole Blood', 'Red Blood Cells', 'Plasma')


def evaluate_component_compatibility(
    donor_group: Optional[str],
    recipient_group: Optional[str],
    component_type: Optional[str] = 'Whole Blood'
) -> Dict[str, Any]:
    """
    Evaluates compatibility between a donor and a recipient/request, returning
    a comprehensive medical decision dictionary.
    
    Returns:
        dict with keys:
            - is_compatible (bool): Whether candidate matches automatically.
            - status (str): 'COMPATIBLE', 'INCOMPATIBLE', 'REQUIRES_CLINICAL_REVIEW', or 'INVALID'
            - reason (str): Human-readable clinical rationale.
            - strategy (str): 'RBC_STANDARD', 'PLASMA_REVERSED', or 'CLINICAL_REVIEW_REQUIRED'
            - requires_review (bool): True if component requires manual clinical assessment.
    """
    d = (donor_group or '').strip().upper()
    r = (recipient_group or '').strip().upper()
    comp = normalize_component_type(component_type)

    if not d or d not in VALID_BLOOD_GROUPS or not r or r not in VALID_BLOOD_GROUPS:
        return {
            'is_compatible': False,
            'status': 'INVALID',
            'reason': f"Invalid or missing blood group (Donor: '{donor_group}', Recipient: '{recipient_group}').",
            'strategy': 'UNKNOWN',
            'requires_review': False
        }

    # Strategy 1: Specialized components requiring clinical pathologist evaluation
    if comp in ('Platelets',) or comp.upper() in CLINICAL_REVIEW_COMPONENTS:
        return {
            'is_compatible': False,
            'status': 'REQUIRES_CLINICAL_REVIEW',
            'reason': (
                f"Matching for '{comp}' involves complex ABO-plasma antibody titers, "
                "HLA considerations, and volume factors. Automated matching is not applied; "
                "this request requires clinical review by an authorized pathologist."
            ),
            'strategy': 'CLINICAL_REVIEW_REQUIRED',
            'requires_review': True
        }

    # Strategy 2: Plasma (Reversed polarity)
    if comp == 'Plasma':
        compatible_recipients = DONOR_TO_RECIPIENT_PLASMA.get(d, [])
        is_compat = r in compatible_recipients
        return {
            'is_compatible': is_compat,
            'status': 'COMPATIBLE' if is_compat else 'INCOMPATIBLE',
            'reason': (
                f"Donor {d} plasma is {'compatible' if is_compat else 'incompatible'} with recipient {r} "
                "under plasma anti-A/anti-B isohemagglutinin rules."
            ),
            'strategy': 'PLASMA_REVERSED',
            'requires_review': False
        }

    # Strategy 3: Red Blood Cells & Whole Blood (Standard ABO/Rh erythrocyte matrix)
    compatible_recipients = DONOR_TO_RECIPIENT_RBC.get(d, [])
    is_compat = r in compatible_recipients
    return {
        'is_compatible': is_compat,
        'status': 'COMPATIBLE' if is_compat else 'INCOMPATIBLE',
        'reason': (
            f"Donor {d} red cells are {'compatible' if is_compat else 'incompatible'} with recipient {r} "
            "under standard ABO/Rh donor-to-recipient erythrocyte compatibility rules."
        ),
        'strategy': 'RBC_STANDARD',
        'requires_review': False
    }


def is_preliminarily_compatible(
    donor_group: Optional[str],
    recipient_group: Optional[str],
    component_type: Optional[str] = 'Whole Blood'
) -> bool:
    """
    Evaluate preliminary compatibility according to specified component type.
    Returns True ONLY if automated matching is clinically supported and compatible.
    Returns False for incompatible blood groups or components requiring clinical review.
    """
    result = evaluate_component_compatibility(donor_group, recipient_group, component_type)
    return result['is_compatible']


def get_compatible_donor_groups(
    recipient_group: Optional[str],
    component_type: Optional[str] = 'Whole Blood'
) -> List[str]:
    """
    Return all preliminary compatible donor blood groups for a given recipient/patient group.
    Returns empty list if component requires manual clinical review or recipient group is invalid.
    """
    r = (recipient_group or '').strip().upper()
    if r not in VALID_BLOOD_GROUPS:
        return []

    comp = normalize_component_type(component_type)
    if comp == 'Plasma':
        return list(RECIPIENT_TO_DONOR_PLASMA.get(r, []))
    elif comp in ('Red Blood Cells', 'Whole Blood'):
        return list(RECIPIENT_TO_DONOR_RBC.get(r, []))
    else:
        # Components requiring clinical review do not return automated groups
        return []


def get_compatible_recipient_groups(
    donor_group: Optional[str],
    component_type: Optional[str] = 'Whole Blood'
) -> List[str]:
    """
    Return all preliminary compatible recipient/patient blood groups for a given donor blood group.
    Returns empty list if component requires manual clinical review or donor group is invalid.
    """
    d = (donor_group or '').strip().upper()
    if d not in VALID_BLOOD_GROUPS:
        return []

    comp = normalize_component_type(component_type)
    if comp == 'Plasma':
        return list(DONOR_TO_RECIPIENT_PLASMA.get(d, []))
    elif comp in ('Red Blood Cells', 'Whole Blood'):
        return list(DONOR_TO_RECIPIENT_RBC.get(d, []))
    else:
        return []
