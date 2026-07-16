"""
智能审计：聊天消息敏感度评估 + 采集数据情感分析 + 封禁管理
"""
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from database.session import SessionLocal, get_db
from core.security import get_current_user
from core.rbac import require_role
from core.openai_client import OpenAIClient
from core.sensitive_filter import sensitive_filter
from dao.model_dao import get_default_model
from dao.base_dao import log_action
from models.user import User
from models.message import Message
from models.group_member import GroupMember
from models.data_collection import CollectedData

smart_audit = APIRouter(prefix="/api/smart-audit", tags=["智能审计"])


def _classify_risk(content: str, db) -> tuple[str, list[str]]:
    """根据 SensitiveFilter 单例对消息内容进行风险分级（数据库驱动）

    映射:
      - action="block" 命中 → high
      - action="replace" 命中（filtered != content）→ medium
      - 无命中 → low
    """
    if not content:
        return ("low", [])
    filtered, blocked = sensitive_filter.filter(content, db)
    if blocked:
        return ("high", [])
    if filtered != content:
        # 至少有一个 replace 类敏感词被替换
        return ("medium", ["***"])
    return ("low", [])


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

    results = []
    for m in msgs:
        content = m.content or ""
        # 风险分级委托给 SensitiveFilter（数据库 sensitive_words 表）
        risk, matched_words = _classify_risk(content, db)

        sender_name = ""
        if m.sender_id:
            s = db.query(User).filter(User.id == m.sender_id).first()
            sender_name = (s.nickname or s.username) if s else ""

        results.append({
            "id": m.id, "msg_id": m.msg_id,
            "sender_id": m.sender_id, "sender_name": sender_name,
            "receiver_id": m.receiver_id, "group_id": m.group_id,
            "content": content.lower()[:200],
            "risk_level": risk, "matched_words": matched_words,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
    return results


@smart_audit.get("/messages/stats")
def message_audit_stats(
    start: str = Query(None), end: str = Query(None),
    db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user),
):
    """消息审计统计 — SQL CASE WHEN 单次聚合，避免 Python 循环 _classify_risk

    逻辑等价于逐条调用 _classify_risk：
      - action="block" 命中 → high
      - action="replace" 命中 → medium
      - 无命中 → low

    实现策略：从 sensitive_filter 单例缓存读取敏感词列表，构造 SQLAlchemy
    `case()` + `func.instr(func.lower(...))` 表达式，在 SQL 端一次性 GROUP BY
    聚合，避免把全部消息加载到 Python 后逐条分类。
    """
    from sqlalchemy import case, func

    # 公共过滤条件
    base_filters = [
        Message.msg_type == "text",
        Message.status != "recalled",
    ]
    if start:
        base_filters.append(Message.created_at >= datetime.fromisoformat(start))
    if end:
        base_filters.append(Message.created_at <= datetime.fromisoformat(end))

    # 加载敏感词（_ensure_cache 自带 60s 内存缓存）
    words = sensitive_filter._ensure_cache(db)
    block_words = [w["word"] for w in words if w.get("action") == "block"]
    replace_words = [w["word"] for w in words if w.get("action") == "replace"]

    # 边界场景：没有任何敏感词时，全部记为 low
    if not block_words and not replace_words:
        total = db.query(func.count(Message.id)).filter(*base_filters).scalar() or 0
        return {
            "total": total, "high": 0, "medium": 0, "low": total,
            "high_pct": 0.0, "medium_pct": 0.0,
            "low_pct": 100.0 if total else 0.0,
        }

    # 构造 CASE WHEN 表达式：block 词优先于 replace 词，命中即分到高/中档
    lower_content = func.lower(Message.content)
    whens = []
    for w in block_words:
        whens.append((func.instr(lower_content, w.lower()) > 0, "high"))
    for w in replace_words:
        whens.append((func.instr(lower_content, w.lower()) > 0, "medium"))
    case_expr = case(*whens, else_="low")

    stats_q = db.query(
        case_expr.label("risk_level"),
        func.count(Message.id).label("cnt"),
    ).filter(*base_filters).group_by(case_expr.label("risk_level"))

    rows = stats_q.all()

    counts = {"high": 0, "medium": 0, "low": 0}
    for r in rows:
        # SQLite 在无命中时 risk_level 可能为 NULL → 归到 low
        level = r.risk_level if r.risk_level in counts else "low"
        counts[level] = r.cnt

    total = counts["high"] + counts["medium"] + counts["low"]
    base = total or 1
    return {
        "total": total,
        "high": counts["high"],
        "medium": counts["medium"],
        "low": counts["low"],
        "high_pct": round(counts["high"] / base * 100, 1),
        "medium_pct": round(counts["medium"] / base * 100, 1),
        "low_pct": round(counts["low"] / base * 100, 1),
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
                   db: SessionLocal = Depends(get_db), user: User = Depends(require_role("ROOT", "ADMIN"))):
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
             user: User = Depends(require_role("ROOT", "ADMIN"))):
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
               user: User = Depends(require_role("ROOT", "ADMIN"))):
    """解封用户"""
    target = db.query(User).filter(User.id == user_id).first()
    if not target: raise HTTPException(404, "用户不存在")
    target.is_active = True
    db.commit()
    log_action("user_unban", f"解封用户 {target.username}", user.username, db)
    return {"unbanned": True, "username": target.username}


@smart_audit.post("/ban/group/{group_id}")
def ban_group(group_id: int, reason: str = Query("群内违规消息"),
              db: SessionLocal = Depends(get_db), user: User = Depends(require_role("ROOT", "ADMIN"))):
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


# ============ AI 风险分析 ============
@smart_audit.post("/ai-analyze")
async def ai_risk_analyze(
    conversation_id: str = Query("", description="会话标识(以 sender_id 解析最近消息)"),
    data_id: int = Query(None, description="采集数据ID"),
    db: SessionLocal = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """将当前会话或采集数据送 LLM 做风险分析

    优先使用 data_id 取采集数据；否则用 conversation_id(映射到 sender_id)
    拉取最近 20 条消息。无 API Key 或无内容时优雅返回,不报错。
    """
    chat_model = get_default_model(db)
    if not chat_model or not chat_model.api_key or "placeholder" in (chat_model.api_key or ""):
        return {"risk_level": "unknown", "risk_types": [],
                "analysis": "无法执行 AI 分析:未配置有效的 API Key",
                "suggestions": "请在系统设置中配置有效的模型 API Key"}

    content = ""
    if data_id:
        d = db.query(CollectedData).filter(CollectedData.id == data_id).first()
        if d:
            content = (d.title or "") + "\n" + (d.content or "")[:3000]
    elif conversation_id:
        try:
            sid = int(conversation_id)
        except (TypeError, ValueError):
            sid = None
        if sid is not None:
            msgs = (db.query(Message)
                    .filter(Message.sender_id == sid,
                            Message.msg_type == "text",
                            Message.status != "recalled")
                    .order_by(Message.created_at.desc()).limit(20).all())
            content = "\n".join(m.content for m in msgs if m.content)[:4000]

    if not content:
        # 优雅返回而非 400,便于大屏调用方统一展示
        return {"risk_level": "unknown", "risk_types": [],
                "analysis": "无可分析的内容(请提供有效的 data_id 或 conversation_id)",
                "suggestions": ""}

    client = OpenAIClient(
        api_key=chat_model.api_key,
        endpoint=chat_model.endpoint,
        model_name=chat_model.model_name,
        temperature=0.3,
        max_tokens=1024,
    )
    try:
        prompt = f"""请对以下内容进行安全风险分析,以JSON格式返回:
{{
  "risk_level": "high/medium/low",
  "risk_types": ["涉政", "涉黄", "涉恐", "暴恐", "广告", "正常"],
  "analysis": "分析结论(100字以内)",
  "suggestions": "建议措施"
}}
内容:{content[:4000]}"""
        resp = await client.chat_completion([{"role": "user", "content": prompt}])
        text = OpenAIClient.extract_content(resp) or ""
        try:
            result = json.loads(text.strip().strip("`").strip("json").strip())
        except Exception:
            result = {
                "risk_level": "unknown",
                "risk_types": [],
                "analysis": text[:200] or "(模型返回为空)",
                "suggestions": "",
            }
        return result
    except Exception as e:
        return {"risk_level": "unknown", "risk_types": [],
                "analysis": f"AI 分析失败:{type(e).__name__}: {str(e)[:150]}",
                "suggestions": "请稍后重试或检查模型配置"}
    finally:
        await client.close()
