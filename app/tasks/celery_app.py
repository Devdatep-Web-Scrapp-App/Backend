from celery import Celery
from celery.schedules import crontab
from app.config import settings
from app.services.ig_scraper import InstagramScraperService
from app.services.tk_scraper import TiktokScraperService


celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)
celery_app.conf.update(task_track_started=True)


@celery_app.task(name="run_ig_scraper_task")
def run_ig_scraper_task(app_user_id: int, ig_username: str):
    scraper = InstagramScraperService(app_user_id, ig_username)
    return scraper.run_extraction()

@celery_app.task(name="run_tk_scraper_task")
def run_tk_scraper_task(app_user_id: int, tk_username: str):
    scraper = TiktokScraperService(app_user_id, tk_username)
    return scraper.run_extraction()


@celery_app.task(name="run_daily_sync")
def run_daily_sync():
    """
    Ejecutada por Celery Beat cada minuto.
    Compara la hora actual con la hora configurada por cada usuario
    y lanza el scraping si coincide.
    """
    from datetime import datetime, timezone
    from app.database import Sessionlocal
    from app.models.user import User
    from app.models.sync_config import SyncConfig

    db = Sessionlocal()
    try:
        now = datetime.now()
        users = db.query(User).filter(User.ig_username.isnot(None), User.is_active == True).all()

        for user in users:
            config = db.query(SyncConfig).filter(SyncConfig.app_user_id == user.id).first()
            hour   = config.sync_hour   if config else 8
            minute = config.sync_minute if config else 0

            if now.hour == hour and now.minute == minute:
                run_ig_scraper_task.delay(user.id, user.ig_username)
                print(f"[Beat] Sync lanzado para user {user.id} (@{user.ig_username})")
    finally:
        db.close()


# Celery Beat: ejecuta run_daily_sync cada minuto para verificar qué usuarios deben sincronizar
celery_app.conf.beat_schedule = {
    "check-daily-sync": {
        "task": "run_daily_sync",
        "schedule": crontab(minute="*"),  # cada minuto
    },
}
celery_app.conf.timezone = "America/Lima"