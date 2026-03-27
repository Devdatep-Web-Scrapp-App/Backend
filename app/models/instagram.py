from sqlalchemy import Column, String, DateTime, Integer, ForeignKey
from app.database import Base

# Estructuras adaptadas para soportar multi-tenant (app_user_id)
class InstagramFollowersSnapshot(Base):
    __tablename__ = "app_ig_followers_snapshot"

    app_user_id = Column(Integer, ForeignKey("app_users.id"), primary_key=True)
    username = Column(String(100), primary_key=True)
    full_name = Column(String(255))
    scraped_at = Column(DateTime)

class InstagramFollowersLost(Base):
    __tablename__ = "app_ig_followers_lost"

    app_user_id = Column(Integer, ForeignKey("app_users.id"), primary_key=True)
    username = Column(String(100), primary_key=True)
    full_name = Column(String(255))
    fecha_perdida = Column(DateTime, primary_key=True)