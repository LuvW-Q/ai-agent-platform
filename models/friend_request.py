"""
好友申请模型
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from database.session import Base


class FriendRequest(Base):
    __tablename__ = "friend_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    from_user_id = Column(Integer, nullable=False, index=True)
    to_user_id = Column(Integer, nullable=False, index=True)
    status = Column(String(20), default="pending")  # pending/accepted/rejected
    message = Column(String(200), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    responded_at = Column(DateTime, nullable=True)
