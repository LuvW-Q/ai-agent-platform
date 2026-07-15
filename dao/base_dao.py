"""
数据源、数字员工、消息、审计、角色的数据访问层
"""
from database.session import SessionLocal
from models.data_source import DataSource
from models.agent import Agent
from models.message import Message
from models.audit_log import AuditLog
from models.role import Role


# ===== 数据源 =====
def list_data_sources(db: SessionLocal):
    return db.query(DataSource).all()

def get_data_source(ds_id: int, db: SessionLocal):
    return db.query(DataSource).filter(DataSource.id == ds_id).first()

def create_data_source(ds: DataSource, db: SessionLocal):
    try:
        db.add(ds)
        db.commit()
        db.refresh(ds)
        return ds
    except Exception:
        db.rollback()
        return None

def delete_data_source(ds_id: int, db: SessionLocal):
    ds = get_data_source(ds_id, db)
    if ds:
        db.delete(ds)
        db.commit()
        return True
    return False


# ===== 数字员工 =====
def list_agents(db: SessionLocal):
    return db.query(Agent).all()

def get_agent(agent_id: int, db: SessionLocal):
    return db.query(Agent).filter(Agent.id == agent_id).first()

def create_agent(agent: Agent, db: SessionLocal):
    try:
        db.add(agent)
        db.commit()
        db.refresh(agent)
        return agent
    except Exception:
        db.rollback()
        return None


# ===== IM消息 =====
def list_messages(user_id: int, db: SessionLocal, limit: int = 50):
    return db.query(Message).filter(
        (Message.sender_id == user_id) | (Message.receiver_id == user_id)
    ).order_by(Message.created_at.desc()).limit(limit).all()

def create_message(msg: Message, db: SessionLocal):
    try:
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return msg
    except Exception:
        db.rollback()
        return None


# ===== 审计日志 =====
def list_audit_logs(db: SessionLocal, limit: int = 100):
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()

def create_audit_log(log: AuditLog, db: SessionLocal):
    try:
        db.add(log)
        db.commit()
        return log
    except Exception:
        db.rollback()
        return None

# 风险等级映射
_RISK_MAP = {
    "login": "medium", "logout": "low", "register": "low",
    "data_source_create": "low", "data_source_delete": "high",
    "agent_create": "low", "agent_publish": "medium",
    "agent_update": "low", "agent_delete": "medium",
    "profile_update": "low", "message_send": "low",
    "login_failed": "high", "auth_error": "high",
    "password_change": "high",
}

def log_action(event_type: str, description: str, operator: str, db: SessionLocal, risk_level: str = None):
    """便捷方法：创建审计日志记录"""
    if risk_level is None:
        risk_level = _RISK_MAP.get(event_type, "low")
    log = AuditLog(
        event_type=event_type,
        risk_level=risk_level,
        description=description,
        operator=operator,
    )
    return create_audit_log(log, db)


# ===== 角色 =====
def list_roles(db: SessionLocal):
    return db.query(Role).all()
