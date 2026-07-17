"""上传文件类型校验与鉴权下载回归测试。"""

from pathlib import Path

from fastapi.testclient import TestClient

from core.security import get_current_user
from main import app
from models.user import User


def _stub_user() -> User:
    user = User(
        username="upload_user",
        nickname="upload_user",
        email="upload_user@test.local",
        role="USER",
        avatar="",
        signature="",
        is_active=True,
    )
    user.id = 9101
    return user


def _other_user() -> User:
    user = _stub_user()
    user.id = 9102
    user.username = "other_upload_user"
    user.email = "other_upload_user@test.local"
    return user


def test_spoofed_image_is_rejected():
    app.dependency_overrides[get_current_user] = _stub_user
    client = TestClient(app)
    try:
        response = client.post(
            "/api/messages/upload",
            files={"file": ("fake.png", b"not an image", "image/png")},
        )
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "文件内容与扩展名不匹配"
    finally:
        app.dependency_overrides.clear()


def test_valid_image_uses_authenticated_download_route():
    app.dependency_overrides[get_current_user] = _stub_user
    client = TestClient(app)
    uploaded_path = None
    try:
        png = b"\x89PNG\r\n\x1a\n" + b"test-content"
        response = client.post(
            "/api/messages/upload",
            files={"file": ("image.png", png, "image/png")},
        )
        assert response.status_code == 200, response.text
        url = response.json()["url"]
        assert url.startswith("/api/uploads/messages/9101/")
        uploaded_path = Path("uploads") / url.removeprefix("/api/uploads/")

        download = client.get(url)
        assert download.status_code == 200, download.text
        assert download.content == png
        assert download.headers["x-content-type-options"] == "nosniff"
        assert download.headers["content-disposition"].startswith("inline;")
    finally:
        app.dependency_overrides.clear()
        if uploaded_path:
            uploaded_path.unlink(missing_ok=True)


def test_legacy_public_upload_mount_is_removed():
    client = TestClient(app)
    response = client.get("/uploads/nonexistent.png")
    assert response.status_code == 404


def test_unrelated_user_cannot_download_unsent_message_upload():
    app.dependency_overrides[get_current_user] = _stub_user
    client = TestClient(app)
    uploaded_path = None
    try:
        png = b"\x89PNG\r\n\x1a\n" + b"private-content"
        response = client.post(
            "/api/messages/upload",
            files={"file": ("private.png", png, "image/png")},
        )
        assert response.status_code == 200, response.text
        url = response.json()["url"]
        uploaded_path = Path("uploads") / url.removeprefix("/api/uploads/")

        app.dependency_overrides[get_current_user] = _other_user
        forbidden = client.get(url)
        assert forbidden.status_code == 403, forbidden.text
    finally:
        app.dependency_overrides.clear()
        if uploaded_path:
            uploaded_path.unlink(missing_ok=True)
