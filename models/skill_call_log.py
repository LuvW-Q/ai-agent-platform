"""
技能调用日志 — 用于熔断判定
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from database.session import Base


class SkillCallLog(Base):
    __tablename__ = "skill_call_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_id = Column(Integer, nullable=False, index=True)
    agent_id = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=True)
    success = Column(Boolean, default=False)
    error_msg = Column(Text, default="")
    duration_ms = Column(Integer, default=0)  # 调用耗时(毫秒)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
