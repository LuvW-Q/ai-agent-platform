"""群聊对象级授权辅助函数。"""
from __future__ import annotations

from fastapi import HTTPException

from models.group import Group
from models.group_member import GroupMember


def require_group_member(group_id: int, user_id: int, db) -> GroupMember:
    group = db.query(Group).filter(Group.id == group_id).first()
    if not group:
        raise HTTPException(404, "群不存在")
    membership = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id,
    ).first()
    if not membership:
        raise HTTPException(403, "无权访问该群")
    return membership


def require_group_manager(group_id: int, user_id: int, db) -> GroupMember:
    membership = require_group_member(group_id, user_id, db)
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(403, "仅群主或管理员可执行该操作")
    return membership


def require_group_owner(group_id: int, user_id: int, db) -> GroupMember:
    membership = require_group_member(group_id, user_id, db)
    if membership.role != "owner":
        raise HTTPException(403, "仅群主可执行该操作")
    return membership
