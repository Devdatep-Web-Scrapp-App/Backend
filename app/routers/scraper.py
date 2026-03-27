from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from celery.result import AsyncResult
from app.database import get_db
from app.services.auth_service import get_current_user
from app.services.crypto_service import decrypt
from app.models.user import User
from app.tasks.celery_app import run_ig_scraper_task, celery_app

router = APIRouter(prefix="/scraper", tags=["Scraper"])

def _tarea_en_curso(task_id: str | None) -> bool:
    if not task_id:
        return False
    result = AsyncResult(task_id, app=celery_app)
    return result.state in ("PENDING", "STARTED", "RETRY")

@router.post("/setup-instagram")
def setup_instagram(current_user: User = Depends(get_current_user)):
    """
    Abre Chrome visible para hacer login manual una sola vez.
    Solo necesario la primera vez o cuando expira la sesion.
    IMPORTANTE: Este endpoint bloquea hasta que el usuario complete el login.
    """
    if not current_user.ig_username or not current_user.ig_password:
        raise HTTPException(status_code=400, detail="Credenciales de Instagram no configuradas")

    from app.services.ig_scraper import InstagramScraperService
    scraper = InstagramScraperService(
        current_user.id,
        current_user.ig_username,
        decrypt(current_user.ig_password)
    )
    scraper.setup_session()
    return {"message": "Sesion de Instagram configurada correctamente."}

@router.post("/run-instagram")
def run_scraper_ig(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not current_user.ig_username or not current_user.ig_password:
        raise HTTPException(status_code=400, detail="Credenciales de Instagram no configuradas")

    if _tarea_en_curso(current_user.ig_task_id):
        raise HTTPException(
            status_code=409,
            detail="Ya hay un scraping de Instagram en curso. Espera a que termine."
        )

    task = run_ig_scraper_task.delay(
        current_user.id,
        current_user.ig_username,
        decrypt(current_user.ig_password)
    )

    current_user.ig_task_id = task.id
    db.commit()

    return {"message": "Scraping de Instagram iniciado", "task_id": task.id}

@router.get("/status-instagram")
def status_ig(current_user: User = Depends(get_current_user)):
    if not current_user.ig_task_id:
        return {"status": "never_run", "task_id": None, "result": None}
    result = AsyncResult(current_user.ig_task_id, app=celery_app)
    return {
        "status": result.state,
        "task_id": current_user.ig_task_id,
        "result": str(result.result) if result.ready() else None
    }

# TikTok desactivado temporalmente
# @router.post("/setup-tiktok")
# @router.post("/run-tiktok")
# @router.get("/status-tiktok")