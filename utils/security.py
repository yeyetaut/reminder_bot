from cryptography.fernet import Fernet
import json
from typing import Optional, Any
from config import ENCRYPTION_KEY

_cipher_suite = Fernet(ENCRYPTION_KEY.encode('utf-8'))

def encrypt_string(data: str) -> str:
    """Encrypts a string using Fernet symmetric encryption."""
    if not data:
        return data
    return _cipher_suite.encrypt(data.encode('utf-8')).decode('utf-8')

def decrypt_string(encrypted_data: str) -> str:
    """Decrypts a Fernet encrypted string."""
    if not encrypted_data:
        return encrypted_data
    return _cipher_suite.decrypt(encrypted_data.encode('utf-8')).decode('utf-8')

def encrypt_json(data: Any) -> str:
    """Encrypts a JSON serializable object."""
    if not data:
        return ""
    json_str = json.dumps(data)
    return encrypt_string(json_str)

def decrypt_json(encrypted_data: str) -> Any:
    """Decrypts to a JSON serializable object."""
    if not encrypted_data:
        return None
    json_str = decrypt_string(encrypted_data)
    return json.loads(json_str)
