"""
认证路由：注册/登录/个人信息/刷新令牌/更新资料/头像上传
"""
from __future__ import annotations

import os, uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from schema.api import RegisterIn, LoginIn, TokenOut, RefreshIn, UserOut
from service.auth_service import register, login, refresh_access
from core.security import get_current_user
from models.user import User
from dao.base_dao import log_action

auth_router = APIRouter(prefix="/api/auth", tags=["认证"])


class ProfileUpdateIn(BaseModel):
    nickname: str | None = None
    email: str | None = None
    signature: str | None = None
    avatar: str | None = None


@auth_router.post("/register", response_model=UserOut)
def do_register(body: RegisterIn, db: SessionLocal = Depends(get_db)):
    user = register(body, db)
    log_action("register", f"新用户注册: {body.username}", body.username, db)
    return user


@auth_router.post("/login", response_model=TokenOut)
def do_login(body: LoginIn, db: SessionLocal = Depends(get_db)):
    try:
        access, refresh = login(body, db)
    except HTTPException:
        log_action("login_failed", f"登录失败: {body.username}", body.username, db)
        raise
    log_action("login", f"用户登录成功: {body.username}", body.username, db)
    return TokenOut(access_token=access, refresh_token=refresh)


@auth_router.get("/profile", response_model=UserOut)
def profile(current: User = Depends(get_current_user)):
    return current


@auth_router.put("/profile", response_model=UserOut)
def update_profile(body: ProfileUpdateIn, db: SessionLocal = Depends(get_db),
                   current: User = Depends(get_current_user)):
    """更新当前用户资料"""
    if body.nickname is not None:
        current.nickname = body.nickname
    if body.email is not None:
        current.email = body.email
    if body.signature is not None:
        current.signature = body.signature
    if body.avatar is not None:
        current.avatar = body.avatar
    db.commit()
    db.refresh(current)
    log_action("profile_update", f"用户更新个人资料: {current.username}", current.username, db)
    return current


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str


@auth_router.post("/change-password")
def change_password(body: PasswordChangeIn, db: SessionLocal = Depends(get_db),
                    current: User = Depends(get_current_user)):
    """修改当前用户密码"""
    from core.security import check_password, hash_password
    if not check_password(body.old_password, current.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度至少6位")
    current.password_hash = hash_password(body.new_password)
    db.commit()
    log_action("password_change", f"用户修改密码: {current.username}", current.username, db)
    return {"changed": True}


@auth_router.post("/refresh", response_model=TokenOut)
def do_refresh(body: RefreshIn, db: SessionLocal = Depends(get_db)):
    new_access = refresh_access(body.refresh_token, db)
    return TokenOut(access_token=new_access, refresh_token=body.refresh_token)


# ===== 头像上传 =====
AVATAR_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(AVATAR_DIR, exist_ok=True)
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@auth_router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    """上传用户头像 — 自动裁剪为200x200并更新当前用户"""
    ext = os.path.splitext(file.filename or ".png")[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise HTTPException(400, f"不支持的图片格式: {ext}，仅支持 jpg/png/gif/webp/bmp")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(400, "图片不能超过5MB")
    safe_name = f"avatar_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(AVATAR_DIR, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)
    avatar_url = f"/uploads/{safe_name}"
    # 更新用户头像
    db = next(get_db())
    try:
        me = db.query(User).filter(User.id == user.id).first()
        if me:
            me.avatar = avatar_url
            db.commit()
    finally:
        db.close()
    return {"avatar": avatar_url, "filename": file.filename, "size": len(content)}
