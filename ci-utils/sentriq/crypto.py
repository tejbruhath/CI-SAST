"""Small Fernet-based encryption helpers for stored OAuth tokens."""
import os  # load TOKEN_ENCRYPTION_KEY from the environment

from cryptography.fernet import Fernet, InvalidToken  # symmetric encrypt/decrypt helpers


_token_key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip() or None  # Fernet key or None if unset


def _fernet():
    """Build a Fernet instance; fail loud if encryption key is missing."""
    if not _token_key:  # cannot encrypt without a configured key
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")  # force ops to configure secrets
    return Fernet(_token_key.encode())  # Fernet expects key as bytes


def encrypt_token(plaintext: str) -> str:
    """Encrypt a sensitive token (e.g. GitHub access token) for DB storage."""
    if not plaintext:  # empty input stays empty (nothing to protect)
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()  # encrypt bytes, store as UTF-8 string


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored token. Returns empty string if input is empty or invalid."""
    if not ciphertext:  # nothing stored → nothing to return
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()  # reverse encrypt_token path
    except InvalidToken:  # bad key, corrupted data, or wrong ciphertext
        return ""  # soft-fail so callers can treat as "no token"
