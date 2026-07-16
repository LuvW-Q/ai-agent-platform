"""
IM消息路由：消息历史漫游/撤回/文件上传/已读标记
"""
import os
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import JSONResponse
from database.session import SessionLocal, get_db
from schema.api import MessageOut, MessageSend
from dao.base_dao import list_messages, create_message, log_action
from models.message import Message
from core.security import get_current_user
from core.sensitive_filter import sensitive_filter
from models.user import User

im_router = APIRouter(prefix="/api/messages", tags=["IM消息"])

# 文件上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 允许的文件扩展名白名单
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".pdf", ".doc", ".docx",
                      ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv", ".md", ".zip", ".rar",
                      ".mp3", ".mp4", ".wav", ".avi", ".mov"}
BLOCKED_EXTENSIONS = {".exe", ".bat", ".cmd", ".sh", ".ps1", ".com", ".scr", ".vbs", ".js", ".jar"}


@im_router.get("/history", response_model=list[MessageOut])
def message_history(
    peer_id: int = Query(None, description="对方用户ID（单聊）"),
    group_id: int = Query(None, description="群ID（群聊）"),
    before: int = Query(None, description="分页：返回此ID之前的消息"),
    limit: int = Query(50, ge=1, le=200),
    db: SessionLocal = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """消息漫游 — 获取历史消息，支持分页"""
    q = db.query(Message).filter(Message.status != "recalled")
    if group_id:
        q = q.filter(Message.group_id == group_id)
    elif peer_id:
        # 单聊：双方之间的消息
        from sqlalchemy import or_, and_
        q = q.filter(or_(
            and_(Message.sender_id == user.id, Message.receiver_id == peer_id),
            and_(Message.sender_id == peer_id, Message.receiver_id == user.id),
        ))
    else:
        return []
    if before:
        q = q.filter(Message.id < before)
    msgs = q.order_by(Message.created_at.desc()).limit(limit).all()
    # 标记为已读
    if peer_id:
        db.query(Message).filter(
            Message.sender_id == peer_id,
            Message.receiver_id == user.id,
            Message.is_read == False
        ).update({"is_read": True})
        db.commit()
    # 构建带 sender_name 的响应
    result = []
    for m in reversed(msgs):
        sender = db.query(User).filter(User.id == m.sender_id).first()
        result.append({
            "id": m.id,
            "msg_id": m.msg_id or "",
            "sender_id": m.sender_id,
            "sender_name": (sender.nickname or sender.username) if sender else "",
            "receiver_id": m.receiver_id,
            "group_id": m.group_id,
            "content": m.content,
            "msg_type": m.msg_type,
            "status": m.status,
            "is_read": m.is_read,
            "file_url": m.file_url or "",
            "file_name": m.file_name or "",
            "file_size": m.file_size or 0,
            "recall_at": m.recall_at,
            "created_at": m.created_at,
        })
    return result


@im_router.get("", response_model=list[MessageOut])
def list_all(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """获取消息列表"""
    return list_messages(user.id, db)


@im_router.post("", response_model=MessageOut, status_code=201)
def send(body: MessageSend, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """通过HTTP发送消息（WebSocket离线时的备选方案）"""
    # 幂等检查
    if body.msg_id:
        existing = db.query(Message).filter(Message.msg_id == body.msg_id).first()
        if existing:
            return existing
    msg = Message(
        msg_id=body.msg_id or str(uuid.uuid4()),
        sender_id=user.id,
        receiver_id=body.receiver_id,
        group_id=body.group_id,
        content=body.content,
        msg_type=body.msg_type,
        status="sent",
        file_url=body.file_url,
        file_name=body.file_name,
        file_size=body.file_size,
    )
    saved = create_message(msg, db)
    if not saved:
        raise HTTPException(status_code=500, detail="发送失败")
    log_action("message_send", f"用户 {user.username} 发送消息", user.username, db)
    return saved


@im_router.post("/{msg_id}/recall")
def recall_message(msg_id: str, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """撤回消息 — 2分钟内"""
    msg = db.query(Message).filter(
        (Message.msg_id == msg_id) | (Message.id == int(msg_id) if msg_id.isdigit() else 0)
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    if msg.sender_id != user.id:
        raise HTTPException(status_code=403, detail="只能撤回自己的消息")
    elapsed = (datetime.now(timezone.utc) - msg.created_at).total_seconds() if msg.created_at else 999
    if elapsed > 120:
        raise HTTPException(status_code=400, detail="超过2分钟不可撤回")
    msg.status = "recalled"
    msg.recall_at = datetime.now(timezone.utc)
    db.commit()
    return {"recalled": True}


@im_router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """文件/图片上传 — 格式白名单校验+大小限制"""
    # 检查文件扩展名
    ext = os.path.splitext(file.filename)[1].lower()
    if ext in BLOCKED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"文件类型 {ext} 被禁止上传")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    # 读取文件内容并检查大小
    content = await file.read()
    is_image = ext in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    max_size = 10 * 1024 * 1024 if is_image else 100 * 1024 * 1024
    if len(content) > max_size:
        limit_mb = 10 if is_image else 100
        raise HTTPException(status_code=400, detail=f"文件超过{limit_mb}MB限制")

    # 保存文件
    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)

    return JSONResponse({
        "url": f"/uploads/{safe_name}",
        "filename": file.filename,
        "size": len(content),
        "type": "image" if is_image else "file",
    })


@im_router.put("/{msg_id}/read")
def mark_read(msg_id: int, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """标记消息已读"""
    msg = db.query(Message).filter(Message.id == msg_id).first()
    if msg and msg.receiver_id == user.id:
        msg.is_read = True
        db.commit()
    return {"read": True}


@im_router.get("/conversations")
def conversations(db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """获取会话列表 — 按最后消息时间排序"""
    from sqlalchemy import or_, and_, func, case, desc
    # 获取所有相关消息
    msgs = db.query(Message).filter(
        or_(Message.sender_id == user.id, Message.receiver_id == user.id)
    ).order_by(Message.created_at.desc()).all()

    seen = set()
    convos = []
    for m in msgs:
        key = None
        peer_id = None
        grp_id = None
        if m.group_id:
            key = f"g{m.group_id}"
            grp_id = m.group_id
        elif m.receiver_id == user.id:
            key = f"u{m.sender_id}"
            peer_id = m.sender_id
        elif m.sender_id == user.id and m.receiver_id:
            key = f"u{m.receiver_id}"
            peer_id = m.receiver_id
        if key and key not in seen:
            seen.add(key)
            # 获取对方信息
            peer_name = ""
            peer_avatar = ""
            if peer_id:
                peer = db.query(User).filter(User.id == peer_id).first()
                if peer:
                    peer_name = peer.nickname or peer.username
                    peer_avatar = peer.avatar or ""
            convos.append({
                "peer_id": peer_id,
                "group_id": grp_id,
                "peer_name": peer_name,
                "peer_avatar": peer_avatar,
                "last_message": m.content[:50] if m.content else ("[文件] " + m.file_name if m.file_name else "[图片]"),
                "last_msg_type": m.msg_type,
                "last_time": m.created_at.isoformat() if m.created_at else None,
                "status": m.status,
            })
    return convos


# ==================== 管理员会话管理 ====================


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
        return ("medium", ["***"])
    return ("low", [])


@im_router.get("/admin/conversations")
def admin_conversations(
    limit: int = Query(50, ge=1, le=500),
    db: SessionLocal = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """管理员查看所有用户最近会话（按用户聚合，含风险标签）

    返回最近活跃会话：按 sender_id 聚合取该用户最新一条消息，
    根据该消息内容判断风险等级，前端按 risk_level=='high' 标红整行。
    """
    from sqlalchemy import func

    # 子查询：每个 sender 最近一条消息时间
    subq = (
        db.query(
            Message.sender_id.label("uid"),
            func.max(Message.created_at).label("last_time"),
        )
        .filter(Message.sender_id.isnot(None))
        .group_by(Message.sender_id)
        .subquery()
    )

    # 用 join 取每个 sender 的最新一条消息
    last_msgs = (
        db.query(Message)
        .join(subq, (Message.sender_id == subq.c.uid) & (Message.created_at == subq.c.last_time))
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )

    convs = []
    for m in last_msgs:
        sender = db.query(User).filter(User.id == m.sender_id).first() if m.sender_id else None
        risk, _matched = _classify_risk(m.content, db)
        convs.append({
            "user_id": m.sender_id,
            "username": (sender.nickname or sender.username) if sender else f"用户{m.sender_id}",
            "peer_id": m.receiver_id,
            "group_id": m.group_id,
            "last_message": (m.content or "")[:100],
            "last_time": m.created_at.isoformat() if m.created_at else None,
            "risk_level": risk,
            "is_sensitive": risk == "high",
        })
    return convs
