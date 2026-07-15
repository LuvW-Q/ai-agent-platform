"""
好友数据访问层
"""
from datetime import datetime, timezone
from sqlalchemy import or_, and_
from database.session import SessionLocal
from models.friendship import Friendship
from models.friend_request import FriendRequest
from models.user import User


def list_friends(user_id: int, db: SessionLocal) -> list[User]:
    """获取好友列表（返回User对象）"""
    friend_ids = db.query(Friendship.friend_id).filter(Friendship.user_id == user_id).all()
    ids = [f[0] for f in friend_ids]
    return db.query(User).filter(User.id.in_(ids)).all() if ids else []


def list_friend_requests(user_id: int, db: SessionLocal) -> list[FriendRequest]:
    """获取收到的待处理好友申请"""
    return db.query(FriendRequest).filter(
        FriendRequest.to_user_id == user_id,
        FriendRequest.status == "pending"
    ).order_by(FriendRequest.created_at.desc()).all()


def create_friend_request(from_id: int, to_id: int, message: str, db: SessionLocal) -> FriendRequest:
    """创建好友申请"""
    # 检查是否已是好友
    existing = db.query(Friendship).filter(
        or_(
            and_(Friendship.user_id == from_id, Friendship.friend_id == to_id),
            and_(Friendship.user_id == to_id, Friendship.friend_id == from_id),
        )
    ).first()
    if existing:
        return None  # 已是好友
    # 检查是否已有pending申请
    pending = db.query(FriendRequest).filter(
        FriendRequest.from_user_id == from_id,
        FriendRequest.to_user_id == to_id,
        FriendRequest.status == "pending"
    ).first()
    if pending:
        return pending  # 已申请过
    req = FriendRequest(from_user_id=from_id, to_user_id=to_id, message=message)
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


def accept_friend_request(req_id: int, user_id: int, db: SessionLocal) -> bool:
    """同意好友申请 — 双向创建好友关系"""
    req = db.query(FriendRequest).filter(
        FriendRequest.id == req_id,
        FriendRequest.to_user_id == user_id,
        FriendRequest.status == "pending"
    ).first()
    if not req:
        return False
    req.status = "accepted"
    req.responded_at = datetime.now(timezone.utc)
    # 双向好友关系
    db.add(Friendship(user_id=req.from_user_id, friend_id=req.to_user_id))
    db.add(Friendship(user_id=req.to_user_id, friend_id=req.from_user_id))
    db.commit()
    return True


def reject_friend_request(req_id: int, user_id: int, db: SessionLocal) -> bool:
    """拒绝好友申请"""
    req = db.query(FriendRequest).filter(
        FriendRequest.id == req_id,
        FriendRequest.to_user_id == user_id,
        FriendRequest.status == "pending"
    ).first()
    if not req:
        return False
    req.status = "rejected"
    req.responded_at = datetime.now(timezone.utc)
    db.commit()
    return True


def delete_friend(user_id: int, friend_id: int, db: SessionLocal) -> bool:
    """删除好友 — 双向移除"""
    db.query(Friendship).filter(
        or_(
            and_(Friendship.user_id == user_id, Friendship.friend_id == friend_id),
            and_(Friendship.user_id == friend_id, Friendship.friend_id == user_id),
        )
    ).delete()
    db.commit()
    return True


def search_users(keyword: str, exclude_id: int, db: SessionLocal) -> list[User]:
    """搜索用户（按用户名或昵称）"""
    return db.query(User).filter(
        User.id != exclude_id,
        or_(
            User.username.ilike(f"%{keyword}%"),
            User.nickname.ilike(f"%{keyword}%"),
        )
    ).limit(20).all()
