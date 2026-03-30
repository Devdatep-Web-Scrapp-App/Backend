from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from celery.result import AsyncResult
from app.database import get_db
from app.services.auth_service import get_current_user
from app.models.user import User
from app.tasks.celery_app import run_ig_scraper_task, run_tk_scraper_task, celery_app
from app.services.ig_scraper import InstagramScraperService
from app.services.tk_scraper import TiktokScraperService


router = APIRouter(prefix="/scraper", tags=["Scraper"])

def _tarea_en_curso(task_id: str | None) -> bool:
    if not task_id:
        return False
    result = AsyncResult(task_id, app=celery_app)
    return result.state in ("PENDING", "STARTED", "RETRY")


# ── Instagram ────────────────────────────────────────────────────────────────

@router.post("/setup-instagram")
def setup_instagram(current_user: User = Depends(get_current_user)):
    if not current_user.ig_username:
        raise HTTPException(status_code=400, detail="Username de Instagram no configurado.")
    InstagramScraperService(current_user.id, current_user.ig_username).setup_session()
    return {"message": "Sesion de Instagram configurada correctamente."}

@router.post("/run-instagram")
def run_scraper_ig(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.ig_username:
        raise HTTPException(status_code=400, detail="Username de Instagram no configurado.")
    if _tarea_en_curso(current_user.ig_task_id):
        raise HTTPException(status_code=409, detail="Ya hay un scraping de Instagram en curso.")
    task = run_ig_scraper_task.delay(current_user.id, current_user.ig_username)
    current_user.ig_task_id = task.id
    db.commit()
    return {"message": "Scraping de Instagram iniciado", "task_id": task.id}

@router.get("/status-instagram")
def status_ig(current_user: User = Depends(get_current_user)):
    if not current_user.ig_task_id:
        return {"status": "never_run", "task_id": None, "result": None}
    result = AsyncResult(current_user.ig_task_id, app=celery_app)
    return {"status": result.state, "task_id": current_user.ig_task_id, "result": str(result.result) if result.ready() else None}


# ── TikTok ───────────────────────────────────────────────────────────────────

@router.post("/setup-tiktok")
def setup_tiktok(current_user: User = Depends(get_current_user)):
    if not current_user.tk_username:
        raise HTTPException(status_code=400, detail="Username de TikTok no configurado.")
    TiktokScraperService(current_user.id, current_user.tk_username).setup_session()
    return {"message": "Navegador abierto. Inicia sesion manualmente y presiona ENTER en la terminal."}

@router.post("/run-tiktok")
def run_scraper_tk(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not current_user.tk_username:
        raise HTTPException(status_code=400, detail="Username de TikTok no configurado.")
    if _tarea_en_curso(current_user.tk_task_id):
        raise HTTPException(status_code=409, detail="Ya hay un scraping de TikTok en curso.")
    task = run_tk_scraper_task.delay(current_user.id, current_user.tk_username)
    current_user.tk_task_id = task.id
    db.commit()
    return {"message": "Scraping de TikTok iniciado", "task_id": task.id}

@router.get("/status-tiktok")
def status_tk(current_user: User = Depends(get_current_user)):
    if not current_user.tk_task_id:
        return {"status": "never_run", "task_id": None, "result": None}
    result = AsyncResult(current_user.tk_task_id, app=celery_app)
    return {"status": result.state, "task_id": current_user.tk_task_id, "result": str(result.result) if result.ready() else None}