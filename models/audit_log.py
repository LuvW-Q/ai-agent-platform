"""
审计日志模型
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from database.session import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50), nullable=False)  # warning/notification/info
    risk_level = Column(String(20), default="low")  # high/medium/low
    description = Column(Text, nullable=False)
    operator = Column(String(50), default="system")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
