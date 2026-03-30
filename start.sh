#!/bin/bash
# Lanzar Celery worker en background
celery -A app.tasks.celery_app worker --loglevel=info --pool=solo &

# Lanzar Celery beat en background
celery -A app.tasks.celery_app beat --loglevel=info &

# Lanzar FastAPI (proceso principal)
python -m app