"""
DE数字员工对话消息模型
持久化用户与数字员工的对话历史
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from database.session import Base


class DEMessage(Base):
    __tablename__ = "de_messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    session_id = Column(String(64), nullable=False, default="", index=True)
    role = Column(String(20), nullable=False)  # user/assistant/system
    content = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
