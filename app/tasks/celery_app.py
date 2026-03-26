from celery import Celery
from app.config import settings
from app.services.ig_scraper import InstagramScraperService
from app.services.tk_scraper import TiktokScraperService

celery_app = Celery("worker", broker=settings.CELERY_BROKER_URL, backend=settings.CELERY_RESULT_BACKEND)
celery_app.conf.update(task_track_started=True)

@celery_app.task(name="run_ig_scraper_task")
def run_ig_scraper_task(app_user_id: int, ig_username: str, ig_password: str):
    scraper = InstagramScraperService(app_user_id, ig_username, ig_password)
    return scraper.run_extraction()

@celery_app.task(name="run_tk_scraper_task")
def run_tk_scraper_task(app_user_id: int, tk_username: str, tk_password: str):
    scraper = TiktokScraperService(app_user_id, tk_username, tk_password)
    return scraper.run_extraction()