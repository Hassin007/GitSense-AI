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


# ── PAT Encryption at Rest ───────────────────────────────────────────────────

import base64
from cryptography.fernet import Fernet, InvalidToken

def _get_fernet() -> Fernet:
    key_bytes = hashlib.sha256(settings.app_secret_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)

def encrypt_pat(pat: str) -> str:
    """Encrypt a GitHub PAT before storing in DB."""
    if not pat:
        return ""
    f = _get_fernet()
    return f.encrypt(pat.encode("utf-8")).decode("utf-8")

def decrypt_pat(encrypted_pat: str) -> str:
    """Decrypt a GitHub PAT retrieved from DB. Gracefully falls back if unencrypted."""
    if not encrypted_pat:
        return ""
    try:
        f = _get_fernet()
        return f.decrypt(encrypted_pat.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        # Return as-is if token was stored in plaintext prior to encryption feature
        return encrypted_pat
