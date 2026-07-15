"""
敏感词管理模型
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from database.session import Base


class SensitiveWord(Base):
    __tablename__ = "sensitive_words"
    id = Column(Integer, primary_key=True, autoincrement=True)
    word = Column(String(100), nullable=False, index=True)  # 敏感词
    replacement = Column(String(100), default="***")         # 替换文本
    action = Column(String(20), default="replace")           # replace/block
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
