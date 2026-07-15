"""
群组数据访问层
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import or_
from database.session import SessionLocal
from models.group import Group
from models.group_member import GroupMember
from models.user import User


def create_group(name: str, owner_id: int, member_ids: list[int], db: SessionLocal) -> Group:
    """创建群聊，owner自动成为群主，同时加入成员"""
    group = Group(name=name, owner_id=owner_id)
    db.add(group)
    db.flush()
    # 群主
    db.add(GroupMember(group_id=group.id, user_id=owner_id, role="owner"))
    # 其他成员
    for uid in member_ids:
        if uid != owner_id:
            db.add(GroupMember(group_id=group.id, user_id=uid, role="member"))
    db.commit()
    db.refresh(group)
    return group


def list_user_groups(user_id: int, db: SessionLocal) -> list[dict]:
    """获取用户加入的所有群"""
    member_rows = db.query(GroupMember).filter(GroupMember.user_id == user_id).all()
    group_ids = [m.group_id for m in member_rows]
    if not group_ids:
        return []
    groups = db.query(Group).filter(Group.id.in_(group_ids)).all()
    result = []
    for g in groups:
        member_count = db.query(GroupMember).filter(GroupMember.group_id == g.id).count()
        my_role = next((m.role for m in member_rows if m.group_id == g.id), "member")
        result.append({
            "id": g.id, "name": g.name, "owner_id": g.owner_id,
            "avatar": g.avatar, "announcement": g.announcement,
            "member_count": member_count, "my_role": my_role,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        })
    return result


def get_group(group_id: int, db: SessionLocal) -> Group | None:
    return db.query(Group).filter(Group.id == group_id).first()


def get_group_members(group_id: int, db: SessionLocal) -> list[dict]:
    """获取群成员列表"""
    rows = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    user_ids = [r.user_id for r in rows]
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    user_map = {u.id: u for u in users}
    return [{
        "user_id": r.user_id,
        "username": user_map[r.user_id].username if r.user_id in user_map else "",
        "nickname": user_map[r.user_id].nickname if r.user_id in user_map else "",
        "avatar": user_map[r.user_id].avatar if r.user_id in user_map else "",
        "role": r.role,
        "joined_at": r.joined_at.isoformat() if r.joined_at else None,
    } for r in rows]


def add_member(group_id: int, user_id: int, db: SessionLocal, role: str = "member") -> bool:
    existing = db.query(GroupMember).filter(
        GroupMember.group_id == group_id, GroupMember.user_id == user_id
    ).first()
    if existing:
        return False
    db.add(GroupMember(group_id=group_id, user_id=user_id, role=role))
    db.commit()
    return True


def remove_member(group_id: int, user_id: int, db: SessionLocal) -> bool:
    row = db.query(GroupMember).filter(
        GroupMember.group_id == group_id, GroupMember.user_id == user_id
    ).first()
    if not row or row.role == "owner":
        return False
    db.delete(row)
    db.commit()
    return True


def dissolve_group(group_id: int, owner_id: int, db: SessionLocal) -> bool:
    group = db.query(Group).filter(Group.id == group_id, Group.owner_id == owner_id).first()
    if not group:
        return False
    db.query(GroupMember).filter(GroupMember.group_id == group_id).delete()
    db.delete(group)
    db.commit()
    return True


def get_member_ids(group_id: int, db: SessionLocal) -> list[int]:
    rows = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
    return [r.user_id for r in rows]
