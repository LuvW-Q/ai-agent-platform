"""
好友管理路由：搜索/申请/同意/拒绝/删除
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from database.session import SessionLocal, get_db
from schema.api import FriendRequestOut, FriendRequestIn, UserSearchOut
from dao.friend_dao import (
    list_friends, list_friend_requests, create_friend_request,
    accept_friend_request, reject_friend_request, delete_friend, search_users
)
from core.security import get_current_user
from core.ws_manager import ws_manager
from models.user import User
from datetime import datetime, timezone
import json, uuid

friend_router = APIRouter(prefix="/api/friends", tags=["好友管理"])


@friend_router.get("")
def get_friends(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """好友列表"""
    friends = list_friends(user.id, db)
    return [{"id": f.id, "username": f.username, "nickname": f.nickname, "avatar": f.avatar, "signature": f.signature, "is_online": ws_manager.is_online(f.id)} for f in friends]


@friend_router.get("/requests")
def get_requests(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """收到的好友申请列表"""
    reqs = list_friend_requests(user.id, db)
    result = []
    for r in reqs:
        sender = db.query(User).filter(User.id == r.from_user_id).first()
        result.append({
            "id": r.id, "from_user_id": r.from_user_id,
            "from_username": sender.username if sender else "",
            "from_nickname": sender.nickname if sender else "",
            "from_avatar": sender.avatar if sender else "",
            "message": r.message, "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return result


@friend_router.post("/requests")
async def send_request(body: FriendRequestIn, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """发送好友申请"""
    if body.to_user_id == user.id:
        raise HTTPException(400, "不能添加自己为好友")
    req = create_friend_request(user.id, body.to_user_id, body.message, db)
    if req is None:
        raise HTTPException(400, "已经是好友了")
    # WebSocket实时通知对方
    await ws_manager.send_to_user(body.to_user_id, {
        "msg_id": str(uuid.uuid4()),
        "msg_type": "friend_request",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "body": {"request_id": req.id, "from_user_id": user.id, "from_name": user.nickname, "message": body.message}
    })
    return {"id": req.id, "status": req.status}


@friend_router.post("/requests/{req_id}/accept")
async def accept_request(req_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """同意好友申请"""
    ok = accept_friend_request(req_id, user.id, db)
    if not ok:
        raise HTTPException(400, "申请不存在或已处理")
    # 找到对方
    from models.friend_request import FriendRequest as FRModel
    req = db.query(FRModel).filter(FRModel.id == req_id).first()
    if req:
        await ws_manager.send_to_user(req.from_user_id, {
            "msg_id": str(uuid.uuid4()),
            "msg_type": "friend_accepted",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "body": {"by_user_id": user.id, "by_name": user.nickname}
        })
    return {"accepted": True}


@friend_router.post("/requests/{req_id}/reject")
def reject_request(req_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """拒绝好友申请"""
    ok = reject_friend_request(req_id, user.id, db)
    if not ok:
        raise HTTPException(400, "申请不存在或已处理")
    return {"rejected": True}


@friend_router.delete("/{friend_id}")
def remove_friend(friend_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """删除好友 — 双向移除"""
    delete_friend(user.id, friend_id, db)
    return {"deleted": True}


@friend_router.get("/search")
def search(q: str = Query(..., min_length=1), db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """搜索用户"""
    users = search_users(q, user.id, db)
    return [{"id": u.id, "username": u.username, "nickname": u.nickname, "avatar": u.avatar, "signature": u.signature} for u in users]
