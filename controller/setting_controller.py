"""
系统设置路由：查询、更新系统设置，支持修改系统名称
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.engine import make_url
from database.session import SessionLocal, get_db
from core.security import get_current_user
from core.rbac import require_role
from core.crypto import encrypt
from dao.base_dao import log_action
from models.user import User
from models.setting import Setting
from models.ai_model import AIModel
from models.user_preference import UserPreference

setting_router = APIRouter(prefix="/api/settings", tags=["系统设置"])
PUBLIC_SETTING_KEYS = {"system_name", "face_recognition_enabled"}
PREFERENCE_DEFAULTS = {
    "notify_analysis": "true",
    "notify_critical": "true",
    "notify_login_alert": "true",
    "profile_public": "false",
    "allow_agent_access": "true",
}


class SettingUpdateIn(BaseModel):
    value: str = Field(..., max_length=1000)


class SettingOut(BaseModel):
    key: str
    value: str
    description: str
    is_configured: bool = False


SENSITIVE_SETTING_KEYS = {"database_url", "external_api_key"}
SETTING_DESCRIPTIONS = {
    "system_name": "系统名称",
    "database_url": "数据库连接（修改后重启生效）",
    "log_retention_days": "日志保留天数",
    "default_model_id": "默认模型ID",
    "sensitive_threshold": "敏感词匹配阈值",
    "voice_enabled": "语音播报开关",
    "face_recognition_enabled": "人脸识别开关",
    "collection_rate_limit": "采集频率限制(次/分钟)",
    "external_api_key": "外链 API 全局密钥",
    "site.title": "站点标题（兼容设置）",
    "notify_analysis": "分析进度更新通知",
    "notify_critical": "关键告警通知",
    "notify_login_alert": "登录安全异常通知",
    "profile_public": "公开工作动态",
    "allow_agent_access": "允许数字员工访问基础信息",
}


def _validated_value(key: str, value: str, db: SessionLocal) -> str:
    if key not in SETTING_DESCRIPTIONS:
        raise HTTPException(404, "未知的系统设置项")
    value = value.strip()
    if key in {"system_name", "site.title"}:
        if not value or len(value) > 60:
            raise HTTPException(400, "标题长度必须为 1 至 60 个字符")
    elif key in {
        "voice_enabled", "face_recognition_enabled", "notify_analysis",
        "notify_critical", "notify_login_alert", "profile_public", "allow_agent_access",
    }:
        normalized = value.lower()
        if normalized not in {"true", "false", "1", "0"}:
            raise HTTPException(400, "开关值必须为 true 或 false")
        value = "true" if normalized in {"true", "1"} else "false"
    elif key == "database_url":
        if not value:
            raise HTTPException(400, "数据库连接不能为空")
        try:
            url = make_url(value)
        except Exception as exc:
            raise HTTPException(400, "数据库连接格式无效") from exc
        if url.drivername not in {"sqlite", "mysql", "mysql+pymysql"}:
            raise HTTPException(400, "仅支持 SQLite 或 MySQL 数据库连接")
    elif key in {"log_retention_days", "collection_rate_limit"}:
        try:
            number = int(value)
        except ValueError as exc:
            raise HTTPException(400, "该设置必须为整数") from exc
        upper = 3650 if key == "log_retention_days" else 10000
        if not 1 <= number <= upper:
            raise HTTPException(400, f"该设置必须在 1 至 {upper} 之间")
        value = str(number)
    elif key == "sensitive_threshold":
        try:
            number = float(value)
        except ValueError as exc:
            raise HTTPException(400, "敏感词阈值必须为数字") from exc
        if not 0 <= number <= 1:
            raise HTTPException(400, "敏感词阈值必须在 0 至 1 之间")
        value = str(number)
    elif key == "default_model_id":
        try:
            model_id = int(value)
        except ValueError as exc:
            raise HTTPException(400, "默认模型 ID 必须为整数") from exc
        if db.query(AIModel).filter(AIModel.id == model_id, AIModel.is_active.is_(True)).first() is None:
            raise HTTPException(400, "默认模型不存在或未启用")
        value = str(model_id)
    elif key == "external_api_key" and len(value) > 500:
        raise HTTPException(400, "外链 API Key 不能超过 500 个字符")
    return value


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


@setting_router.get("/preferences", response_model=list[SettingOut])
def list_preferences(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    stored = {
        preference.key: preference.value
        for preference in db.query(UserPreference).filter(UserPreference.user_id == user.id).all()
    }
    return [
        SettingOut(
            key=key,
            value=stored.get(key, default),
            description=SETTING_DESCRIPTIONS[key],
            is_configured=key in stored,
        )
        for key, default in PREFERENCE_DEFAULTS.items()
    ]


@setting_router.put("/preferences/{key}", response_model=SettingOut)
def update_preference(key: str, body: SettingUpdateIn, db: SessionLocal = Depends(get_db),
                      user: User = Depends(get_current_user)):
    if key not in PREFERENCE_DEFAULTS:
        raise HTTPException(404, "未知的个人偏好项")
    value = _validated_value(key, body.value, db)
    preference = db.query(UserPreference).filter(
        UserPreference.user_id == user.id,
        UserPreference.key == key,
    ).first()
    if preference is None:
        preference = UserPreference(user_id=user.id, key=key, value=value)
        db.add(preference)
    else:
        preference.value = value
    db.commit()
    log_action("preference_update", f"更新个人偏好: {key}", user.username, db)
    return SettingOut(
        key=key,
        value=value,
        description=SETTING_DESCRIPTIONS[key],
        is_configured=True,
    )


@setting_router.put("/{key}", response_model=SettingOut)
def update_setting(key: str, body: SettingUpdateIn, db: SessionLocal = Depends(get_db),
                   user: User = Depends(require_role("ROOT"))):
    value = _validated_value(key, body.value, db)
    s = db.query(Setting).filter(Setting.key == key).first()
    if not s:
        stored_value = encrypt(value) if key in SENSITIVE_SETTING_KEYS else value
        s = Setting(key=key, value=stored_value, description=SETTING_DESCRIPTIONS[key])
        db.add(s)
    else:
        s.value = encrypt(value) if key in SENSITIVE_SETTING_KEYS else value
    db.commit()
    db.refresh(s)
    log_action("setting_update", f"更新系统设置: {key}", user.username, db)
    return _setting_out(s)


@setting_router.post("/system-name")
def set_system_name(body: SettingUpdateIn, db: SessionLocal = Depends(get_db),
                    user: User = Depends(require_role("ROOT"))):
    """修改系统名称，更新 settings 表"""
    value = _validated_value("system_name", body.value, db)
    s = db.query(Setting).filter(Setting.key == "system_name").first()
    if not s:
        s = Setting(key="system_name", value=value, description="系统名称")
        db.add(s)
    else:
        s.value = value
    db.commit()
    db.refresh(s)
    log_action("setting_update", "更新系统名称", user.username, db)
    return {"key": "system_name", "value": s.value}
