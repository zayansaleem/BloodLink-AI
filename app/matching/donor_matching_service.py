"""
Donor Matching Service re-export for modular convenience.
"""

from app.services.donor_matching_service import (
    search_matching_donors,
    SUPPORTED_COMPONENTS,
    VALID_BLOOD_GROUPS
)

__all__ = [
    'search_matching_donors',
    'SUPPORTED_COMPONENTS',
    'VALID_BLOOD_GROUPS'
]
