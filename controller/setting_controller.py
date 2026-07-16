"""
系统设置路由：查询、更新系统设置，支持修改系统名称
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from core.security import get_current_user
from core.rbac import require_role
from core.crypto import encrypt
from dao.base_dao import log_action
from models.user import User
from models.setting import Setting

setting_router = APIRouter(prefix="/api/settings", tags=["系统设置"])
PUBLIC_SETTING_KEYS = {"system_name", "face_recognition_enabled"}


class SettingUpdateIn(BaseModel):
    value: str


class SettingOut(BaseModel):
    key: str
    value: str
    description: str
    is_configured: bool = False


SENSITIVE_SETTING_KEYS = {"database_url", "external_api_key"}


def _setting_out(setting: Setting) -> SettingOut:
    sensitive = setting.key in SENSITIVE_SETTING_KEYS
    return SettingOut(
        key=setting.key,
        value="" if sensitive else setting.value,
        description=setting.description,
        is_configured=bool(setting.value),
    )


@setting_router.get("/public", response_model=list[SettingOut])
def public_settings(db: SessionLocal = Depends(get_db)):
    """登录前可读取的非敏感展示与功能开关。"""
    settings = db.query(Setting).filter(Setting.key.in_(PUBLIC_SETTING_KEYS)).order_by(Setting.id).all()
    return [_setting_out(setting) for setting in settings]


@setting_router.get("", response_model=list[SettingOut])
def list_settings(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    return [_setting_out(setting) for setting in db.query(Setting).order_by(Setting.id).all()]


@setting_router.put("/{key}", response_model=SettingOut)
def update_setting(key: str, body: SettingUpdateIn, db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT"))):
    s = db.query(Setting).filter(Setting.key == key).first()
    if not s:
        stored_value = encrypt(body.value) if key in SENSITIVE_SETTING_KEYS else body.value
        s = Setting(key=key, value=stored_value)
        db.add(s)
    else:
        s.value = encrypt(body.value) if key in SENSITIVE_SETTING_KEYS else body.value
    db.commit()
    db.refresh(s)
    log_action("setting_update", f"更新系统设置: {key}", user.username, db)
    return _setting_out(s)


@setting_router.post("/system-name")
def set_system_name(body: SettingUpdateIn, db: SessionLocal = Depends(get_db),
                    user: User = Depends(require_role("ROOT"))):
    """修改系统名称，更新 settings 表"""
    s = db.query(Setting).filter(Setting.key == "system_name").first()
    if not s:
        s = Setting(key="system_name", value=body.value, description="系统名称")
        db.add(s)
    else:
        s.value = body.value
    db.commit()
    db.refresh(s)
    log_action("setting_update", "更新系统名称", user.username, db)
    return {"key": "system_name", "value": s.value}
