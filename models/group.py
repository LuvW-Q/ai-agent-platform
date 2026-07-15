"""
群组模型
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from database.session import Base


class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    owner_id = Column(Integer, nullable=False, index=True)
    avatar = Column(String(500), default="")
    announcement = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
