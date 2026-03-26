from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class FollowerBase(BaseModel):
    username: str
    full_name: Optional[str]

class FollowerSnapshot(FollowerBase):
    scraped_at: datetime
    class Config: from_attributes = True

class FollowerLost(FollowerBase):
    fecha_perdida: datetime
    class Config: from_attributes = True