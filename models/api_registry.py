"""
接口注册表模型：管理外部API接口配置与认证信息
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from database.session import Base


class ApiRegistry(Base):
    __tablename__ = "api_registries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), nullable=False, unique=True)
    base_url = Column(String(500), nullable=False)
    method = Column(String(10), default="GET")
    headers = Column(Text, default="{}")
    body_template = Column(Text, default="")
    response_path = Column(String(200), default="")
    auth_type = Column(String(20), default="query")
    auth_key = Column(String(200), default="")
    description = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
