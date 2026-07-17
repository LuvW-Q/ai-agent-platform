"""人脸注册与登录接口回归测试。"""

import json
import uuid

from fastapi.testclient import TestClient

from core.crypto import decrypt
from database.session import SessionLocal
from models.user import User


def _new_account(client: TestClient) -> tuple[str, dict[str, str]]:
    username = f"face_{uuid.uuid4().hex[:12]}"
    password = "FaceTest123!"
    register_response = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "email": f"{username}@test.local"},
    )
    assert register_response.status_code == 200
    login_response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200
    return username, login_response.json()


def _descriptor(value: float) -> list[float]:
    return [value] * 128


def test_face_register_encrypts_descriptor_and_face_login_returns_tokens():
    from main import app

    client = TestClient(app)
    username, tokens = _new_account(client)
    descriptor = _descriptor(0.125)
    register_response = client.post(
        "/api/auth/face/register",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"descriptor": descriptor},
    )
    assert register_response.status_code == 200
    assert register_response.json() == {"registered": True}

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one()
        assert user.face_descriptor != json.dumps(descriptor, separators=(",", ":"))
        assert json.loads(decrypt(user.face_descriptor)) == descriptor
    finally:
        db.close()

    login_response = client.post(
        "/api/auth/face/login",
        json={"username": username, "descriptor": descriptor},
    )
    assert login_response.status_code == 200
    body = login_response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"


def test_face_register_requires_access_token():
    from main import app

    response = TestClient(app).post(
        "/api/auth/face/register",
        json={"descriptor": _descriptor(0.0)},
    )
    assert response.status_code == 401


def test_face_descriptor_must_have_exactly_128_finite_numbers():
    from main import app

    client = TestClient(app)
    username, tokens = _new_account(client)
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    short_response = client.post(
        "/api/auth/face/register",
        headers=headers,
        json={"descriptor": _descriptor(0.0)[:-1]},
    )
    assert short_response.status_code == 422

    text_response = client.post(
        "/api/auth/face/login",
        json={"username": username, "descriptor": ["0"] * 128},
    )
    assert text_response.status_code == 422


def test_face_login_rejects_unregistered_account():
    from main import app

    client = TestClient(app)
    username, _ = _new_account(client)
    response = client.post(
        "/api/auth/face/login",
        json={"username": username, "descriptor": _descriptor(0.0)},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "该账号尚未注册人脸特征"


def test_face_login_rejects_distance_at_or_above_threshold():
    from main import app

    client = TestClient(app)
    username, tokens = _new_account(client)
    register_response = client.post(
        "/api/auth/face/register",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"descriptor": _descriptor(0.0)},
    )
    assert register_response.status_code == 200

    response = client.post(
        "/api/auth/face/login",
        json={"username": username, "descriptor": _descriptor(1.0)},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "人脸验证失败"
