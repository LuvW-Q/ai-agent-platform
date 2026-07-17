"""
群聊管理路由：建群/邀人/退群/解散/成员列表
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from core.security import get_current_user
from core.group_auth import require_group_manager, require_group_member, require_group_owner
from core.ws_manager import ws_manager
from models.user import User
from dao.group_dao import (
    create_group, list_user_groups, get_group, get_group_members,
    add_member, remove_member, dissolve_group, get_member_ids
)
from dao.base_dao import log_action
from datetime import datetime, timezone
import uuid

group_router = APIRouter(prefix="/api/groups", tags=["群聊管理"])


class GroupCreateIn(BaseModel):
    name: str
    member_ids: list[int] = []


class InviteIn(BaseModel):
    user_ids: list[int]


class GroupUpdateIn(BaseModel):
    name: str | None = None
    avatar: str | None = None
    announcement: str | None = None


@group_router.get("")
def my_groups(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """我加入的群列表"""
    return list_user_groups(user.id, db)


@group_router.put("/{group_id}")
def update_group(group_id: int, body: GroupUpdateIn, db: SessionLocal = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """更新群信息（名称、头像、公告）"""
    require_group_manager(group_id, user.id, db)
    g = get_group(group_id, db)
    if not g:
        raise HTTPException(404, "群不存在")
    if body.name is not None:
        g.name = body.name
    if body.avatar is not None:
        g.avatar = body.avatar
    if body.announcement is not None:
        g.announcement = body.announcement
    db.commit()
    db.refresh(g)
    return {"id": g.id, "name": g.name, "avatar": g.avatar or "", "announcement": g.announcement or ""}


@group_router.post("", status_code=201)
async def create(body: GroupCreateIn, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """创建群聊"""
    group = create_group(body.name, user.id, body.member_ids, db)
    log_action("group_create", f"创建群聊: {body.name}", user.username, db)
    # 通知被邀请的成员
    for uid in body.member_ids:
        if uid != user.id:
            await ws_manager.send_to_user(uid, {
                "msg_id": str(uuid.uuid4()),
                "msg_type": "group_invite",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "body": {"group_id": group.id, "group_name": group.name, "inviter": user.nickname}
            })
    return {"id": group.id, "name": group.name, "owner_id": group.owner_id}


@group_router.get("/{group_id}/members")
def members(group_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """群成员列表"""
    require_group_member(group_id, user.id, db)
    return get_group_members(group_id, db)


@group_router.post("/{group_id}/invite")
async def invite(group_id: int, body: InviteIn, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """邀请好友进群"""
    require_group_manager(group_id, user.id, db)
    added = []
    for uid in body.user_ids:
        if add_member(group_id, uid, db, "member"):
            added.append(uid)
            await ws_manager.send_to_user(uid, {
                "msg_id": str(uuid.uuid4()),
                "msg_type": "group_invite",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "body": {"group_id": group_id, "inviter": user.nickname}
            })
    return {"added": added}


@group_router.delete("/{group_id}/members/{user_id}")
def kick(group_id: int, user_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """踢人出群（仅群主/管理员）"""
    require_group_manager(group_id, user.id, db)
    if user_id == user.id:
        raise HTTPException(400, "不能踢出自己，请使用退出群聊")
    ok = remove_member(group_id, user_id, db)
    if not ok:
        raise HTTPException(400, "无法移除该成员")
    return {"removed": True}


@group_router.delete("/{group_id}/leave")
def leave(group_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """退出群聊"""
    require_group_member(group_id, user.id, db)
    ok = remove_member(group_id, user.id, db)
    if not ok:
        raise HTTPException(400, "无法退出（您可能是群主）")
    return {"left": True}


@group_router.delete("/{group_id}")
def dissolve(group_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """解散群聊（仅群主）"""
    require_group_owner(group_id, user.id, db)
    ok = dissolve_group(group_id, user.id, db)
    if not ok:
        raise HTTPException(400, "无权限或群不存在")
    log_action("group_dissolve", f"解散群聊 ID: {group_id}", user.username, db)
    return {"dissolved": True}
