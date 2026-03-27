from cryptography.fernet import Fernet
from app.config import settings

def _get_fernet() -> Fernet:
    return Fernet(settings.ENCRYPTION_KEY.encode())

def encrypt(plain_text: str) -> str:
    """Encripta un string y devuelve el resultado como string."""
    return _get_fernet().encrypt(plain_text.encode()).decode()

def decrypt(cipher_text: str) -> str:
    """Desencripta un string encriptado con Fernet."""
    return _get_fernet().decrypt(cipher_text.encode()).decode()