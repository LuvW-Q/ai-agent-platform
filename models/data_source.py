"""
数据源模型
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from database.session import Base


class DataSource(Base):
    __tablename__ = "data_sources"
    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_id = Column(String(100), nullable=False)  # 如 FinNews_Crawler_01
    name = Column(String(100), nullable=False)
    status = Column(String(20), default="idle")  # active/syncing/idle/error
    frequency = Column(String(50), default="")  # 如 5s/request
    endpoint = Column(String(255), default="")  # 如 api.market-intel.v3
    protocol = Column(String(50), default="http")  # http/psql/webhook/tls
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
