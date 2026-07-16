"""
SSRF 防护单元测试 —纯函数测试，不依赖 DB / TestClient。
"""
import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from core.url_guard import assert_public_url


def test_localhost_loopback_blocked():
    with pytest.raises(HTTPException) as exc:
        assert_public_url("http://127.0.0.1")
    assert exc.value.status_code == 400
    assert "private/reserved" in exc.value.detail


def test_localhost_name_blocked():
    # localhost 通常解析到 127.0.0.1 / ::1
    with pytest.raises(HTTPException) as exc:
        assert_public_url("http://localhost")
    assert exc.value.status_code == 400


def test_private_v4_blocked():
    with pytest.raises(HTTPException):
        assert_public_url("http://192.168.1.1")


def test_bad_scheme_blocked():
    with pytest.raises(HTTPException) as exc:
        assert_public_url("ftp://example.com")
    assert "scheme" in exc.value.detail


def test_bypass_env():
    """SSRF_ALLOW_INTERNAL=1 时旁路校验"""
    with patch.dict(os.environ, {"SSRF_ALLOW_INTERNAL": "1"}, clear=False):
        # 不会抛出
        assert_public_url("http://127.0.0.1")


def test_bypass_env_clears_after_unset():
    """确认旁路仅受 env 控制；unset 后仍被拦截"""
    # 这里不修改 env，验证默认行为
    with pytest.raises(HTTPException):
        assert_public_url("http://10.0.0.1")


def test_public_url_ok_or_skip():
    """对外网域名要么通过，要么网络不可达时跳过

    测试环境不一定有外网，所以失败时只要不是 HTTPException(400) 就算通过。
    """
    try:
        assert_public_url("http://example.com")
    except HTTPException as e:
        if e.status_code == 400 and "DNS resolution failed" in e.detail:
            pytest.skip("no network in test env")
        else:
            raise
