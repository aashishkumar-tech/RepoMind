"""
step1/signature.py — GitHub Webhook Signature Validator

HOW IT WORKS:
─────────────
GitHub signs every webhook payload with HMAC-SHA256 using your webhook secret.

The signature is sent in the `X-Hub-Signature-256` header:
    sha256=<hex_digest>

We recompute the HMAC on our side and compare.
If they don't match → the request is forged → reject with 403.

SECURITY:
    - Uses hmac.compare_digest() for constant-time comparison
      (prevents timing attacks)
    - Never logs the secret or signature values
    - Fails closed (reject on any error)

USAGE:
    from step1.signature import validate_signature
    is_valid = validate_signature(payload_body, header_signature, secret)

COMMUNICATION:
─────────────
Called by webhook_handler.py on every incoming request.
If validation fails → return 403 immediately, do NOT process.
"""

import hmac
import hashlib

from shared.logger import get_logger

logger = get_logger("step1.signature")


def validate_signature(
    payload_body: bytes,
    signature_header: str,
    secret: str,
) -> bool:
    """
    Validate GitHub webhook HMAC-SHA256 signature.

    Args:
        payload_body: Raw request body bytes (NOT decoded/parsed)
        signature_header: Value of X-Hub-Signature-256 header
                         Format: "sha256=<hex_digest>"
        secret: Your GITHUB_WEBHOOK_SECRET

    Returns:
        True if signature is valid, False otherwise

    Security:
        - Constant-time comparison via hmac.compare_digest
        - Rejects empty/malformed signatures
    """
    if not signature_header:
        logger.warning("signature_missing")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("signature_bad_format", header=signature_header[:20])
        return False

    # Extract the hex digest from "sha256=<hex_digest>"
    received_signature = signature_header[7:]  # Remove "sha256=" prefix

    # Compute expected HMAC-SHA256
    expected_signature = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison (prevents timing attacks)
    is_valid = hmac.compare_digest(expected_signature, received_signature)

    if not is_valid:
        logger.warning("signature_invalid")
    else:
        logger.debug("signature_valid")

    return is_valid
