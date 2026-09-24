"""Email and Identity Validation, Normalization, and Derivation Domain Rules (DEV-SPEC §8, §15.5, §20, SP-301)."""

import re
import uuid
from typing import Tuple
from app.core.errors import ValidationError

# RFC 5322 compliant email regex matching standard web form and API validations
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)

# RFC 5321 length limits
MAX_EMAIL_LENGTH = 320
MAX_LOCAL_PART_LENGTH = 64
MAX_DOMAIN_LENGTH = 255


def validate_and_normalize_email(email_input: str) -> Tuple[str, str]:
    """
    Validates and normalizes an email address.
    
    Returns:
        (raw_email, email_normalized):
        - raw_email: trimmed original input string
        - email_normalized: trimmed lowercase string for one-email-one-sketch identity consistency.
        
    Raises:
        ValidationError: if the email is empty, malformed, or exceeds length limits.
    """
    if not isinstance(email_input, str):
        raise ValidationError("Email address must be a string.")

    raw_email = email_input.strip()
    if not raw_email:
        raise ValidationError("Email address cannot be empty.")

    if len(raw_email) > MAX_EMAIL_LENGTH:
        raise ValidationError(
            f"Email address exceeds maximum length of {MAX_EMAIL_LENGTH} characters."
        )

    if "@" not in raw_email:
        raise ValidationError("Invalid email address: missing '@' symbol.")

    parts = raw_email.split("@")
    if len(parts) != 2:
        raise ValidationError("Invalid email address: multiple '@' symbols.")

    local_part, domain_part = parts
    if not local_part or not domain_part:
        raise ValidationError("Invalid email address: local part and domain must not be empty.")

    if len(local_part) > MAX_LOCAL_PART_LENGTH:
        raise ValidationError(
            f"Email local part exceeds maximum length of {MAX_LOCAL_PART_LENGTH} characters."
        )

    if len(domain_part) > MAX_DOMAIN_LENGTH:
        raise ValidationError(
            f"Email domain exceeds maximum length of {MAX_DOMAIN_LENGTH} characters."
        )

    if ".." in raw_email:
        raise ValidationError("Invalid email address: consecutive dots are not allowed.")

    if not EMAIL_REGEX.match(raw_email):
        raise ValidationError(f"Invalid email address format: '{raw_email}'.")

    # Domain must have at least one dot and a TLD of at least 2 letters/numbers
    domain_labels = domain_part.split(".")
    if len(domain_labels) < 2 or not domain_labels[-1]:
        raise ValidationError(f"Invalid email domain format: '{domain_part}'.")

    email_normalized = raw_email.lower()
    return raw_email, email_normalized


def derive_user_id_for_email(email_normalized: str) -> uuid.UUID:
    """
    Derives a deterministic UUIDv5 from normalized email.

    NOTE (DEV-SPEC §8.3 / H-2 Invariant):
    Anonymous quiz funnel email capture does NOT assign or derive user_id on the session.
    Anonymous sessions maintain session.user_id = None.
    This helper is reserved strictly for trusted/internal operations where deterministic
    namespace mapping from email is explicitly needed, and is NOT invoked during anonymous capture.
    """
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mailto:{email_normalized}")
