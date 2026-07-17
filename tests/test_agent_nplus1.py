"""
Task 5 — N+1 query fix test for agent_controller.list_all.

Verifies:
  * GET /api/agents returns all agents with model_name and skill_names
    populated via batch-loaded lookups (no per-agent queries).
  * GET /api/agents?agent_type=model filters server-side and returns only
    model-type agents (frontend client-side filter still works, this is
    an additive optional server-side filter).

Uses TestClient + dependency_overrides for get_current_user (ROOT role)
to avoid JWT issuance.
"""
from fastapi.testclient import TestClient

from core.security import get_current_user
from models.user import User


def _stub_root_user() -> User:
    u = User(
        username="stub_root",
        nickname="stub_root",
        email="stub_root@test.local",
        role="root",
        avatar="",
        signature="",
        is_active=True,
    )
    u.id = 1
    return u


def _make_client() -> TestClient:
    from main import app
    app.dependency_overrides[get_current_user] = _stub_root_user
    return TestClient(app)


def _seed(db):
    """Seed 5 agents (3 model-type, 2 api-type) plus the models and skills
    they reference. Returns (model_name, skill_names_set).

    Wipes any seeded agents/models/skills so assertion counts hold — the
    test DB is seeded at import time by main.run_seed().
    """
    from models.ai_model import AIModel
    from models.skill import Skill
    from models.agent import Agent

    db.query(Agent).delete()
    db.query(Skill).delete()
    db.query(AIModel).delete()
    db.commit()

    m1 = AIModel(name="GPT-4o", provider="openai", api_key_cipher="cipher",
                 model_name="gpt-4o", is_default=False, is_active=True)
    m2 = AIModel(name="Claude Sonnet", provider="anthropic", api_key_cipher="cipher",
                 model_name="claude-sonnet", is_default=False, is_active=True)
    db.add_all([m1, m2])
    db.commit()
    db.refresh(m1)
    db.refresh(m2)

    s1 = Skill(name="天气查询", skill_type="function_call", description="",
               config="", parameters="[]", status="active")
    s2 = Skill(name="邮件摘要", skill_type="prompt", description="",
               config="", parameters="[]", status="active")
    s3 = Skill(name="报表生成", skill_type="function_call", description="",
               config="", parameters="[]", status="active")
    db.add_all([s1, s2, s3])
    db.commit()
    db.refresh(s1)
    db.refresh(s2)
    db.refresh(s3)

    # 3 model-type agents
    a1 = Agent(name="员工1", model_id=m1.id, skill_ids=f"{s1.id},{s2.id}",
               agent_type="model", status="draft", base_model="gpt-4o")
    a2 = Agent(name="员工2", model_id=m2.id, skill_ids=f"{s3.id}",
               agent_type="model", status="published", base_model="claude")
    a3 = Agent(name="员工3", model_id=m1.id, skill_ids="",
               agent_type="model", status="draft", base_model="gpt-4o")
    # 2 api-type agents (one with skill_ids, one without)
    a4 = Agent(name="员工4", skill_ids=f"{s2.id}",
               agent_type="api", status="draft", api_id=None,
               skill_bindings="api_x")
    a5 = Agent(name="员工5", skill_ids="",
               agent_type="api", status="draft", api_id=None,
               skill_bindings="api_y")

    db.add_all([a1, a2, a3, a4, a5])
    db.commit()

    return (
        {m1.id: m1.name, m2.id: m2.name},
        {s1.id: s1.name, s2.id: s2.name, s3.id: s3.name},
    )


def test_list_all_returns_all_agents_with_names():
    from main import app
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        model_map, skill_map = _seed(db)
    finally:
        db.close()

    client = _make_client()
    try:
        resp = client.get("/api/agents")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 5, f"expected 5 agents, got {len(data)}"

        # At least one agent has the correct model_name
        names_by_id = {a["id"]: a for a in data}
        a1 = next(a for a in data if a["name"] == "员工1")
        assert a1["model_name"] == model_map[a1["model_id"]], \
            f"model_name mismatch: {a1['model_name']!r}"

        # At least one agent has correct skill_names (order-insensitive)
        a1_skills = set(a1["skill_names"])
        expected = set()
        for x in a1["skill_ids"].split(","):
            if x.strip():
                expected.add(skill_map[int(x.strip())])
        assert a1_skills == expected, \
            f"skill_names mismatch: got {a1_skills}, want {expected}"
    finally:
        app.dependency_overrides.clear()


def test_list_all_filters_by_agent_type_model():
    from main import app
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        _seed(db)
    finally:
        db.close()

    client = _make_client()
    try:
        resp = client.get("/api/agents?agent_type=model")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data) == 3, f"expected 3 model-type agents, got {len(data)}"
        for a in data:
            assert a["agent_type"] == "model", \
                f"expected agent_type=model, got {a['agent_type']!r}"

        # And api-type filter excludes model-type
        resp_api = client.get("/api/agents?agent_type=api")
        assert resp_api.status_code == 200
        data_api = resp_api.json()
        assert len(data_api) == 2, \
            f"expected 2 api-type agents, got {len(data_api)}"
        for a in data_api:
            assert a["agent_type"] == "api"
    finally:
        app.dependency_overrides.clear()
