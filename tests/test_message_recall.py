"""消息撤回回归测试。"""

from fastapi.testclient import TestClient

from core.security import get_current_user
from main import app
from models.message import Message
from models.user import User


def _user(user_id: int, username: str) -> User:
    user = User(
        username=username,
        nickname=username,
        email=f"{username}@test.local",
        role="ROOT",
        avatar="",
        signature="",
        is_active=True,
    )
    user.id = user_id
    return user


def test_recall_supports_client_and_database_ids(db_session):
    db_session.query(Message).delete()
    db_session.commit()

    sender = _user(9001, "recall_sender")
    app.dependency_overrides[get_current_user] = lambda: sender
    client = TestClient(app)

    try:
        by_client_id = client.post(
            "/api/messages",
            json={
                "receiver_id": 9002,
                "content": "client id recall",
                "msg_id": "recall-client-id",
            },
        )
        assert by_client_id.status_code == 201, by_client_id.text
        recalled = client.post("/api/messages/recall-client-id/recall")
        assert recalled.status_code == 200, recalled.text
        assert recalled.json() == {"recalled": True}

        by_database_id = client.post(
            "/api/messages",
            json={
                "receiver_id": 9002,
                "content": "database id recall",
                "msg_id": "recall-database-id",
            },
        )
        assert by_database_id.status_code == 201, by_database_id.text
        database_id = by_database_id.json()["id"]
        recalled = client.post(f"/api/messages/{database_id}/recall")
        assert recalled.status_code == 200, recalled.text
        assert recalled.json() == {"recalled": True}
    finally:
        app.dependency_overrides.clear()


def test_recall_rejects_non_sender(db_session):
    db_session.query(Message).delete()
    db_session.commit()

    sender = _user(9011, "recall_owner")
    other_user = _user(9012, "recall_other")
    app.dependency_overrides[get_current_user] = lambda: sender
    client = TestClient(app)

    try:
        sent = client.post(
            "/api/messages",
            json={
                "receiver_id": other_user.id,
                "content": "permission check",
                "msg_id": "recall-permission-id",
            },
        )
        assert sent.status_code == 201, sent.text

        app.dependency_overrides[get_current_user] = lambda: other_user
        forbidden = client.post("/api/messages/recall-permission-id/recall")
        assert forbidden.status_code == 403, forbidden.text
        assert forbidden.json()["detail"] == "只能撤回自己的消息"
    finally:
        app.dependency_overrides.clear()
