"""Regression coverage for the final checklist audit fixes."""

import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from core.security import get_current_user
from core.sensitive_filter import sensitive_filter
from database.session import SessionLocal
from models.ai_model import AIModel
from models.audit_log import AuditLog
from models.de_message import DEMessage
from models.message import Message
from models.sensitive_word import SensitiveWord
from models.user import User
from models.user_preference import UserPreference


def _user(role: str, user_id: int) -> User:
    user = User(
        username=f"completion_{role}_{user_id}",
        password_hash="unused",
        nickname="Completion Audit",
        email=f"completion_{user_id}@test.local",
        role=role,
        is_active=True,
    )
    user.id = user_id
    return user


def _client(user: User) -> TestClient:
    from main import app

    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_lowercase_user_menu_never_falls_back_to_management_pages():
    from main import app

    client = _client(_user("user", 930001))
    try:
        response = client.get("/api/permissions/menus")
        assert response.status_code == 200
        paths = {item["path"] for item in response.json()}
        assert {"/de", "/query", "/employees"}.issubset(paths)
        assert "/agent-management" not in paths
        assert "/permissions" not in paths
        assert "/models" not in paths
    finally:
        app.dependency_overrides.clear()


def test_personal_preferences_are_per_user_and_do_not_require_root():
    from main import app

    user = _user("USER", 930002)
    client = _client(user)
    try:
        updated = client.put(
            "/api/settings/preferences/notify_analysis", json={"value": "false"}
        )
        assert updated.status_code == 200
        assert updated.json()["value"] == "false"
        listed = client.get("/api/settings/preferences")
        values = {item["key"]: item["value"] for item in listed.json()}
        assert values["notify_analysis"] == "false"
        assert client.put("/api/settings/system_name", json={"value": "blocked"}).status_code == 403
    finally:
        app.dependency_overrides.clear()
        db = SessionLocal()
        db.query(UserPreference).filter(UserPreference.user_id == user.id).delete()
        db.query(AuditLog).filter(AuditLog.operator == user.username).delete()
        db.commit()
        db.close()


def test_user_delete_removes_user_owned_runtime_data():
    from main import app
    from models.agent import Agent

    suffix = uuid.uuid4().hex[:10]
    db = SessionLocal()
    target = User(
        username=f"cascade_{suffix}", password_hash="unused", nickname="Cascade",
        email=f"cascade_{suffix}@test.local", role="USER", is_active=True,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    agent = db.query(Agent).first()
    db.add_all([
        UserPreference(user_id=target.id, key="notify_analysis", value="false"),
        DEMessage(user_id=target.id, agent_id=agent.id, session_id="cascade", role="user", content="cleanup"),
        Message(msg_id=f"cascade-{suffix}", sender_id=target.id, content="cleanup", msg_type="text"),
    ])
    db.commit()
    target_id = target.id
    db.close()

    client = _client(_user("ROOT", 930010))
    try:
        deleted = client.delete(f"/api/permissions/users/{target_id}")
        assert deleted.status_code == 200
        db = SessionLocal()
        assert db.query(User).filter(User.id == target_id).first() is None
        assert db.query(UserPreference).filter(UserPreference.user_id == target_id).count() == 0
        assert db.query(DEMessage).filter(DEMessage.user_id == target_id).count() == 0
        assert db.query(Message).filter(Message.sender_id == target_id).count() == 0
        db.close()
    finally:
        app.dependency_overrides.clear()


def test_sensitive_input_is_blocked_persisted_and_visible_to_smart_audit():
    from main import app
    from models.agent import Agent

    user = _user("USER", 930003)
    db = SessionLocal()
    marker = f"机密词{uuid.uuid4().hex[:8]}"
    rule = SensitiveWord(word=marker, replacement="***", action="block")
    db.add(rule)
    db.commit()
    db.refresh(rule)
    agent = db.query(Agent).filter(Agent.status == "published").first()
    assert agent is not None
    agent_id = agent.id
    db.close()
    sensitive_filter.invalidate_cache()

    client = _client(user)
    session_id = "sensitive-audit-session"
    try:
        blocked_im = client.post(
            "/api/messages",
            json={"content": f"这里包含{marker}", "msg_type": "text", "msg_id": str(uuid.uuid4())},
        )
        assert blocked_im.status_code == 400
        assert "已被拦截" in blocked_im.json()["detail"]

        blocked_de = client.post(
            "/api/de/chat",
            json={
                "agent_id": agent_id,
                "session_id": session_id,
                "messages": [{"role": "user", "content": f"数字员工输入{marker}"}],
            },
        )
        assert blocked_de.status_code == 200
        assert "已被拦截" in blocked_de.json()["reply"]

        app.dependency_overrides[get_current_user] = lambda: _user("ROOT", 930004)
        audit = client.get("/api/smart-audit/messages?risk_level=high&limit=100")
        assert audit.status_code == 200
        rows = audit.json()
        assert any(row["source"] == "im" and marker in row["content"] for row in rows)
        assert any(row["source"] == "digital_employee" and marker in row["content"] for row in rows)

        db = SessionLocal()
        assert db.query(Message).filter(Message.sender_id == user.id, Message.status == "blocked").count() == 1
        assert db.query(DEMessage).filter(
            DEMessage.user_id == user.id, DEMessage.session_id == session_id
        ).count() == 2
        assert db.query(AuditLog).filter(
            AuditLog.operator == user.username, AuditLog.risk_level == "high"
        ).count() >= 2
        db.close()
    finally:
        app.dependency_overrides.clear()
        db = SessionLocal()
        db.query(Message).filter(Message.sender_id == user.id).delete()
        db.query(DEMessage).filter(DEMessage.user_id == user.id).delete()
        db.query(AuditLog).filter(AuditLog.operator == user.username).delete()
        db.query(SensitiveWord).filter(SensitiveWord.id == rule.id).delete()
        db.commit()
        db.close()
        sensitive_filter.invalidate_cache()


class _FakeAsyncClient:
    payload = {"data": []}
    status_code = 200
    requested_urls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, **kwargs):
        self.requested_urls.append(url)
        request = httpx.Request("POST", url)
        return httpx.Response(self.status_code, request=request, json=self.payload)


def test_multimodal_dispatch_builds_correct_v1_urls_and_rejects_empty_results():
    from main import app

    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    image_model = AIModel(
        name=f"Image {suffix}", provider="test", api_key="sk-valid-generation-key",
        model_name="image-test", endpoint="https://media.example/v1", model_type="image",
        is_active=True,
    )
    video_model = AIModel(
        name=f"Video {suffix}", provider="test", api_key="sk-valid-generation-key",
        model_name="video-test", endpoint="https://media.example", model_type="video",
        is_active=True,
    )
    db.add_all([image_model, video_model])
    db.commit()
    db.refresh(image_model)
    db.refresh(video_model)
    image_id, video_id = image_model.id, video_model.id
    db.close()

    client = _client(_user("USER", 930005))
    try:
        _FakeAsyncClient.requested_urls = []
        _FakeAsyncClient.payload = {"data": [{"url": "https://cdn.example/result.png"}]}
        _FakeAsyncClient.status_code = 200
        with patch("controller.creative_controller.httpx.AsyncClient", _FakeAsyncClient):
            image = client.post(
                "/api/creative/generate",
                json={"model_id": image_id, "type": "image", "prompt": "测试图片"},
            )
        assert image.status_code == 200
        assert image.json() == {"success": True, "urls": ["https://cdn.example/result.png"], "error": ""}
        assert _FakeAsyncClient.requested_urls[-1] == "https://media.example/v1/images/generations"

        _FakeAsyncClient.payload = {"data": [{"video_url": "https://cdn.example/result.mp4"}]}
        with patch("controller.creative_controller.httpx.AsyncClient", _FakeAsyncClient):
            video = client.post(
                "/api/creative/generate",
                json={"model_id": video_id, "type": "video", "prompt": "测试视频"},
            )
        assert video.status_code == 200
        assert video.json()["urls"] == ["https://cdn.example/result.mp4"]
        assert _FakeAsyncClient.requested_urls[-1] == "https://media.example/v1/video/generations"

        _FakeAsyncClient.payload = {"data": []}
        with patch("controller.creative_controller.httpx.AsyncClient", _FakeAsyncClient):
            empty = client.post(
                "/api/creative/generate",
                json={"model_id": image_id, "type": "image", "prompt": "空结果"},
            )
        assert empty.status_code == 200
        assert empty.json()["success"] is False
        assert "未返回" in empty.json()["error"]
    finally:
        app.dependency_overrides.clear()
        db = SessionLocal()
        db.query(AIModel).filter(AIModel.id.in_([image_id, video_id])).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_html_404_and_api_404_keep_their_expected_formats():
    from main import app

    client = TestClient(app)
    page = client.get("/this-page-does-not-exist", headers={"Accept": "text/html"})
    assert page.status_code == 404
    assert "页面未找到" in page.text
    assert page.headers["content-type"].startswith("text/html")

    api = client.get("/api/this-endpoint-does-not-exist")
    assert api.status_code == 404
    assert api.json() == {"detail": "Not Found"}


def test_management_pages_have_product_forms_and_correct_links():
    root = Path(__file__).resolve().parents[1]
    permissions_html = (root / "static" / "permissions.html").read_text(encoding="utf-8")
    agent_html = (root / "static" / "agent-management.html").read_text(encoding="utf-8")
    collection_html = (root / "static" / "data-collection.html").read_text(encoding="utf-8")
    assert "prompt(" not in permissions_html
    assert all(modal_id in permissions_html for modal_id in (
        'id="user-modal"', 'id="function-modal"', 'id="binding-modal"', 'id="menu-modal"'
    ))
    assert 'href="/apis"' not in agent_html
    assert 'href="/api-registry"' in agent_html
    assert "previewSource" in collection_html
    assert "openSourceModal(${s.id})" in collection_html
