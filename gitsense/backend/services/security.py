import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from jose import jwt, JWTError
from backend.config import settings


# ── Webhook HMAC Validation ──────────────────────────────────────────────────

def verify_github_signature(payload_body: bytes, signature_header: str) -> bool:
    """
    GitHub signs every webhook payload with HMAC-SHA256.
    We compute what the signature should be and compare.
    Returns True if valid, raises HTTPException 403 if not.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Missing or malformed GitHub signature.")

    expected_sig = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode("utf-8"),
        payload_body,
        hashlib.sha256
    ).hexdigest()

    # Use compare_digest to prevent timing attacks
    if not hmac.compare_digest(expected_sig, signature_header):
        raise HTTPException(status_code=403, detail="Invalid webhook signature. Request rejected.")

    return True


# ── JWT Auth ─────────────────────────────────────────────────────────────────

def create_access_token(user_id: int, github_username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "username": github_username,
        "exp": expire
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
