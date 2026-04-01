#!/bin/bash
# Lanzar Celery worker en background
celery -A app.tasks.celery_app worker --loglevel=error --pool=solo --concurrency=1 &

# Lanzar Celery beat en background
celery -A app.tasks.celery_app beat --loglevel=error &

# Lanzar FastAPI (proceso principal)
python -m app