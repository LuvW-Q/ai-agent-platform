"""
系统设置：键值对存储，支持系统名称、阈值、开关等通用配置
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from database.session import Base


class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String(500), default="")
    description = Column(String(200), default="")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
