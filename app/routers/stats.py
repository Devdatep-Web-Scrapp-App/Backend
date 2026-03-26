from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.services.auth_service import get_current_user
from app.models.user import User
from app.models.instagram import InstagramFollowersSnapshot, InstagramFollowersLost
from app.models.tiktok import TiktokFollowersSnapshot, TiktokFollowersLost
from app.schemas.stats import FollowerSnapshot, FollowerLost

router = APIRouter(prefix="/stats", tags=["Statistics"])

@router.get("/instagram/followers", response_model=List[FollowerSnapshot])
def get_ig_followers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(InstagramFollowersSnapshot).filter(InstagramFollowersSnapshot.app_user_id == current_user.id).all()

@router.get("/tiktok/followers", response_model=List[FollowerSnapshot])
def get_tk_followers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(TiktokFollowersSnapshot).filter(TiktokFollowersSnapshot.app_user_id == current_user.id).all()

@router.get("/instagram/lost", response_model=List[FollowerLost])
def get_ig_lost(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(InstagramFollowersLost).filter(InstagramFollowersLost.app_user_id == current_user.id).order_by(InstagramFollowersLost.fecha_perdida.desc()).all()

@router.get("/tiktok/lost", response_model=List[FollowerLost])
def get_tk_lost(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(TiktokFollowersLost).filter(TiktokFollowersLost.app_user_id == current_user.id).order_by(TiktokFollowersLost.fecha_perdida.desc()).all()

@router.get("/history")
def get_history_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ig_active = db.query(InstagramFollowersSnapshot).filter(InstagramFollowersSnapshot.app_user_id == current_user.id).count()
    ig_lost = db.query(InstagramFollowersLost).filter(InstagramFollowersLost.app_user_id == current_user.id).count()
    
    tk_active = db.query(TiktokFollowersSnapshot).filter(TiktokFollowersSnapshot.app_user_id == current_user.id).count()
    tk_lost = db.query(TiktokFollowersLost).filter(TiktokFollowersLost.app_user_id == current_user.id).count()
    
    return {
        "instagram": {"active": ig_active, "lost": ig_lost},
        "tiktok": {"active": tk_active, "lost": tk_lost}
    }