"""管理员会话详情、导出和删除回归测试。"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import or_

from core.security import get_current_user
from database.session import SessionLocal
from models.message import Message
from models.user import User


def _root_user() -> User:
    user = User(username="conversation_root", nickname="Root", email="root@test.local", role="ROOT")
    user.id = 900001
    return user


def test_root_can_view_export_and_delete_conversation():
    from main import app

    db = SessionLocal()
    suffix = uuid.uuid4().hex[:12]
    target = User(
        username=f"conversation_{suffix}",
        password_hash="unused",
        nickname="Conversation User",
        email=f"conversation_{suffix}@test.local",
        role="USER",
    )
    peer = User(
        username=f"peer_{suffix}",
        password_hash="unused",
        nickname="Peer User",
        email=f"peer_{suffix}@test.local",
        role="USER",
    )
    db.add_all([target, peer])
    db.commit()
    db.refresh(target)
    db.refresh(peer)
    message = Message(
        msg_id=str(uuid.uuid4()),
        sender_id=target.id,
        receiver_id=peer.id,
        content="conversation export regression",
        msg_type="text",
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    target_id = target.id
    peer_id = peer.id
    message_id = message.id

    app.dependency_overrides[get_current_user] = _root_user
    client = TestClient(app)
    try:
        detail = client.get(f"/api/messages/admin/conversations/{target_id}/messages")
        assert detail.status_code == 200
        assert [row["id"] for row in detail.json()] == [message_id]

        export = client.get(f"/api/messages/admin/conversations/{target_id}/export")
        assert export.status_code == 200
        assert export.content.startswith(b"\xef\xbb\xbf")
        assert "conversation export regression" in export.text

        deleted = client.delete(f"/api/messages/admin/conversations/{target_id}")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": 1}
        db.expire_all()
        assert db.query(Message).filter(Message.id == message_id).first() is None
    finally:
        app.dependency_overrides.clear()
        db.query(Message).filter(or_(Message.sender_id == target_id, Message.receiver_id == target_id)).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id.in_([target_id, peer_id])).delete(synchronize_session=False)
        db.commit()
        db.close()
