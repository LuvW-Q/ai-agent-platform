"""
CORS 配置测试：验证中间件使用配置的源（非通配符）响应预检请求。
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cors_app(monkeypatch):
    """重新加载 main，使其读取测试用的 CORS_ORIGINS。"""
    test_origin = "http://test.example:1234"
    monkeypatch.setenv("CORS_ORIGINS", test_origin)
    # SQL 必须指向测试库（与 conftest 保持一致）
    if "SQLITE_URL" not in os.environ:
        monkeypatch.setenv("SQLITE_URL", f"sqlite:///data_outlook_v2.test.db")

    import main
    original_origins = main.config.CORS_ORIGINS
    main.config.CORS_ORIGINS = test_origin
    importlib.reload(main)
    yield main.app
    # 还原以避免污染其他测试模块
    main.config.CORS_ORIGINS = original_origins
    importlib.reload(main)


def test_cors_preflight_echoes_configured_origin(cors_app):
    client = TestClient(cors_app)
    headers = {
        "Origin": "http://test.example:1234",
        "Access-Control-Request-Method": "GET",
    }
    resp = client.options("/any-path", headers=headers)
    assert resp.status_code in (200, 404)
    assert resp.headers.get("Access-Control-Allow-Origin") == "http://test.example:1234"
