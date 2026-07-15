"""
数字员工/Agent模型
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from database.session import Base


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    avatar = Column(String(500), default="")               # 头像URL
    base_model = Column(String(50), default="gpt-4o")      # 旧字段，保留兼容
    model_id = Column(Integer, nullable=True)              # 关联ai_models表
    persona_prompt = Column(Text, default="")              # 人设系统Prompt
    skill_bindings = Column(String(500), default="")       # 旧字段，逗号分隔技能名
    skill_ids = Column(String(500), default="")            # 逗号分隔的skill ID
    fallback_message = Column(String(500), default="系统繁忙，请稍后再试")  # 降级兜底话术
    status = Column(String(20), default="draft")           # draft/published
    description = Column(String(500), default="")
    # 接口型数字员工扩展：model=对话型, api=接口型(联动 api_registries)
    agent_type = Column(String(20), default="model")
    api_id = Column(Integer, nullable=True)                # 关联 api_registries 表
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
