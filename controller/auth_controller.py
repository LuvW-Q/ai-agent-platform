"""
认证路由：注册/登录/个人信息/刷新令牌/更新资料/头像上传
"""
from __future__ import annotations

import json
import math

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field, ValidationError, field_validator
from database.session import SessionLocal, get_db
from schema.api import RegisterIn, LoginIn, TokenOut, RefreshIn, UserOut
from service.auth_service import issue_tokens, login, refresh_access, register
from core.security import get_current_user
from core.crypto import decrypt, encrypt
from models.user import User
from models.setting import Setting
from dao.user_dao import find_user_by_name
from dao.base_dao import log_action
from core.upload_security import IMAGE_EXTENSIONS, save_validated_upload

auth_router = APIRouter(prefix="/api/auth", tags=["认证"])


class ProfileUpdateIn(BaseModel):
    nickname: str | None = None
    email: str | None = None
    signature: str | None = None
    avatar: str | None = None


class FaceDescriptorIn(BaseModel):
    descriptor: list[float]

    @field_validator("descriptor", mode="before")
    @classmethod
    def validate_descriptor_input(cls, value):
        if not isinstance(value, list) or len(value) != 128:
            raise ValueError("人脸特征必须是 128 维数组")
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value):
            raise ValueError("人脸特征只能包含数值")
        if any(not math.isfinite(float(item)) for item in value):
            raise ValueError("人脸特征不能包含非有限数值")
        return value


class FaceLoginIn(FaceDescriptorIn):
    username: str = Field(..., min_length=3, max_length=50)


def _require_face_recognition_enabled(db: SessionLocal) -> None:
    setting = db.query(Setting).filter(Setting.key == "face_recognition_enabled").first()
    if setting is not None and setting.value not in ("true", "1"):
        raise HTTPException(status_code=403, detail="人脸识别已关闭")


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


@auth_router.post("/face/register")
def register_face(body: FaceDescriptorIn, db: SessionLocal = Depends(get_db),
                  current: User = Depends(get_current_user)):
    """为当前已认证账号加密保存 128 维人脸特征。"""
    _require_face_recognition_enabled(db)
    descriptor_json = json.dumps(body.descriptor, ensure_ascii=False, separators=(",", ":"))
    current.face_descriptor = encrypt(descriptor_json)
    db.commit()
    log_action("face_register", f"用户注册人脸特征: {current.username}", current.username, db)
    return {"registered": True}


@auth_router.post("/face/login", response_model=TokenOut)
def login_with_face(body: FaceLoginIn, db: SessionLocal = Depends(get_db)):
    """比对人脸特征；欧氏距离严格小于 0.6 时签发登录令牌。"""
    _require_face_recognition_enabled(db)
    user = find_user_by_name(body.username, db)
    if user is None or not user.face_descriptor:
        log_action("face_login_failed", f"人脸登录失败: {body.username}", body.username, db)
        raise HTTPException(status_code=400, detail="该账号尚未注册人脸特征")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已停用")

    try:
        stored_value = json.loads(decrypt(user.face_descriptor) or "")
        stored_descriptor = FaceDescriptorIn(descriptor=stored_value).descriptor
    except (json.JSONDecodeError, TypeError, ValidationError):
        raise HTTPException(status_code=400, detail="已保存的人脸特征无效，请重新注册")

    distance = math.sqrt(sum(
        (saved - current) ** 2
        for saved, current in zip(stored_descriptor, body.descriptor)
    ))
    if distance >= 0.6:
        log_action("face_login_failed", f"人脸登录失败: {body.username}", body.username, db)
        raise HTTPException(status_code=401, detail="人脸验证失败")

    access, refresh = issue_tokens(user, db)
    log_action("face_login", f"用户人脸登录成功: {body.username}", body.username, db)
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
@auth_router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), db: SessionLocal = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """上传用户头像：分块限流并校验真实图片文件头。"""
    saved = await save_validated_upload(
        file,
        category=f"avatars/{user.id}",
        allowed_extensions=IMAGE_EXTENSIONS,
        max_size=5 * 1024 * 1024,
    )
    avatar_url = f"/api/uploads/{saved.relative_path}"
    # 更新用户头像
    me = db.query(User).filter(User.id == user.id).first()
    if me:
        me.avatar = avatar_url
        db.commit()
    return {"avatar": avatar_url, "filename": saved.original_name, "size": saved.size}
