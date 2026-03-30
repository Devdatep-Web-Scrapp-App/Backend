from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.database import get_db
from app.models.user import User
from app.models.sync_config import SyncConfig
from app.services.auth_service import get_current_user

router = APIRouter(prefix="/sync", tags=["Sync"])

class SyncConfigSchema(BaseModel):
    sync_hour:   int  # 0-23
    sync_minute: int  # 0-59

@router.get("/config")
def get_sync_config(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    config = db.query(SyncConfig).filter(SyncConfig.app_user_id == current_user.id).first()
    if not config:
        return {"sync_hour": 8, "sync_minute": 0}
    return {"sync_hour": config.sync_hour, "sync_minute": config.sync_minute}

@router.put("/config")
def update_sync_config(data: SyncConfigSchema, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    config = db.query(SyncConfig).filter(SyncConfig.app_user_id == current_user.id).first()
    if not config:
        config = SyncConfig(app_user_id=current_user.id)
        db.add(config)
    config.sync_hour   = max(0, min(23, data.sync_hour))
    config.sync_minute = max(0, min(59, data.sync_minute))
    db.commit()
    return {"sync_hour": config.sync_hour, "sync_minute": config.sync_minute}