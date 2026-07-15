"""
WebSocket聊天控制器
自定义协议：Header(msg_id, msg_type, timestamp) + Body(消息内容)
支持：实时聊天、ACK确认、消息撤回、多端同步、强制下线
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import jwt, JWTError
from database.session import SessionLocal
from core.config import config
from core.ws_manager import ws_manager
from models.user import User
from models.message import Message
from models.group_member import GroupMember
from dao.base_dao import log_action

ws_router = APIRouter(tags=["WebSocket"])


def _authenticate(token: str) -> User | None:
    """通过JWT token认证WebSocket连接"""
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        username = payload.get("sub")
        t_type = payload.get("type")
        exp = payload.get("exp")
        if t_type != "access":
            return None
        if exp and exp < datetime.now(timezone.utc).timestamp():
            return None
        db = SessionLocal()
        user = db.query(User).filter(User.username == username).first()
        db.close()
        return user
    except JWTError:
        return None


def _build_packet(msg_type: str, body: dict, msg_id: str = None) -> dict:
    """构建应用层协议包"""
    return {
        "msg_id": msg_id or str(uuid.uuid4()),
        "msg_type": msg_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "body": body,
    }


@ws_router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket, token: str = Query(...)):
    """WebSocket聊天端点 — 客户端连接时需传token查询参数"""
    user = _authenticate(token)
    if not user:
        await websocket.close(code=4001, reason="认证失败")
        return

    user_id = user.id
    await ws_manager.connect(user_id, websocket)

    # 发送上线通知
    await ws_manager.send_to_user(user_id, _build_packet("system", {
        "action": "connected",
        "user_id": user_id,
        "username": user.username,
        "message": "WebSocket连接成功"
    }))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                packet = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = packet.get("msg_type", "")
            msg_id = packet.get("msg_id", str(uuid.uuid4()))
            body = packet.get("body", {})

            if msg_type == "chat":
                await _handle_chat(user, msg_id, body)
            elif msg_type == "recall":
                await _handle_recall(user, msg_id, body)
            elif msg_type == "typing":
                await _handle_typing(user, body)
            elif msg_type == "read_receipt":
                await _handle_read_receipt(user, body)

    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, websocket)


async def _handle_chat(sender: User, msg_id: str, body: dict):
    """处理聊天消息：存储+转发+ACK"""
    db = SessionLocal()
    try:
        # 幂等检查：msg_id已存在则不重复存储
        existing = db.query(Message).filter(Message.msg_id == msg_id).first()
        if existing:
            # 返回ACK表示已处理
            await ws_manager.send_to_user(sender.id, _build_packet("ack", {
                "msg_id": msg_id,
                "status": "duplicate",
                "db_id": existing.id,
            }, msg_id))
            return

        chat_type = body.get("chat_type", "single")  # single/group
        content = body.get("content", "")
        content_type = body.get("content_type", "text")  # text/emoji/image/file
        file_url = body.get("file_url", "")
        file_name = body.get("file_name", "")
        file_size = body.get("file_size", 0)

        receiver_id = body.get("receiver_id")
        group_id = body.get("group_id")

        # 创建消息记录
        msg = Message(
            msg_id=msg_id,
            sender_id=sender.id,
            receiver_id=receiver_id if chat_type == "single" else None,
            group_id=group_id if chat_type == "group" else None,
            content=content,
            msg_type=content_type,
            status="sent",
            file_url=file_url,
            file_name=file_name,
            file_size=file_size,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)

        # 向发送方返回ACK
        await ws_manager.send_to_user(sender.id, _build_packet("ack", {
            "msg_id": msg_id,
            "status": "sent",
            "db_id": msg.id,
            "timestamp": msg.created_at.isoformat() if msg.created_at else None,
        }, msg_id))

        # 构建转发消息包
        forward = _build_packet("chat", {
            "db_id": msg.id,
            "msg_id": msg_id,
            "sender_id": sender.id,
            "sender_name": sender.nickname or sender.username,
            "sender_avatar": sender.avatar or "",
            "chat_type": chat_type,
            "receiver_id": receiver_id,
            "group_id": group_id,
            "content": content,
            "content_type": content_type,
            "file_url": file_url,
            "file_name": file_name,
            "file_size": file_size,
            "status": "delivered" if ws_manager.is_online(receiver_id) else "sent",
        }, msg_id)

        if chat_type == "single" and receiver_id:
            # 单聊：直接推送给接收方
            await ws_manager.send_to_user(receiver_id, forward)
        elif chat_type == "group" and group_id:
            # 群聊：推送给所有群成员
            members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
            member_ids = [m.user_id for m in members if m.user_id != sender.id]
            for uid in member_ids:
                await ws_manager.send_to_user(uid, forward)

        # 审计日志
        log_action("message_send", f"用户 {sender.username} 发送{chat_type}消息", sender.username, db)

    except Exception as e:
        # 发送失败ACK
        await ws_manager.send_to_user(sender.id, _build_packet("ack", {
            "msg_id": msg_id,
            "status": "failed",
            "error": str(e),
        }, msg_id))
    finally:
        db.close()


async def _handle_recall(user: User, msg_id: str, body: dict):
    """处理消息撤回 — 2分钟内可撤回"""
    db = SessionLocal()
    try:
        db_id = body.get("db_id")
        msg = db.query(Message).filter(Message.id == db_id).first() if db_id else None
        if not msg:
            return
        if msg.sender_id != user.id:
            return
        # 2分钟内可撤回
        elapsed = (datetime.now(timezone.utc) - msg.created_at).total_seconds() if msg.created_at else 999
        if elapsed > 120:
            await ws_manager.send_to_user(user.id, _build_packet("ack", {
                "msg_id": msg_id, "status": "recall_failed", "reason": "超过2分钟不可撤回"
            }, msg_id))
            return

        msg.status = "recalled"
        msg.recall_at = datetime.now(timezone.utc)
        db.commit()

        # 通知双方
        recall_packet = _build_packet("recall", {
            "db_id": msg.id,
            "msg_id": msg.msg_id,
            "sender_id": msg.sender_id,
            "receiver_id": msg.receiver_id,
            "group_id": msg.group_id,
        }, msg_id)

        await ws_manager.send_to_user(user.id, recall_packet)
        if msg.receiver_id:
            await ws_manager.send_to_user(msg.receiver_id, recall_packet)
        elif msg.group_id:
            members = db.query(GroupMember).filter(GroupMember.group_id == msg.group_id).all()
            for m in members:
                if m.user_id != user.id:
                    await ws_manager.send_to_user(m.user_id, recall_packet)

    finally:
        db.close()


async def _handle_typing(user: User, body: dict):
    """处理正在输入状态"""
    receiver_id = body.get("receiver_id")
    group_id = body.get("group_id")
    packet = _build_packet("typing", {
        "sender_id": user.id,
        "sender_name": user.nickname or user.username,
        "receiver_id": receiver_id,
        "group_id": group_id,
    })
    if receiver_id:
        await ws_manager.send_to_user(receiver_id, packet)
    elif group_id:
        db = SessionLocal()
        members = db.query(GroupMember).filter(GroupMember.group_id == group_id).all()
        db.close()
        for m in members:
            if m.user_id != user.id:
                await ws_manager.send_to_user(m.user_id, packet)


async def _handle_read_receipt(user: User, body: dict):
    """处理已读回执"""
    db = SessionLocal()
    try:
        sender_id = body.get("sender_id")
        # 标记来自sender_id的消息为已读
        db.query(Message).filter(
            Message.sender_id == sender_id,
            Message.receiver_id == user.id,
            Message.is_read == False
        ).update({"is_read": True})
        db.commit()
        # 通知发送方
        await ws_manager.send_to_user(sender_id, _build_packet("read_receipt", {
            "reader_id": user.id,
            "sender_id": sender_id,
        }))
    finally:
        db.close()
