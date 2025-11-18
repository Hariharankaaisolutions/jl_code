# modules/role_manager.py

from utils_config_loader import load_properties
from logger import get_logger

logger = get_logger("role_manager")

ROLES = load_properties("role.properties")

BUSINESS_ROLES = [
    r.strip().upper()
    for r in ROLES.get("BUSINESS_ROLES", "MD,JMD,GM,AGM").split(",")
    if r.strip()
]

IT_ROLES = [
    r.strip().upper()
    for r in ROLES.get("IT_ROLES", "IT HEAD").split(",")
    if r.strip()
]

IT_BRANCH_RESTRICTED = ROLES.get("IT_BRANCH_RESTRICTED", "True").lower() == "true"


def get_roles_for_otp(branch_name: str):
    """
    Returns a role mapping dict for business + IT roles
    with branch restrictions handled.
    """
    logger.info(
        f"OTP role fetch => branch={branch_name}, "
        f"business={BUSINESS_ROLES}, it={IT_ROLES}, restricted={IT_BRANCH_RESTRICTED}"
    )

    return {
        "business": {
            "roles": BUSINESS_ROLES,
            "branch": None
        },
        "it": {
            "roles": IT_ROLES,
            "branch_restricted": IT_BRANCH_RESTRICTED,
            "branch": branch_name if IT_BRANCH_RESTRICTED else None
        }
    }
