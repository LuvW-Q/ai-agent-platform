"""
RBAC dependency test — assert GUEST gets 403 and ROOT gets 200/201 on a protected endpoint.

Uses FastAPI TestClient and overrides `get_current_user` to inject a user with
the desired role, so the test does not need JWT issuance.
"""
from fastapi.testclient import TestClient

from core.security import get_current_user
from models.user import User


def _stub_user(role: str) -> User:
    """Build a transient User instance with the requested role."""
    u = User(
        username=f"stub_{role}",
        nickname=f"stub_{role}",
        email=f"stub_{role}@test.local",
        role=role,
        avatar="",
        signature="",
        is_active=True,
    )
    u.id = 1
    return u


def _make_client_with_role(role: str) -> TestClient:
    """Create a TestClient with get_current_user overridden to return the given role."""
    from main import app

    app.dependency_overrides[get_current_user] = lambda: _stub_user(role)
    return TestClient(app)


def test_guest_gets_403_on_create_role():
    """POST /api/permissions/roles requires ROOT/ADMIN; GUEST must be rejected."""
    payload = {"name": "测试角色", "code": "TEST_ROLE", "description": ""}
    client = _make_client_with_role("guest")
    resp = client.post("/api/permissions/roles", json=payload)
    assert resp.status_code == 403, f"guest should be 403, got {resp.status_code}: {resp.text}"


def test_root_gets_201_on_create_role():
    """POST /api/permissions/roles with ROOT should succeed with 201."""
    payload = {"name": "测试角色", "code": "TEST_ROLE_X", "description": ""}
    client = _make_client_with_role("root")
    resp = client.post("/api/permissions/roles", json=payload)
    assert resp.status_code in (200, 201), f"root should be 2xx, got {resp.status_code}: {resp.text}"
    assert resp.status_code == 201


def test_guest_gets_403_on_setting_update():
    """PUT /api/settings/{key} requires ROOT; GUEST must be rejected."""
    client = _make_client_with_role("guest")
    resp = client.put("/api/settings/site.title", json={"value": "x"})
    assert resp.status_code == 403, f"guest should be 403, got {resp.status_code}: {resp.text}"


def test_root_gets_200_on_setting_update():
    """PUT /api/settings/{key} with ROOT should succeed."""
    client = _make_client_with_role("root")
    resp = client.put("/api/settings/site.title", json={"value": "test"})
    assert resp.status_code in (200, 201), f"root should be 2xx, got {resp.status_code}: {resp.text}"


def teardown_module(module):
    """Clear overrides so other tests are not affected."""
    from main import app
    app.dependency_overrides.clear()
