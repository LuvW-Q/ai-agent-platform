"""
系统设置路由：查询、更新系统设置，支持修改系统名称
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from database.session import SessionLocal, get_db
from core.security import get_current_user
from models.user import User
from models.setting import Setting

setting_router = APIRouter(prefix="/api/settings", tags=["系统设置"])


class SettingUpdateIn(BaseModel):
    value: str


class SettingOut(BaseModel):
    key: str
    value: str
    description: str


@setting_router.get("", response_model=list[SettingOut])
def list_settings(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Setting).order_by(Setting.id).all()


@setting_router.put("/{key}", response_model=SettingOut)
def update_setting(key: str, body: SettingUpdateIn, db: SessionLocal = Depends(get_db),
                   user: User = Depends(get_current_user)):
    s = db.query(Setting).filter(Setting.key == key).first()
    if not s:
        s = Setting(key=key, value=body.value)
        db.add(s)
    else:
        s.value = body.value
    db.commit()
    db.refresh(s)
    return SettingOut(key=s.key, value=s.value, description=s.description)


@setting_router.post("/system-name")
def set_system_name(body: SettingUpdateIn, db: SessionLocal = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """修改系统名称，更新 settings 表"""
    s = db.query(Setting).filter(Setting.key == "system_name").first()
    if not s:
        s = Setting(key="system_name", value=body.value, description="系统名称")
        db.add(s)
    else:
        s.value = body.value
    db.commit()
    db.refresh(s)
    return {"key": "system_name", "value": s.value}
