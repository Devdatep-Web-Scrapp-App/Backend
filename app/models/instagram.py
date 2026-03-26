from sqlalchemy import Column, String, DateTime
from app.database import Base

# Estructuras adaptadas para soportar multi-tenant (user_id)
class InstagramFollowersSnapshot(Base):
  __tablename__ = "instagram_followers_snapshot"

  username = Column(String(100), primary_key=True)
  full_name = Column(String(255))
  scraped_at = Column(DateTime)

class InstagramFollowersLost(Base):
  __tablename__ = "instagram_followers_lost"

  # Doble PK para mapeo
  username = Column(String(100), primary_key=True)
  full_name = Column(String(255))
  fecha_perdida = Column(DateTime, primary_key=True)