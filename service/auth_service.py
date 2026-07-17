"""
认证业务逻辑
"""
from datetime import datetime, timezone
from fastapi import HTTPException

from core.security import hash_password, check_password, gen_access_token, gen_refresh_token
from dao.user_dao import find_user_by_name, insert_user, store_refresh_token, find_refresh_token
from database.session import SessionLocal
from models.user import User
from models.refresh_token import RefreshToken
from schema.api import RegisterIn, LoginIn


def register(data: RegisterIn, db: SessionLocal):
    if find_user_by_name(data.username, db):
        raise HTTPException(status_code=400, detail="该用户名已被注册")
    new_user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        nickname=data.username,
        email=data.email,
        role="USER",
    )
    saved = insert_user(new_user, db)
    if not saved:
        raise HTTPException(status_code=500, detail="注册失败")
    return saved


def login(data: LoginIn, db: SessionLocal):
    user = find_user_by_name(data.username, db)
    if not user:
        raise HTTPException(status_code=400, detail="用户不存在")
    if not check_password(data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="密码不正确")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")

    return issue_tokens(user, db)


def issue_tokens(user: User, db: SessionLocal):
    """为已完成身份校验的用户签发并持久化访问令牌与刷新令牌。"""
    access = gen_access_token(user.username)
    refresh, expire_at = gen_refresh_token(user.username)
    record = RefreshToken(uid=user.id, token=refresh, expires_at=expire_at)
    if not store_refresh_token(record, db):
        raise HTTPException(status_code=500, detail="登录令牌保存失败")
    return access, refresh


def refresh_access(refresh_token_str: str, db: SessionLocal):
    record = find_refresh_token(refresh_token_str, db)
    if not record:
        raise HTTPException(status_code=400, detail="刷新令牌无效")
    if record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="刷新令牌已过期")
    user = db.query(User).filter(User.id == record.uid).first()
    if not user:
        raise HTTPException(status_code=400, detail="用户不存在")
    return gen_access_token(user.username)
