"""最终审计修复的接口与页面回归测试。"""

import uuid

from fastapi.testclient import TestClient

from controller.smart_audit_controller import _parse_risk_result
from core.security import get_current_user
from database.session import SessionLocal
from models.agent import Agent
from models.api_registry import ApiRegistry
from models.user import User


def _root() -> User:
    user = User(username="audit_fix_root", password_hash="unused", role="ROOT", is_active=True)
    user.id = 990001
    return user


def test_dashboard_and_data_governance_routes_have_distinct_pages():
    from main import app

    client = TestClient(app)
    dashboard = client.get("/dashboard")
    governance = client.get("/data-governance")
    assert dashboard.status_code == 200
    assert governance.status_code == 200
    assert "控制台" in dashboard.text
    assert "数据治理工作台" in governance.text


def test_dashboard_metrics_use_configured_collection_sources():
    from main import app

    app.dependency_overrides[get_current_user] = _root
    try:
        response = TestClient(app).get("/api/dashboard/metrics")
        assert response.status_code == 200
        assert response.json()["active_pipelines"] >= 3
        assert response.json()["crawl_success_rate"] > 0
        assert response.json()["total_collected"] >= 30
    finally:
        app.dependency_overrides.clear()


def test_setting_validation_rejects_unknown_and_invalid_values():
    from main import app

    app.dependency_overrides[get_current_user] = _root
    client = TestClient(app)
    try:
        assert client.put("/api/settings/not-a-setting", json={"value": "x"}).status_code == 404
        assert client.put("/api/settings/sensitive_threshold", json={"value": "1.5"}).status_code == 400
        assert client.put("/api/settings/log_retention_days", json={"value": "0"}).status_code == 400
        valid = client.put("/api/settings/voice_enabled", json={"value": "1"})
        assert valid.status_code == 200
        assert valid.json()["value"] == "true"
    finally:
        app.dependency_overrides.clear()


def test_api_registry_rejects_a_second_agent_for_the_same_api():
    from main import app

    db = SessionLocal()
    api = db.query(ApiRegistry).first()
    app.dependency_overrides[get_current_user] = _root
    client = TestClient(app)
    created_id = None
    try:
        first = client.post(f"/api/apis/{api.id}/create-agent", params={"agent_name": "接口员工回归"})
        assert first.status_code == 200
        created_id = first.json()["id"]
        second = client.post(f"/api/apis/{api.id}/create-agent", params={"agent_name": "重复接口员工"})
        assert second.status_code == 409
    finally:
        app.dependency_overrides.clear()
        if created_id:
            db.query(Agent).filter(Agent.id == created_id).delete(synchronize_session=False)
            db.commit()
        db.close()


def test_api_registry_never_returns_plaintext_auth_key_and_blank_update_keeps_it():
    from main import app

    db = SessionLocal()
    suffix = uuid.uuid4().hex[:10]
    secret = "registry-secret-value"
    api = ApiRegistry(
        name="密钥脱敏回归",
        code=f"secret_mask_{suffix}",
        base_url="https://example.com/test",
        method="GET",
        headers="{}",
        auth_type="header",
        auth_key=secret,
    )
    db.add(api)
    db.commit()
    db.refresh(api)
    app.dependency_overrides[get_current_user] = _root
    client = TestClient(app)
    try:
        rows = client.get("/api/apis")
        assert rows.status_code == 200
        row = next(item for item in rows.json() if item["id"] == api.id)
        assert row["auth_key"] == ""
        assert row["auth_key_configured"] is True
        assert secret not in rows.text

        updated = client.put(f"/api/apis/{api.id}", json={"description": "保留密钥", "auth_key": ""})
        assert updated.status_code == 200
        db.expire_all()
        assert db.query(ApiRegistry).filter(ApiRegistry.id == api.id).one().auth_key == secret
    finally:
        app.dependency_overrides.clear()
        db.delete(api)
        db.commit()
        db.close()


def test_risk_result_parser_accepts_fenced_json_and_normalizes_fields():
    parsed = _parse_risk_result(
        '分析如下：\n```json\n{"risk_level":"HIGH","risk_types":["涉诈"],'
        '"analysis":"存在风险","suggestions":"人工复核"}\n```'
    )
    assert parsed == {
        "risk_level": "high",
        "risk_types": ["涉诈"],
        "analysis": "存在风险",
        "suggestions": "人工复核",
    }
