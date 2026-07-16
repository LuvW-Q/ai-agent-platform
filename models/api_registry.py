"""
接口注册表模型：管理外部API接口配置与认证信息
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.ext.hybrid import hybrid_property
from database.session import Base
from core.crypto import encrypt, decrypt


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
    # auth_key 在 DB 中存储为 Fernet 密文；hybrid_property 自动加解密
    auth_key_cipher = Column("auth_key", String(200), default="")
    description = Column(String(500), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    @hybrid_property
    def auth_key(self):
        """自动解密存储的 auth_key_cipher。"""
        return decrypt(self.auth_key_cipher)

    @auth_key.setter
    def auth_key(self, value):
        """写入时自动加密。"""
        self.auth_key_cipher = encrypt(value)
