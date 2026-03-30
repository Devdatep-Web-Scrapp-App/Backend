from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
    __tablename__ = "app_users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))

    # Instagram — usuario y contraseña encriptada con Fernet (necesaria para instagrapi)
    ig_username = Column(String(100), nullable=True)
    ig_password = Column(String(255), nullable=True)

    # TikTok — solo username, el login es manual via Selenium
    tk_username = Column(String(100), nullable=True)

    # Ultima tarea Celery lanzada por red social
    ig_task_id = Column(String(255), nullable=True)
    tk_task_id = Column(String(255), nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())