"""审计报告 P0/P1 剩余项回归测试。"""

import uuid

from fastapi.testclient import TestClient

from core.security import get_current_user
from database.session import SessionLocal
from main import app
from models.group import Group
from models.group_member import GroupMember
from models.message import Message
from models.user import User


def _user(user_id: int, role: str = "USER") -> User:
    user = User(
        username=f"audit_user_{user_id}",
        nickname=f"audit_user_{user_id}",
        email=f"audit_user_{user_id}@test.local",
        role=role,
        avatar="",
        signature="",
        is_active=True,
    )
    user.id = user_id
    return user


def _client_as(user: User) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_group_membership_and_manager_authorization_is_enforced():
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    group = Group(name=f"authz-{suffix}", owner_id=9501)
    db.add(group)
    db.flush()
    db.add_all([
        GroupMember(group_id=group.id, user_id=9501, role="owner"),
        GroupMember(group_id=group.id, user_id=9502, role="member"),
        Message(
            msg_id=f"group-msg-{suffix}",
            sender_id=9501,
            group_id=group.id,
            content="secret group message",
            msg_type="text",
        ),
    ])
    db.commit()
    group_id = group.id
    db.close()

    try:
        non_member = _client_as(_user(9503))
        assert non_member.get(f"/api/groups/{group_id}/members").status_code == 403
        assert non_member.get(f"/api/messages/history?group_id={group_id}").status_code == 403
        assert non_member.post(
            "/api/messages",
            json={"group_id": group_id, "content": "forged", "msg_type": "text"},
        ).status_code == 403

        member = _client_as(_user(9502))
        assert member.get(f"/api/groups/{group_id}/members").status_code == 200
        assert member.put(f"/api/groups/{group_id}", json={"announcement": "x"}).status_code == 403

        owner = _client_as(_user(9501))
        updated = owner.put(f"/api/groups/{group_id}", json={"announcement": "ok"})
        assert updated.status_code == 200, updated.text
    finally:
        app.dependency_overrides.clear()
        db = SessionLocal()
        try:
            db.query(Message).filter(Message.group_id == group_id).delete()
            db.query(GroupMember).filter(GroupMember.group_id == group_id).delete()
            db.query(Group).filter(Group.id == group_id).delete()
            db.commit()
        finally:
            db.close()


def test_user_cannot_call_global_nl2sql():
    response = _client_as(_user(9510)).post("/api/query/nl2sql", json={"question": "列出所有用户"})
    app.dependency_overrides.clear()
    assert response.status_code == 403


def test_user_cannot_read_management_model_or_skill_config():
    client = _client_as(_user(9512))
    try:
        assert client.get("/api/agents").status_code == 403
        assert client.get("/api/models").status_code == 403
        assert client.get("/api/skills").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_model_endpoint_rejects_private_addresses_on_save():
    client = _client_as(_user(9511, "ROOT"))
    try:
        response = client.post("/api/models", json={
            "name": "private-endpoint",
            "provider": "test",
            "api_key": "sk-test",
            "model_name": "test-model",
            "endpoint": "http://127.0.0.1/v1",
            "context_length": 4096,
            "model_type": "chat",
            "temperature": "0.1",
            "max_tokens": 128,
        })
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()
