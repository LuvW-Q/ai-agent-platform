"""数字员工服务端会话隔离回归测试。"""

from fastapi.testclient import TestClient

from controller.de_controller import _merge_messages
from core.security import get_current_user
from database.session import SessionLocal
from models.agent import Agent
from models.de_message import DEMessage
from models.user import User


def test_merge_messages_removes_full_client_history_overlap():
    history = [
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
    ]
    frontend = history + [{"role": "user", "content": "第二问"}]
    assert _merge_messages(history, frontend) == frontend


def test_session_list_history_and_delete_are_scoped_to_current_user():
    from main import app

    db = SessionLocal()
    current = db.query(User).filter(User.role == "ROOT").first()
    agent = db.query(Agent).filter(Agent.status == "published").first()
    own_session = "session-own-regression"
    other_session = "session-other-regression"
    other = User(
        username="session_other_user",
        password_hash="unused",
        nickname="Other",
        email="session-other@test.local",
        role="USER",
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add_all([
        DEMessage(user_id=current.id, agent_id=agent.id, session_id=own_session,
                  role="user", content="当前用户的会话标题"),
        DEMessage(user_id=current.id, agent_id=agent.id, session_id=own_session,
                  role="assistant", content="当前用户的回答"),
        DEMessage(user_id=other.id, agent_id=agent.id, session_id=other_session,
                  role="user", content="其他用户的内容"),
    ])
    db.commit()

    app.dependency_overrides[get_current_user] = lambda: current
    client = TestClient(app)
    try:
        sessions = client.get("/api/de/sessions")
        assert sessions.status_code == 200
        ids = {item["id"] for item in sessions.json()}
        assert own_session in ids
        assert other_session not in ids

        history = client.get(f"/api/de/{agent.id}/history", params={"session_id": own_session})
        assert history.status_code == 200
        assert [item["content"] for item in history.json()] == ["当前用户的会话标题", "当前用户的回答"]

        deleted = client.delete(f"/api/de/sessions/{own_session}")
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": 2}
        assert db.query(DEMessage).filter(DEMessage.session_id == own_session).count() == 0
        assert db.query(DEMessage).filter(DEMessage.session_id == other_session).count() == 1
    finally:
        app.dependency_overrides.clear()
        db.query(DEMessage).filter(DEMessage.session_id.in_([own_session, other_session])).delete(
            synchronize_session=False
        )
        db.delete(other)
        db.commit()
        db.close()
