"""天气、计算器与接口型数字员工的真实分发回归测试。"""

import asyncio
import uuid

import httpx
from fastapi.testclient import TestClient

from core.builtin_skills import execute_builtin_skill, execute_builtin_skill_async
from core.security import get_current_user
from database.session import SessionLocal
from models.agent import Agent
from models.api_registry import ApiRegistry
from models.de_message import DEMessage
from models.skill import Skill
from models.user import User
from controller.de_controller import _extract_args_from_msg


def test_builtin_calculator_accepts_arithmetic_and_rejects_code(db_session):
    assert execute_builtin_skill("calculator", {"expression": "(7 + 5) * 3"}, db_session)["result"] == 36
    try:
        execute_builtin_skill("calculator", {"expression": "__import__('os')"}, db_session)
    except ValueError as exc:
        assert "仅支持" in str(exc)
    else:
        raise AssertionError("calculator accepted executable code")


def test_latest_news_request_does_not_turn_request_words_into_a_keyword(db_session):
    skill = Skill(
        name="新闻检索",
        parameters='{"type":"object","properties":{"keyword":{"type":"string"}}}',
    )
    assert _extract_args_from_msg("请检索最新新闻", skill) == {"keyword": ""}


def test_weather_builtin_parses_public_api_payload(monkeypatch, db_session):
    async def fake_request(client, method, url, **kwargs):
        assert method == "GET"
        assert "Beijing" in url
        return httpx.Response(
            200,
            json={
                "current_condition": [{
                    "temp_C": "26", "humidity": "45", "winddir16Point": "NE",
                    "windspeedKmph": "9", "weatherDesc": [{"value": "Sunny"}],
                }],
                "weather": [{"maxtempC": "30", "mintempC": "18"}],
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("core.builtin_skills.request_public_url", fake_request)
    result = asyncio.run(execute_builtin_skill_async("weather", {"city": "Beijing"}, db_session))
    assert result == {
        "city": "Beijing",
        "temperature": "26°C",
        "description": "Sunny",
        "humidity": "45%",
        "wind": "NE 9km/h",
        "today_high": "30°C",
        "today_low": "18°C",
    }


def test_published_api_agent_calls_registry_and_persists_session(monkeypatch):
    from main import app

    db = SessionLocal()
    current = db.query(User).filter(User.role == "ROOT").first()
    suffix = uuid.uuid4().hex[:10]
    registry = ApiRegistry(
        name="IP 归属测试",
        code=f"ip_test_{suffix}",
        base_url="https://example.com/ip/{params}",
        method="GET",
        headers="{}",
        response_path="country",
        auth_type="none",
        auth_key="",
    )
    db.add(registry)
    db.commit()
    db.refresh(registry)
    agent = Agent(
        name=f"IP 员工 {suffix}",
        status="published",
        agent_type="api",
        api_id=registry.id,
        fallback_message="IP 查询暂不可用",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    session_id = f"api-agent-{suffix}"

    async def fake_request(client, method, url, **kwargs):
        assert url.endswith("/8.8.8.8")
        return httpx.Response(
            200,
            json={"country": "United States"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("controller.de_controller.request_public_url", fake_request)
    app.dependency_overrides[get_current_user] = lambda: current
    client = TestClient(app)
    try:
        response = client.post("/api/de/chat", json={
            "agent_id": agent.id,
            "session_id": session_id,
            "messages": [{"role": "user", "content": "8.8.8.8 是哪的 IP"}],
        })
        assert response.status_code == 200
        assert "United States" in response.json()["reply"]
        assert response.json()["skill_calls"][0]["skill"] == f"api_{registry.id}"
        assert db.query(DEMessage).filter(DEMessage.session_id == session_id).count() == 2
    finally:
        app.dependency_overrides.clear()
        db.query(DEMessage).filter(DEMessage.session_id == session_id).delete(synchronize_session=False)
        db.delete(agent)
        db.delete(registry)
        db.commit()
        db.close()
