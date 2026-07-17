"""
IM消息路由：消息历史漫游/撤回/文件上传/已读标记
"""
import csv
import io
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy import or_
from database.session import SessionLocal, get_db
from schema.api import MessageOut, MessageSend
from dao.base_dao import list_messages, create_message, log_action
from models.message import Message
from core.security import get_current_user
from core.rbac import require_role
from core.sensitive_filter import sensitive_filter
from core.upload_security import IMAGE_EXTENSIONS, MESSAGE_EXTENSIONS, save_validated_upload
from models.user import User

im_router = APIRouter(prefix="/api/messages", tags=["IM消息"])

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
            if existing.status == "blocked":
                raise HTTPException(status_code=400, detail="消息包含敏感信息，已被拦截")
            return existing
    content = body.content
    matches = []
    blocked = False
    if body.msg_type == "text":
        content, blocked, matches = sensitive_filter.inspect(body.content, db)
    msg = Message(
        msg_id=body.msg_id or str(uuid.uuid4()),
        sender_id=user.id,
        receiver_id=body.receiver_id,
        group_id=body.group_id,
        content=body.content if blocked else content,
        msg_type=body.msg_type,
        status="blocked" if blocked else "sent",
        file_url=body.file_url,
        file_name=body.file_name,
        file_size=body.file_size,
    )
    saved = create_message(msg, db)
    if not saved:
        raise HTTPException(status_code=500, detail="发送失败")
    if matches:
        matched_words = "、".join(sorted({rule["word"] for rule in matches}))
        log_action(
            "sensitive_message_blocked" if blocked else "sensitive_message_filtered",
            f"用户 {user.username} 的消息命中敏感规则: {matched_words}",
            user.username,
            db,
            risk_level="high" if blocked else "medium",
        )
    if blocked:
        raise HTTPException(status_code=400, detail="消息包含敏感信息，已被拦截")
    log_action("message_send", f"用户 {user.username} 发送消息", user.username, db)
    return saved


@im_router.post("/{msg_id}/recall")
def recall_message(msg_id: str, db: SessionLocal = Depends(get_db), user: User = Depends(get_current_user)):
    """撤回消息 — 2分钟内"""
    lookup = Message.msg_id == msg_id
    if msg_id.isdigit():
        lookup = or_(lookup, Message.id == int(msg_id))
    msg = db.query(Message).filter(lookup).first()
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")
    if msg.sender_id != user.id:
        raise HTTPException(status_code=403, detail="只能撤回自己的消息")
    created_at = msg.created_at
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - created_at).total_seconds() if created_at else 999
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
    """文件/图片上传：分块限流并校验真实文件类型。"""
    extension = Path(file.filename or "").suffix.lower()
    is_image = extension in IMAGE_EXTENSIONS
    saved = await save_validated_upload(
        file,
        category=f"messages/{user.id}",
        allowed_extensions=MESSAGE_EXTENSIONS,
        max_size=10 * 1024 * 1024 if is_image else 100 * 1024 * 1024,
    )

    return JSONResponse({
        "url": f"/api/uploads/{saved.relative_path}",
        "filename": saved.original_name,
        "size": saved.size,
        "type": "image" if saved.is_image else "file",
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
    user: User = Depends(require_role("ROOT", "AUDIT")),
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


def _admin_message_rows(user_id: int, db: SessionLocal):
    return (
        db.query(Message)
        .filter(or_(Message.sender_id == user_id, Message.receiver_id == user_id))
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )


def _serialize_admin_message(message: Message, db: SessionLocal) -> dict:
    sender = db.query(User).filter(User.id == message.sender_id).first()
    risk_level, matched_words = _classify_risk(message.content, db)
    return {
        "id": message.id,
        "msg_id": message.msg_id or "",
        "sender_id": message.sender_id,
        "sender_name": (sender.nickname or sender.username) if sender else "",
        "receiver_id": message.receiver_id,
        "group_id": message.group_id,
        "content": message.content,
        "msg_type": message.msg_type,
        "status": message.status,
        "risk_level": risk_level,
        "matched_words": matched_words,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


@im_router.get("/admin/conversations/{user_id}/messages")
def admin_conversation_messages(
    user_id: int,
    db: SessionLocal = Depends(get_db),
    user: User = Depends(require_role("ROOT", "AUDIT")),
):
    """管理员下钻查看指定用户参与的完整消息记录。"""
    if db.query(User).filter(User.id == user_id).first() is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return [_serialize_admin_message(message, db) for message in _admin_message_rows(user_id, db)]


@im_router.get("/admin/conversations/{user_id}/export")
def export_admin_conversation(
    user_id: int,
    db: SessionLocal = Depends(get_db),
    user: User = Depends(require_role("ROOT", "AUDIT")),
):
    """将指定用户参与的全部消息导出为 UTF-8 BOM CSV。"""
    if db.query(User).filter(User.id == user_id).first() is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["消息ID", "发送者ID", "接收者ID", "群组ID", "类型", "状态", "内容", "发送时间"])
    for message in _admin_message_rows(user_id, db):
        writer.writerow([
            message.id,
            message.sender_id,
            message.receiver_id or "",
            message.group_id or "",
            message.msg_type,
            message.status,
            message.content,
            message.created_at.isoformat() if message.created_at else "",
        ])
    log_action("conversation_export", f"导出用户 {user_id} 的会话", user.username, db)
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="conversation-{user_id}.csv"'},
    )


@im_router.delete("/admin/conversations/{user_id}")
def delete_admin_conversation(
    user_id: int,
    db: SessionLocal = Depends(get_db),
    user: User = Depends(require_role("ROOT")),
):
    """超级管理员删除指定用户参与的全部消息。"""
    messages = _admin_message_rows(user_id, db)
    for message in messages:
        db.delete(message)
    db.commit()
    log_action("conversation_delete", f"删除用户 {user_id} 的会话，共 {len(messages)} 条消息", user.username, db)
    return {"deleted": len(messages)}


@im_router.delete("/admin/messages/{message_id}")
def delete_admin_message(
    message_id: int,
    db: SessionLocal = Depends(get_db),
    user: User = Depends(require_role("ROOT")),
):
    """超级管理员删除单条消息。"""
    message = db.query(Message).filter(Message.id == message_id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    db.delete(message)
    db.commit()
    log_action("message_delete", f"删除消息 {message_id}", user.username, db)
    return {"deleted": True}
