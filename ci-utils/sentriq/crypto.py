"""Small Fernet-based encryption helpers for stored OAuth tokens."""
import os

from cryptography.fernet import Fernet, InvalidToken


_token_key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip() or None


def _fernet():
    if not _token_key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")
    return Fernet(_token_key.encode())


def encrypt_token(plaintext: str) -> str:
    """Encrypt a sensitive token (e.g. GitHub access token) for DB storage."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a stored token. Returns empty string if input is empty or invalid."""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return ""
