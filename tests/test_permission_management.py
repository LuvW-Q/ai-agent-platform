"""用户、功能点和角色-功能-资源绑定管理回归测试。"""

import uuid

from fastapi.testclient import TestClient

from core.security import get_current_user
from models.user import User


def _user(role: str, user_id: int) -> User:
    user = User(
        username=f"permission_{role}_{user_id}",
        password_hash="unused",
        nickname="Permission Test",
        email=f"permission_{role}_{user_id}@test.local",
        role=role,
        is_active=True,
    )
    user.id = user_id
    return user


def test_function_binding_tree_and_user_crud():
    from main import app

    suffix = uuid.uuid4().hex[:10]
    role_code = f"ROLE_{suffix}"
    function_code = f"function_{suffix}"
    username = f"managed_{suffix}"
    app.dependency_overrides[get_current_user] = lambda: _user("ROOT", 910001)
    client = TestClient(app)

    role = client.post(
        "/api/permissions/roles",
        json={"name": f"测试角色 {suffix}", "code": role_code, "description": "权限绑定回归"},
    )
    assert role.status_code == 201
    role_id = role.json()["id"]

    function = client.post(
        "/api/permissions/functions",
        json={"name": f"测试功能 {suffix}", "code": function_code, "description": "功能点回归"},
    )
    assert function.status_code == 201
    function_id = function.json()["id"]

    binding = client.post(
        "/api/permissions/bindings",
        json={
            "role_code": role_code,
            "function_code": function_code,
            "resource": f"/resource/{suffix}",
            "actions": "查看,编辑",
        },
    )
    assert binding.status_code == 201
    binding_id = binding.json()["id"]

    app.dependency_overrides[get_current_user] = lambda: _user(role_code, 910002)
    tree = client.get("/api/permissions/tree")
    assert tree.status_code == 200
    assert tree.json()["modules"] == [{
        "name": f"测试功能 {suffix}",
        "icon": "verified_user",
        "path": f"/resource/{suffix}",
        "permissions": ["查看", "编辑"],
    }]

    app.dependency_overrides[get_current_user] = lambda: _user("ROOT", 910001)
    created_user = client.post(
        "/api/permissions/users",
        json={
            "username": username,
            "password": "Managed123!",
            "nickname": "受管用户",
            "email": f"{username}@test.local",
            "role": role_code,
        },
    )
    assert created_user.status_code == 201
    managed_user_id = created_user.json()["id"]
    assert created_user.json()["role"] == role_code

    assert client.delete(f"/api/permissions/users/{managed_user_id}").status_code == 200
    assert client.delete(f"/api/permissions/bindings/{binding_id}").status_code == 200
    assert client.delete(f"/api/permissions/functions/{function_id}").status_code == 200
    assert client.delete(f"/api/permissions/roles/{role_id}").status_code == 200
    app.dependency_overrides.clear()
