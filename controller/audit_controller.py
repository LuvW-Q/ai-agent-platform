"""
审计日志路由：支持按风险等级、事件类型筛选
"""
from fastapi import APIRouter, Depends, Query
from database.session import SessionLocal, get_db
from schema.api import AuditLogOut
from dao.base_dao import list_audit_logs
from core.security import get_current_user
from models.user import User
from models.audit_log import AuditLog

audit_router = APIRouter(prefix="/api/audit", tags=["审计管理"])


@audit_router.get("/logs", response_model=list[AuditLogOut])
def list_logs(
    risk_level: str = Query(None, description="按风险等级筛选: high/medium/low"),
    event_type: str = Query(None, description="按事件类型筛选（模糊匹配）"),
    limit: int = Query(100, ge=1, le=500),
    db: SessionLocal = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(AuditLog)
    if risk_level:
        q = q.filter(AuditLog.risk_level == risk_level)
    if event_type:
        q = q.filter(AuditLog.event_type.ilike(f"%{event_type}%"))
    return q.order_by(AuditLog.created_at.desc()).limit(limit).all()
