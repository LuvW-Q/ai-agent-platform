"""
智能审计：聊天消息敏感度评估 + 采集数据情感分析 + 封禁管理
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from database.session import SessionLocal, get_db
from core.security import get_current_user
from core.openai_client import OpenAIClient
from dao.model_dao import get_default_model
from dao.base_dao import log_action
from models.user import User
from models.message import Message
from models.group_member import GroupMember
from models.data_collection import CollectedData

smart_audit = APIRouter(prefix="/api/smart-audit", tags=["智能审计"])


@smart_audit.get("/messages")
def audit_messages(
    start: str = Query(None, description="开始时间 ISO"),
    end: str = Query(None, description="结束时间 ISO"),
    risk_level: str = Query(None, description="low/medium/high 筛选"),
    limit: int = Query(100, ge=1, le=1000),
    db: SessionLocal = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """审计聊天消息 — 基于关键词和规则的敏感度分级"""
    q = db.query(Message).filter(Message.msg_type == "text", Message.status != "recalled")
    if start:
        q = q.filter(Message.created_at >= datetime.fromisoformat(start))
    if end:
        q = q.filter(Message.created_at <= datetime.fromisoformat(end))
    if risk_level:
        q = q.filter(Message._risk == risk_level)

    msgs = q.order_by(Message.created_at.desc()).limit(limit).all()

    # 敏感词库（可从 sensitive_words 表读取，这里用内置规则）
    HIGH_RISK = {"密码", "身份证", "银行卡", "转账", "汇款", "裸聊", "赌博", "毒品", "fuck", "kill"}
    MEDIUM_RISK = {"私聊", "加微信", "QQ号", "手机号", "私下", "shit", "damn"}

    results = []
    for m in msgs:
        content = (m.content or "").lower()
        risk = "low"
        matched_words = []
        for w in HIGH_RISK:
            if w.lower() in content:
                risk = "high"
                matched_words.append(w)
        if risk != "high":
            for w in MEDIUM_RISK:
                if w.lower() in content:
                    risk = "medium"
                    matched_words.append(w)

        sender_name = ""
        if m.sender_id:
            s = db.query(User).filter(User.id == m.sender_id).first()
            sender_name = (s.nickname or s.username) if s else ""

        results.append({
            "id": m.id, "msg_id": m.msg_id,
            "sender_id": m.sender_id, "sender_name": sender_name,
            "receiver_id": m.receiver_id, "group_id": m.group_id,
            "content": content[:200],
            "risk_level": risk, "matched_words": matched_words,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
    return results


@smart_audit.get("/messages/stats")
def message_audit_stats(
    start: str = Query(None), end: str = Query(None),
    db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user),
):
    """消息审计统计"""
    q = db.query(Message).filter(Message.msg_type == "text", Message.status != "recalled")
    if start: q = q.filter(Message.created_at >= datetime.fromisoformat(start))
    if end: q = q.filter(Message.created_at <= datetime.fromisoformat(end))

    high = medium = low = 0
    HIGH_RISK = {"密码", "身份证", "银行卡", "转账", "汇款", "裸聊", "赌博", "毒品", "fuck", "kill"}
    MEDIUM_RISK = {"私聊", "加微信", "QQ号", "手机号", "私下", "shit", "damn"}

    for m in q.all():
        c = (m.content or "").lower()
        if any(w.lower() in c for w in HIGH_RISK):
            high += 1
        elif any(w.lower() in c for w in MEDIUM_RISK):
            medium += 1
        else:
            low += 1
    total = high + medium + low or 1
    return {
        "total": total, "high": high, "medium": medium, "low": low,
        "high_pct": round(high / total * 100, 1),
        "medium_pct": round(medium / total * 100, 1),
        "low_pct": round(low / total * 100, 1),
    }


@smart_audit.get("/data")
def audit_collected_data(
    start: str = Query(None), end: str = Query(None),
    sentiment: str = Query(None),
    db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user),
):
    """审计采集数据 — 情感分析"""
    q = db.query(CollectedData)
    if start: q = q.filter(CollectedData.created_at >= datetime.fromisoformat(start))
    if end: q = q.filter(CollectedData.created_at <= datetime.fromisoformat(end))
    if sentiment: q = q.filter(CollectedData.sentiment == sentiment)

    items = q.order_by(CollectedData.created_at.desc()).limit(100).all()
    return [{
        "id": d.id, "title": d.title, "source_name": d.source_name,
        "sentiment": d.sentiment,
        "summary": (d.summary or d.content or "")[:200],
        "keywords": d.keywords_extracted,
        "entities": d.entities,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in items]


@smart_audit.post("/data/{data_id}/mark-sentiment")
def mark_sentiment(data_id: int, sentiment: str = Query(...),
                   db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """手动标记采集数据的情感"""
    d = db.query(CollectedData).filter(CollectedData.id == data_id).first()
    if not d: raise HTTPException(404, "数据不存在")
    if sentiment not in ("positive", "neutral", "negative"):
        raise HTTPException(400, "情感值必须是 positive/neutral/negative")
    d.sentiment = sentiment
    db.commit()
    return {"id": d.id, "sentiment": d.sentiment}


# ============ 封禁管理 ============
@smart_audit.post("/ban/user/{user_id}")
def ban_user(user_id: int, reason: str = Query("违规消息"), db: SessionLocal = Depends(get_db),
             user: User = Depends(get_current_user)):
    """封禁用户"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target: raise HTTPException(404, "用户不存在")
    if target.role == "ROOT": raise HTTPException(400, "不能封禁超级管理员")
    target.is_active = False
    # 标记该用户所有消息为高风险
    db.query(Message).filter(Message.sender_id == user_id).update(
        {"status": "recalled"}, synchronize_session=False)
    db.commit()
    log_action("user_ban", f"封禁用户 {target.username}: {reason}", user.username, db, risk_level="high")
    return {"banned": True, "username": target.username}


@smart_audit.post("/ban/user/{user_id}/unban")
def unban_user(user_id: int, db: SessionLocal = Depends(get_db),
               user: User = Depends(get_current_user)):
    """解封用户"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target: raise HTTPException(404, "用户不存在")
    target.is_active = True
    db.commit()
    log_action("user_unban", f"解封用户 {target.username}", user.username, db)
    return {"unbanned": True, "username": target.username}


@smart_audit.post("/ban/group/{group_id}")
def ban_group(group_id: int, reason: str = Query("群内违规消息"),
              db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """封禁群聊（解散群 + 撤回所有消息）"""
    from models.group import Group
    g = db.query(Group).filter(Group.id == group_id).first()
    if not g: raise HTTPException(404, "群不存在")
    # 撤回所有群消息
    db.query(Message).filter(Message.group_id == group_id).update(
        {"status": "recalled"}, synchronize_session=False)
    # 移除所有成员
    db.query(GroupMember).filter(GroupMember.group_id == group_id).delete()
    db.delete(g)
    db.commit()
    log_action("group_ban", f"封禁并解散群 {g.name}: {reason}", user.username, db, risk_level="high")
    return {"banned": True, "group_name": g.name}


# ============ 用户管理 ============
@smart_audit.get("/users")
def list_users(search: str = Query(None), db: SessionLocal = Depends(get_db),
               user: User = Depends(get_current_user)):
    """列出所有用户"""
    q = db.query(User)
    if search:
        q = q.filter((User.username.contains(search)) | (User.nickname.contains(search)))
    users = q.order_by(User.created_at.desc()).limit(100).all()
    return [{
        "id": u.id, "username": u.username, "nickname": u.nickname,
        "email": u.email, "role": u.role, "is_active": u.is_active,
        "avatar": u.avatar or "", "signature": u.signature or "",
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "message_count": db.query(Message).filter(Message.sender_id == u.id).count(),
    } for u in users]
