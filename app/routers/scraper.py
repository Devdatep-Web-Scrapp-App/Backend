from fastapi import APIRouter, Depends, HTTPException
from app.services.auth_service import get_current_user
from app.models.user import User
from app.tasks.celery_app import run_ig_scraper_task, run_tk_scraper_task

router = APIRouter(prefix="/scraper", tags=["Scraper"])

@router.post("/run-instagram")
def run_scraper_ig(current_user: User = Depends(get_current_user)):
    if not current_user.ig_username or not current_user.ig_password:
        raise HTTPException(status_code=400, detail="Credenciales de Instagram no configuradas")
    
    task = run_ig_scraper_task.delay(current_user.id, current_user.ig_username, current_user.ig_password)
    return {"message": "Scraping de Instagram iniciado", "task_id": task.id}

@router.post("/run-tiktok")
def run_scraper_tk(current_user: User = Depends(get_current_user)):
    if not current_user.tk_username or not current_user.tk_password:
        raise HTTPException(status_code=400, detail="Credenciales de TikTok no configuradas")
    
    task = run_tk_scraper_task.delay(current_user.id, current_user.tk_username, current_user.tk_password)
    return {"message": "Scraping de TikTok iniciado", "task_id": task.id}