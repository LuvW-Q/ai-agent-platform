"""
大模型管理
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from database.session import Base


class AIModel(Base):
    __tablename__ = "ai_models"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)           # 显示名称
    provider = Column(String(50), default="openai")       # 提供商
    api_key = Column(String(500), nullable=False)         # API Key
    model_name = Column(String(100), nullable=False)      # 模型标识如 gpt-4o
    endpoint = Column(String(500), default="https://api.openai.com/v1")  # API地址
    context_length = Column(Integer, default=4096)        # 上下文长度
    model_type = Column(String(20), default="chat")       # chat/embedding/rerank
    is_default = Column(Boolean, default=False)           # 是否默认模型
    is_active = Column(Boolean, default=True)             # 是否启用
    temperature = Column(String(10), default="0.7")       # 温度参数
    max_tokens = Column(Integer, default=2048)            # 最大输出token
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
