"""
权限管理路由：角色CRUD + 用户角色分配 + 权限树
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from database.session import SessionLocal, get_db
from dao.base_dao import list_roles, log_action
from core.security import get_current_user
from core.rbac import require_role
from models.user import User
from models.role import Role
from models.menu import Menu
from models.permission import FunctionPoint, RoleFunctionPermission
from models.de_message import DEMessage
from models.friend_request import FriendRequest
from models.friendship import Friendship
from models.group import Group
from models.group_member import GroupMember
from models.message import Message
from models.refresh_token import RefreshToken
from models.skill_call_log import SkillCallLog
from models.user_preference import UserPreference
from sqlalchemy import or_
from pydantic import BaseModel, Field
from core.security import hash_password

permission_router = APIRouter(prefix="/api/permissions", tags=["权限管理"])
BUILTIN_ROLE_CODES = {"ROOT", "ADMIN", "AUDIT", "OPS", "USER", "GUEST"}


def _canonical_role_code(value: str | None) -> str:
    role_code = value or "USER"
    upper = role_code.upper()
    return upper if upper in BUILTIN_ROLE_CODES else role_code


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
def list_all_roles(db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT", "ADMIN"))):
    roles = list_roles(db)
    return [RoleOut(id=r.id, name=r.name, code=r.code, description=r.description, is_active=r.is_active) for r in roles]


@permission_router.post("/roles", status_code=201)
def create_role(body: RoleCreateIn, db: SessionLocal = Depends(get_db), user: User = Depends(require_role("ROOT", "ADMIN"))):
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
                user: User = Depends(require_role("ROOT", "ADMIN"))):
    r = db.query(Role).filter(Role.id == role_id).first()
    if not r:
        raise HTTPException(404, "角色不存在")
    if r.code in ("ROOT", "AUDIT", "OPS", "USER", "GUEST") and body.code not in (None, r.code):
        raise HTTPException(400, "系统内置角色代码不可修改")
    old_code = r.code
    if body.code is not None and body.code != old_code:
        if db.query(Role).filter(Role.code == body.code, Role.id != role_id).first():
            raise HTTPException(400, "角色代码已存在")
        db.query(RoleFunctionPermission).filter(
            RoleFunctionPermission.role_code == old_code
        ).update({"role_code": body.code})
    for k, v in body.model_dump().items():
        if v is not None:
            setattr(r, k, v)
    db.commit()
    db.refresh(r)
    log_action("role_update", f"更新角色: {r.name}({r.code})", user.username, db)
    return RoleOut(id=r.id, name=r.name, code=r.code, description=r.description, is_active=r.is_active)


@permission_router.delete("/roles/{role_id}")
def delete_role(role_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(require_role("ROOT", "ADMIN"))):
    r = db.query(Role).filter(Role.id == role_id).first()
    if not r:
        raise HTTPException(404, "角色不存在")
    if r.code in ("ROOT", "AUDIT", "OPS", "USER", "GUEST"):
        raise HTTPException(400, "系统内置角色不可删除")
    db.query(RoleFunctionPermission).filter(
        RoleFunctionPermission.role_code == r.code
    ).delete(synchronize_session=False)
    db.delete(r)
    db.commit()
    log_action("role_delete", f"删除角色: {r.name}", user.username, db)
    return {"deleted": True}


@permission_router.put("/user-role")
def assign_user_role(body: UserRoleIn, db: SessionLocal = Depends(get_db),
                     user: User = Depends(require_role("ROOT", "ADMIN"))):
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
def get_permission_tree(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """返回当前用户角色的权限树"""
    role_code = _canonical_role_code(user.role)
    bindings = (
        db.query(RoleFunctionPermission, FunctionPoint)
        .join(FunctionPoint, FunctionPoint.code == RoleFunctionPermission.function_code)
        .filter(
            RoleFunctionPermission.role_code == role_code,
            FunctionPoint.is_active == True,
        )
        .order_by(FunctionPoint.id)
        .all()
    )
    if bindings:
        modules = [{
            "name": function.name,
            "icon": "verified_user",
            "path": binding.resource,
            "permissions": [action.strip() for action in binding.actions.split(",") if action.strip()],
        } for binding, function in bindings]
        return {
            "role": role_code,
            "role_name": _get_role_name(role_code),
            "modules": modules,
            "total_nodes": sum(len(module["permissions"]) for module in modules),
            "api_coverage": 100,
            "menu_coverage": 100,
        }
    tree = PERM_TREE.get(role_code, PERM_TREE["USER"])
    return {"role": role_code, "role_name": _get_role_name(role_code), **tree}


# ===== 功能点与角色-功能-资源绑定 =====

class FunctionCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    code: str = Field(..., min_length=1, max_length=80)
    description: str = ""


class FunctionUpdateIn(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    code: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = None
    is_active: bool | None = None


class PermissionBindingIn(BaseModel):
    role_code: str = Field(..., min_length=1, max_length=50)
    function_code: str = Field(..., min_length=1, max_length=80)
    resource: str = Field(..., min_length=1, max_length=255)
    actions: str = Field("查看", min_length=1, max_length=255)


@permission_router.get("/functions")
def list_functions(db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT", "ADMIN"))):
    return [{
        "id": item.id,
        "name": item.name,
        "code": item.code,
        "description": item.description,
        "is_active": item.is_active,
    } for item in db.query(FunctionPoint).order_by(FunctionPoint.id).all()]


@permission_router.post("/functions", status_code=201)
def create_function(body: FunctionCreateIn, db: SessionLocal = Depends(get_db),
                    user: User = Depends(require_role("ROOT", "ADMIN"))):
    if db.query(FunctionPoint).filter(FunctionPoint.code == body.code).first():
        raise HTTPException(400, "功能代码已存在")
    item = FunctionPoint(name=body.name, code=body.code, description=body.description)
    db.add(item)
    db.commit()
    db.refresh(item)
    log_action("function_create", f"创建功能点: {item.name}({item.code})", user.username, db)
    return {"id": item.id, "name": item.name, "code": item.code,
            "description": item.description, "is_active": item.is_active}


@permission_router.put("/functions/{function_id}")
def update_function(function_id: int, body: FunctionUpdateIn, db: SessionLocal = Depends(get_db),
                    user: User = Depends(require_role("ROOT", "ADMIN"))):
    item = db.query(FunctionPoint).filter(FunctionPoint.id == function_id).first()
    if item is None:
        raise HTTPException(404, "功能点不存在")
    old_code = item.code
    if body.code is not None and body.code != old_code:
        if db.query(FunctionPoint).filter(FunctionPoint.code == body.code).first():
            raise HTTPException(400, "功能代码已存在")
        db.query(RoleFunctionPermission).filter(
            RoleFunctionPermission.function_code == old_code
        ).update({"function_code": body.code})
    for key, value in body.model_dump().items():
        if value is not None:
            setattr(item, key, value)
    db.commit()
    db.refresh(item)
    log_action("function_update", f"更新功能点: {item.name}({item.code})", user.username, db)
    return {"id": item.id, "name": item.name, "code": item.code,
            "description": item.description, "is_active": item.is_active}


@permission_router.delete("/functions/{function_id}")
def delete_function(function_id: int, db: SessionLocal = Depends(get_db),
                    user: User = Depends(require_role("ROOT", "ADMIN"))):
    item = db.query(FunctionPoint).filter(FunctionPoint.id == function_id).first()
    if item is None:
        raise HTTPException(404, "功能点不存在")
    db.query(RoleFunctionPermission).filter(
        RoleFunctionPermission.function_code == item.code
    ).delete(synchronize_session=False)
    name = item.name
    db.delete(item)
    db.commit()
    log_action("function_delete", f"删除功能点: {name}", user.username, db)
    return {"deleted": True}


@permission_router.get("/bindings")
def list_bindings(role_code: str | None = None, db: SessionLocal = Depends(get_db),
                  user: User = Depends(require_role("ROOT", "ADMIN"))):
    query = db.query(RoleFunctionPermission)
    if role_code is not None:
        query = query.filter(RoleFunctionPermission.role_code == role_code)
    return [{
        "id": item.id,
        "role_code": item.role_code,
        "function_code": item.function_code,
        "resource": item.resource,
        "actions": item.actions,
    } for item in query.order_by(RoleFunctionPermission.role_code, RoleFunctionPermission.id).all()]


def _validate_binding(body: PermissionBindingIn, db: SessionLocal):
    if db.query(Role).filter(Role.code == body.role_code).first() is None:
        raise HTTPException(400, "角色不存在")
    if db.query(FunctionPoint).filter(FunctionPoint.code == body.function_code).first() is None:
        raise HTTPException(400, "功能点不存在")


@permission_router.post("/bindings", status_code=201)
def create_binding(body: PermissionBindingIn, db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT", "ADMIN"))):
    _validate_binding(body, db)
    exists = db.query(RoleFunctionPermission).filter(
        RoleFunctionPermission.role_code == body.role_code,
        RoleFunctionPermission.function_code == body.function_code,
        RoleFunctionPermission.resource == body.resource,
    ).first()
    if exists:
        raise HTTPException(400, "该角色-功能-资源绑定已存在")
    item = RoleFunctionPermission(**body.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    log_action("permission_binding_create", f"创建权限绑定: {body.role_code}/{body.function_code}/{body.resource}", user.username, db)
    return {"id": item.id, **body.model_dump()}


@permission_router.put("/bindings/{binding_id}")
def update_binding(binding_id: int, body: PermissionBindingIn, db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT", "ADMIN"))):
    item = db.query(RoleFunctionPermission).filter(RoleFunctionPermission.id == binding_id).first()
    if item is None:
        raise HTTPException(404, "权限绑定不存在")
    _validate_binding(body, db)
    duplicate = db.query(RoleFunctionPermission).filter(
        RoleFunctionPermission.role_code == body.role_code,
        RoleFunctionPermission.function_code == body.function_code,
        RoleFunctionPermission.resource == body.resource,
        RoleFunctionPermission.id != binding_id,
    ).first()
    if duplicate:
        raise HTTPException(400, "该角色-功能-资源绑定已存在")
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    db.commit()
    log_action("permission_binding_update", f"更新权限绑定: {body.role_code}/{body.function_code}/{body.resource}", user.username, db)
    return {"id": item.id, **body.model_dump()}


@permission_router.delete("/bindings/{binding_id}")
def delete_binding(binding_id: int, db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT", "ADMIN"))):
    item = db.query(RoleFunctionPermission).filter(RoleFunctionPermission.id == binding_id).first()
    if item is None:
        raise HTTPException(404, "权限绑定不存在")
    description = f"{item.role_code}/{item.function_code}/{item.resource}"
    db.delete(item)
    db.commit()
    log_action("permission_binding_delete", f"删除权限绑定: {description}", user.username, db)
    return {"deleted": True}


def _get_role_name(code: str) -> str:
    names = {"ROOT": "超级管理员", "AUDIT": "安全审计员", "OPS": "运维工程师", "USER": "普通用户", "GUEST": "访客"}
    return names.get(code, code)


# ===== 菜单管理 =====

class MenuOut(BaseModel):
    id: int
    name: str
    icon: str
    path: str
    parent_id: int
    sort_order: int
    role_codes: str
    is_active: bool


class MenuCreateIn(BaseModel):
    name: str
    icon: str = ""
    path: str
    parent_id: int = 0
    sort_order: int = 0
    role_codes: str = ""


class MenuUpdateIn(BaseModel):
    name: str | None = None
    icon: str | None = None
    path: str | None = None
    parent_id: int | None = None
    sort_order: int | None = None
    role_codes: str | None = None
    is_active: bool | None = None


@permission_router.get("/menus")
def get_menus(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """返回当前用户可见的菜单列表"""
    role_code = _canonical_role_code(user.role)
    all_menus = db.query(Menu).filter(Menu.is_active == True).order_by(Menu.sort_order, Menu.id).all()
    # 过滤：role_codes 为空表示全部可见，否则检查是否包含用户角色
    visible = [
        m for m in all_menus
        if not m.role_codes or role_code in [c.strip() for c in m.role_codes.split(",")]
    ]
    return [MenuOut(id=m.id, name=m.name, icon=m.icon, path=m.path,
                    parent_id=m.parent_id, sort_order=m.sort_order,
                    role_codes=m.role_codes, is_active=m.is_active) for m in visible]


@permission_router.get("/menus/all", response_model=list[MenuOut])
def list_all_menus(db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT", "ADMIN"))):
    """管理侧：全部菜单列表"""
    all_menus = db.query(Menu).order_by(Menu.sort_order, Menu.id).all()
    return [MenuOut(id=m.id, name=m.name, icon=m.icon, path=m.path,
                    parent_id=m.parent_id, sort_order=m.sort_order,
                    role_codes=m.role_codes, is_active=m.is_active) for m in all_menus]


@permission_router.post("/menus", status_code=201)
def create_menu(body: MenuCreateIn, db: SessionLocal = Depends(get_db),
                user: User = Depends(require_role("ROOT", "ADMIN"))):
    m = Menu(name=body.name, icon=body.icon, path=body.path,
             parent_id=body.parent_id, sort_order=body.sort_order,
             role_codes=body.role_codes)
    db.add(m)
    db.commit()
    db.refresh(m)
    log_action("menu_create", f"创建菜单: {body.name}", user.username, db)
    return MenuOut(id=m.id, name=m.name, icon=m.icon, path=m.path,
                   parent_id=m.parent_id, sort_order=m.sort_order,
                   role_codes=m.role_codes, is_active=m.is_active)


@permission_router.put("/menus/{menu_id}")
def update_menu(menu_id: int, body: MenuUpdateIn, db: SessionLocal = Depends(get_db),
                user: User = Depends(require_role("ROOT", "ADMIN"))):
    m = db.query(Menu).filter(Menu.id == menu_id).first()
    if not m:
        raise HTTPException(404, "菜单不存在")
    for k, v in body.model_dump().items():
        if v is not None:
            setattr(m, k, v)
    db.commit()
    db.refresh(m)
    log_action("menu_update", f"更新菜单: {m.name}", user.username, db)
    return MenuOut(id=m.id, name=m.name, icon=m.icon, path=m.path,
                   parent_id=m.parent_id, sort_order=m.sort_order,
                   role_codes=m.role_codes, is_active=m.is_active)


@permission_router.delete("/menus/{menu_id}")
def delete_menu(menu_id: int, db: SessionLocal = Depends(get_db),
                user: User = Depends(require_role("ROOT", "ADMIN"))):
    m = db.query(Menu).filter(Menu.id == menu_id).first()
    if not m:
        raise HTTPException(404, "菜单不存在")
    db.delete(m)
    db.commit()
    log_action("menu_delete", f"删除菜单: {m.name}", user.username, db)
    return {"deleted": True}


# ===== 用户管理 =====

class UserCreateIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=72)
    nickname: str = Field(..., min_length=1, max_length=50)
    email: str = Field(..., min_length=1, max_length=255)
    role: str = Field("USER", min_length=1, max_length=50)


class UserUpdateIn(BaseModel):
    nickname: str | None = None
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None


@permission_router.post("/users", status_code=201)
def create_perm_user(body: UserCreateIn, db: SessionLocal = Depends(get_db),
                     user: User = Depends(require_role("ROOT", "ADMIN"))):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(400, "用户名已存在")
    if db.query(Role).filter(Role.code == body.role, Role.is_active == True).first() is None:
        raise HTTPException(400, "角色不存在或已停用")
    target = User(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname,
        email=body.email,
        role=body.role,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    log_action("user_create", f"管理员创建用户 {target.username}", user.username, db)
    return {
        "id": target.id, "username": target.username, "nickname": target.nickname,
        "email": target.email, "role": target.role, "is_active": target.is_active,
    }


@permission_router.get("/users")
def list_perm_users(search: str = Query(None, description="按用户名或昵称搜索"),
                   db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT", "ADMIN"))):
    """用户管理列表 — 支持按用户名/昵称搜索"""
    q = db.query(User)
    if search:
        q = q.filter((User.username.contains(search)) | (User.nickname.contains(search)))
    users = q.order_by(User.created_at.desc()).limit(100).all()
    return [{
        "id": u.id, "username": u.username, "nickname": u.nickname,
        "email": u.email, "role": u.role, "is_active": u.is_active,
        "avatar": u.avatar or "",
        "created_at": u.created_at.isoformat() if u.created_at else None,
    } for u in users]


@permission_router.put("/users/{user_id}")
def update_perm_user(user_id: int, body: UserUpdateIn, db: SessionLocal = Depends(get_db),
                     user: User = Depends(require_role("ROOT", "ADMIN"))):
    """更新用户基本信息（昵称、邮箱、角色、启停用）"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "用户不存在")
    # 保护：不允许通过此接口把超管停用或修改其角色（防止权限误操作）
    if (target.role or "").upper() == "ROOT" and body.is_active is False:
        raise HTTPException(400, "不能停用超级管理员")
    if (target.role or "").upper() == "ROOT" and body.role is not None and body.role.upper() != "ROOT":
        raise HTTPException(400, "不能修改超级管理员角色")
    if body.role is not None and db.query(Role).filter(
        Role.code == body.role,
        Role.is_active == True,
    ).first() is None:
        raise HTTPException(400, "角色不存在或已停用")
    for k, v in body.model_dump().items():
        if v is not None:
            setattr(target, k, v)
    db.commit()
    log_action("user_update", f"管理员更新用户 {target.username}", user.username, db)
    return {
        "id": target.id, "username": target.username,
        "nickname": target.nickname, "email": target.email,
        "role": target.role, "is_active": target.is_active,
    }


@permission_router.delete("/users/{user_id}")
def delete_perm_user(user_id: int, db: SessionLocal = Depends(get_db),
                     user: User = Depends(require_role("ROOT", "ADMIN"))):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        raise HTTPException(404, "用户不存在")
    if (target.role or "").upper() == "ROOT":
        raise HTTPException(400, "不能删除超级管理员")
    if target.id == user.id:
        raise HTTPException(400, "不能删除当前登录用户")
    username = target.username
    owned_group_ids = [row.id for row in db.query(Group.id).filter(Group.owner_id == target.id).all()]
    message_filter = or_(Message.sender_id == target.id, Message.receiver_id == target.id)
    if owned_group_ids:
        message_filter = or_(message_filter, Message.group_id.in_(owned_group_ids))
        db.query(GroupMember).filter(GroupMember.group_id.in_(owned_group_ids)).delete(
            synchronize_session=False
        )
        db.query(Group).filter(Group.id.in_(owned_group_ids)).delete(synchronize_session=False)
    db.query(Message).filter(message_filter).delete(synchronize_session=False)
    db.query(GroupMember).filter(GroupMember.user_id == target.id).delete(synchronize_session=False)
    db.query(Friendship).filter(or_(
        Friendship.user_id == target.id, Friendship.friend_id == target.id
    )).delete(synchronize_session=False)
    db.query(FriendRequest).filter(or_(
        FriendRequest.from_user_id == target.id, FriendRequest.to_user_id == target.id
    )).delete(synchronize_session=False)
    db.query(DEMessage).filter(DEMessage.user_id == target.id).delete(synchronize_session=False)
    db.query(RefreshToken).filter(RefreshToken.uid == target.id).delete(synchronize_session=False)
    db.query(UserPreference).filter(UserPreference.user_id == target.id).delete(synchronize_session=False)
    db.query(SkillCallLog).filter(SkillCallLog.user_id == target.id).update(
        {SkillCallLog.user_id: None}, synchronize_session=False
    )
    db.delete(target)
    db.commit()
    log_action("user_delete", f"管理员删除用户 {username}", user.username, db)
    return {"deleted": True}
