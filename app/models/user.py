from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base

class User(Base):
  __tablename__ = "app_users" # Nombre de usuarios que se conectarán

  id = Column(Integer, primary_key=True, index=True)
  email = Column(String(100), unique=True, index=True, nullable=False)
  hashed_password = Column(String(255), nullable=False)
  full_name = Column(String(100))

  #Credenciales de redes sociales (desencriptar al usar)
  ig_username = Column(String(100), nullable=True)
  ig_password = Column(String(255), nullable=True)

  tk_username = Column(String(100), nullable=True)
  tk_password = Column(String(255), nullable=True)

  is_active = Column(Boolean, default=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now())