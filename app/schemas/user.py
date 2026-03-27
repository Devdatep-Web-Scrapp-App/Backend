from pydantic import BaseModel, EmailStr
from typing import Optional

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    ig_username: Optional[str]
    tk_username: Optional[str]

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class SettingsUpdate(BaseModel):
    full_name: Optional[str] = None

class PasswordUpdate(BaseModel):
    current_password: str
    new_password: str

class SocialConnect(BaseModel):
    username: str
    password: str

# --- Schemas faltantes para el flujo de recuperación de contraseña ---

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str