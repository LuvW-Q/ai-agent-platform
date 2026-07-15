"""
权限管理路由：角色CRUD + 用户角色分配 + 权限树
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from database.session import SessionLocal, get_db
from dao.base_dao import list_roles, log_action
from core.security import get_current_user
from models.user import User
from models.role import Role
from pydantic import BaseModel

permission_router = APIRouter(prefix="/api/permissions", tags=["权限管理"])


class RoleOut(BaseModel):
    id: int
    name: str
    code: str
    description: str
    is_active: bool


class RoleCreateIn(BaseModel):
    name: str
    code: str
    description: str = ""


class RoleUpdateIn(BaseModel):
    name: str | None = None
    code: str | None = None
    description: str | None = None
    is_active: bool | None = None


class UserRoleIn(BaseModel):
    user_id: int
    role_code: str


@permission_router.get("/roles", response_model=list[RoleOut])
def list_all_roles(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    roles = list_roles(db)
    return [RoleOut(id=r.id, name=r.name, code=r.code, description=r.description, is_active=r.is_active) for r in roles]


@permission_router.post("/roles", status_code=201)
def create_role(body: RoleCreateIn, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    if db.query(Role).filter(Role.code == body.code).first():
        raise HTTPException(400, "角色代码已存在")
    r = Role(name=body.name, code=body.code, description=body.description)
    db.add(r)
    db.commit()
    db.refresh(r)
    log_action("role_create", f"创建角色: {body.name}({body.code})", user.username, db)
    return RoleOut(id=r.id, name=r.name, code=r.code, description=r.description, is_active=r.is_active)


@permission_router.put("/roles/{role_id}")
def update_role(role_id: int, body: RoleUpdateIn, db: SessionLocal = Depends(get_db),
                user: User = Depends(get_current_user)):
    r = db.query(Role).filter(Role.id == role_id).first()
    if not r:
        raise HTTPException(404, "角色不存在")
    for k, v in body.model_dump().items():
        if v is not None:
            setattr(r, k, v)
    db.commit()
    db.refresh(r)
    return RoleOut(id=r.id, name=r.name, code=r.code, description=r.description, is_active=r.is_active)


@permission_router.delete("/roles/{role_id}")
def delete_role(role_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    r = db.query(Role).filter(Role.id == role_id).first()
    if not r:
        raise HTTPException(404, "角色不存在")
    if r.code in ("ROOT", "AUDIT", "OPS", "USER", "GUEST"):
        raise HTTPException(400, "系统内置角色不可删除")
    db.delete(r)
    db.commit()
    log_action("role_delete", f"删除角色: {r.name}", user.username, db)
    return {"deleted": True}


@permission_router.put("/user-role")
def assign_user_role(body: UserRoleIn, db: SessionLocal = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """分配（修改）用户的角色"""
    target = db.query(User).filter(User.id == body.user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")
    role = db.query(Role).filter(Role.code == body.role_code).first()
    if not role:
        raise HTTPException(400, "角色不存在")
    target.role = body.role_code
    db.commit()
    log_action("user_role_change", f"将用户 {target.username} 角色改为 {body.role_code}", user.username, db)
    return {"user_id": target.id, "username": target.username, "role": target.role}


# 权限树（基于角色code返回）
PERM_TREE = {
    "ROOT": {
        "modules": [
            {"name": "数据治理", "icon": "database", "path": "/dashboard", "permissions": ["查看", "编辑", "删除"]},
            {"name": "数字大屏", "icon": "monitoring", "path": "/screen", "permissions": ["查看"]},
            {"name": "员工编排", "icon": "precision_manufacturing", "path": "/agents", "permissions": ["查看", "创建", "发布"]},
            {"name": "权限管理", "icon": "admin_panel_settings", "path": "/permissions", "permissions": ["查看", "编辑"]},
            {"name": "审计管理", "icon": "security", "path": "/audit", "permissions": ["查看", "导出"]},
            {"name": "IM控制台", "icon": "forum", "path": "/im", "permissions": ["查看", "发送"]},
            {"name": "智能问数", "icon": "query_stats", "path": "/query", "permissions": ["查看"]},
            {"name": "模型管理", "icon": "psychology", "path": "/models", "permissions": ["查看", "编辑"]},
            {"name": "技能管理", "icon": "build", "path": "/skills", "permissions": ["查看", "编辑"]},
            {"name": "数字员工管理", "icon": "smart_toy", "path": "/agent-management", "permissions": ["查看", "编辑"]},
            {"name": "个人设置", "icon": "settings", "path": "/settings", "permissions": ["查看", "编辑"]},
        ],
        "total_nodes": 42,
        "api_coverage": 100,
        "menu_coverage": 100,
    },
    "AUDIT": {
        "modules": [
            {"name": "数字大屏", "icon": "monitoring", "path": "/screen", "permissions": ["查看"]},
            {"name": "审计管理", "icon": "security", "path": "/audit", "permissions": ["查看", "导出"]},
            {"name": "个人设置", "icon": "settings", "path": "/settings", "permissions": ["查看", "编辑"]},
        ],
        "total_nodes": 12, "api_coverage": 85, "menu_coverage": 60,
    },
    "OPS": {
        "modules": [
            {"name": "数据治理", "icon": "database", "path": "/dashboard", "permissions": ["查看", "编辑"]},
            {"name": "数字大屏", "icon": "monitoring", "path": "/screen", "permissions": ["查看"]},
            {"name": "智能问数", "icon": "query_stats", "path": "/query", "permissions": ["查看"]},
            {"name": "个人设置", "icon": "settings", "path": "/settings", "permissions": ["查看", "编辑"]},
        ],
        "total_nodes": 18, "api_coverage": 75, "menu_coverage": 65,
    },
    "USER": {
        "modules": [
            {"name": "数字大屏", "icon": "monitoring", "path": "/screen", "permissions": ["查看"]},
            {"name": "IM控制台", "icon": "forum", "path": "/im", "permissions": ["查看", "发送"]},
            {"name": "个人设置", "icon": "settings", "path": "/settings", "permissions": ["查看", "编辑"]},
        ],
        "total_nodes": 10, "api_coverage": 60, "menu_coverage": 40,
    },
    "GUEST": {
        "modules": [{"name": "数字大屏", "icon": "monitoring", "path": "/screen", "permissions": ["查看"]}],
        "total_nodes": 4, "api_coverage": 30, "menu_coverage": 20,
    },
}


@permission_router.get("/tree")
def get_permission_tree(user: User = Depends(get_current_user)):
    """返回当前用户角色的权限树"""
    role_code = user.role or "USER"
    tree = PERM_TREE.get(role_code, PERM_TREE["USER"])
    return {"role": role_code, "role_name": _get_role_name(role_code), **tree}


def _get_role_name(code: str) -> str:
    names = {"ROOT": "超级管理员", "AUDIT": "安全审计员", "OPS": "运维工程师", "USER": "普通用户", "GUEST": "访客"}
    return names.get(code, code)
