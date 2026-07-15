"""
安全模块：密码哈希、JWT签发与校验
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError
from fastapi import Header, HTTPException, Depends

from core.config import config
from database.session import get_db
from dao.user_dao import find_user_by_name


def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def check_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _build_token(username: str, token_type: str, expire_minutes: int):
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=expire_minutes)
    payload = {"sub": username, "type": token_type, "iat": now, "exp": expire}
    return jwt.encode(payload, config.SECRET_KEY, algorithm=config.ALGORITHM), expire


def gen_access_token(username: str):
    token, _ = _build_token(username, "access", config.ACCESS_TOKEN_EXPIRE)
    return token


def gen_refresh_token(username: str):
    return _build_token(username, "refresh", config.REFRESH_TOKEN_EXPIRE)


def extract_token(authorization: str | None = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少Authorization头")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authorization格式不正确")
    return parts[1]


def get_current_user(token: str = Depends(extract_token), db=Depends(get_db)):
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        username = payload.get("sub")
        t_type = payload.get("type")
        exp = payload.get("exp")
    except JWTError:
        raise HTTPException(status_code=401, detail="令牌解析失败")
    if t_type != "access":
        raise HTTPException(status_code=401, detail="令牌类型错误")
    if exp and exp < datetime.now(timezone.utc).timestamp():
        raise HTTPException(status_code=401, detail="访问令牌已过期")
    user = find_user_by_name(username, db)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user
