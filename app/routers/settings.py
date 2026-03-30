from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserResponse, SocialConnect, SettingsUpdate, PasswordUpdate
from app.services.auth_service import get_current_user, verify_password, get_password_hash

router = APIRouter(prefix="/settings", tags=["Settings"])

@router.put("/connect-instagram", response_model=UserResponse)
def connect_instagram(data: SocialConnect, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.ig_username = data.username
    db.commit()
    db.refresh(current_user)
    return current_user

@router.put("/connect-tiktok", response_model=UserResponse)
def connect_tiktok(data: SocialConnect, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.tk_username = data.username
    db.commit()
    db.refresh(current_user)
    return current_user

@router.put("/update-profile", response_model=UserResponse)
def update_profile(data: SettingsUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if data.full_name:
        current_user.full_name = data.full_name
    db.commit()
    db.refresh(current_user)
    return current_user

@router.put("/change-password")
def change_password(data: PasswordUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="La contrasena actual es incorrecta")
    current_user.hashed_password = get_password_hash(data.new_password)
    db.commit()
    return {"message": "Contrasena actualizada exitosamente"}

@router.put("/disconnect-instagram", response_model=UserResponse)
def disconnect_instagram(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.ig_username = None
    current_user.ig_task_id  = None
    db.commit()
    db.refresh(current_user)
    return current_user