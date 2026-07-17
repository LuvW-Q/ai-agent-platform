"""
数据仓库深度采集任务模型
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text
from database.session import Base


class CollectionTask(Base):
    """批量深度采集任务进度日志"""
    __tablename__ = "collection_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(String(200), default="")
    source_ids = Column(String(200), default="")     # 逗号分隔
    total_count = Column(Integer, default=0)
    completed_count = Column(Integer, default=0)
    status = Column(String(20), default="pending")   # pending/running/completed/failed
    log = Column(Text, default="")                    # 日志内容
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
