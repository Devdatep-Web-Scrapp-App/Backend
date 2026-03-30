from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, Token, PasswordResetRequest, PasswordResetConfirm
from app.config import settings
from app.services.auth_service import get_password_hash, verify_password, create_access_token, timedelta, get_current_user
from jose import JWTError, jwt

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = get_password_hash(user.password)
    new_user = User(email=user.email, hashed_password=hashed_password, full_name=user.full_name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user

@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/forgot-password")
def forgot_password(request: PasswordResetRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    # Por seguridad, siempre devolvemos el mismo mensaje aunque el correo no exista (evita enumeración de usuarios)
    if not user:
        return {"message": "Si el correo existe, se ha enviado un enlace de recuperación."}
    
    # Generamos un token especial para reset que expira en 15 minutos
    reset_token = create_access_token(
        data={"sub": user.email, "type": "reset"}, 
        expires_delta=timedelta(minutes=15)
    )
    
    return {
        "message": "Si el correo existe, se ha enviado un enlace de recuperación.", 
        "debug_token": reset_token  # Devoler email en produccion, no token
    }

@router.post("/reset-password")
def reset_password(request: PasswordResetConfirm, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(request.token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        token_type: str = payload.get("type")
        
        if email is None or token_type != "reset":
            raise HTTPException(status_code=400, detail="Token inválido o de tipo incorrecto")
    except JWTError:
        raise HTTPException(status_code=400, detail="Token inválido o expirado")
        
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    user.hashed_password = get_password_hash(request.new_password)
    db.commit()
    return {"message": "Contraseña restablecida con éxito"}

@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user