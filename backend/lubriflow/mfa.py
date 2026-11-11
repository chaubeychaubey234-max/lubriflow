"""RFC 6238 authenticators; secrets encrypted separately from the database."""
import base64
import hashlib
import hmac
import secrets
import struct
from time import time

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from .config import settings


def cipher():
    key = settings().mfa_encryption_key
    if not key:
        raise HTTPException(503, "Authenticator key is not configured. Contact your administrator.")
    return Fernet(key.encode())


def encrypt(secret):
    return cipher().encrypt(secret.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        raise HTTPException(503, "Authenticator key is unavailable. Contact your administrator.") from None


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode()


def totp(secret, step, digits=6):
    raw = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = raw[-1] & 15
    number = struct.unpack(">I", raw[offset:offset + 4])[0] & 0x7fffffff
    return str(number % (10 ** digits)).zfill(digits)


def matching_step(secret, code, previous=None):
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    current = int(time()) // 30
    for step in (current, current - 1, current + 1):
        if (previous is None or step > previous) and hmac.compare_digest(totp(secret, step), code):
            return step
    return None


def recovery_hash(code):
    return hashlib.sha256(code.strip().replace("-", "").lower().encode()).hexdigest()


def new_recovery_codes():
    return [secrets.token_hex(16) for _ in range(10)]


def verify_factor(user, code):
    """Caller must hold the user row lock and commit successful consumption."""
    if not user.mfa_secret:
        return True
    code = code.strip()
    step = matching_step(decrypt(user.mfa_secret), code, user.mfa_last_step)
    if step is not None:
        user.mfa_last_step = step
        return True
    hashed = recovery_hash(code)
    match = next((value for value in user.mfa_recovery if hmac.compare_digest(value, hashed)), None)
    if match:
        user.mfa_recovery = [value for value in user.mfa_recovery if value != match]
        return True
    return False
