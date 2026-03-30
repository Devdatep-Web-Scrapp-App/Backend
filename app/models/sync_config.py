from sqlalchemy import Column, Integer, ForeignKey

from app.database import Base


class SyncConfig(Base):
    __tablename__ = "app_sync_config"

    app_user_id  = Column(Integer, ForeignKey("app_users.id"), primary_key=True)
    sync_hour    = Column(Integer, default=8)   # 0-23
    sync_minute  = Column(Integer, default=0)   # 0-59