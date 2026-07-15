"""
IM消息模型 — 支持WebSocket即时通信、消息幂等、撤回、文件传输
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from database.session import Base


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    msg_id = Column(String(64), unique=True, index=True, default="")  # UUID 幂等去重
    sender_id = Column(Integer, nullable=False, index=True)
    receiver_id = Column(Integer, nullable=True, index=True)  # 单聊
    group_id = Column(Integer, nullable=True, index=True)  # 群聊 (FK groups.id)
    content = Column(Text, nullable=False, default="")
    msg_type = Column(String(20), default="text")  # text/emoji/image/file/system
    status = Column(String(20), default="sent")  # sending/sent/delivered/read/failed/recalled
    is_read = Column(Boolean, default=False)
    file_url = Column(String(500), default="")
    file_name = Column(String(255), default="")
    file_size = Column(Integer, default=0)
    recall_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
