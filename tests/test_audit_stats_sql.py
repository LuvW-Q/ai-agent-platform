"""
Task 8 — Replace in-memory stats aggregation with SQL CASE WHEN.

Verifies GET /api/smart-audit/messages/stats:
  * With seeded block + replace words, counts map correctly to high/medium/low.
  * With no sensitive words seeded, every message is classified as low.

Uses TestClient + dependency_overrides to bypass JWT and inject a ROOT user.
"""
import os
import time

import pytest
from fastapi.testclient import TestClient

# Importing main triggers Base.metadata.create_all + run_seed() once for the
# test DB, isolating it from the dev database (see tests/conftest.py).
from main import app
from core.security import get_current_user
from core.sensitive_filter import sensitive_filter
from database.session import SessionLocal
from models.message import Message
from models.sensitive_word import SensitiveWord
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
    app.dependency_overrides[get_current_user] = _stub_root_user
    return TestClient(app)


def _wipe(db):
    """Clean slate so seeded counts are deterministic."""
    global _msg_seq
    _msg_seq = 0
    db.query(Message).delete()
    db.query(SensitiveWord).delete()
    db.commit()


_msg_seq = 0


def _add_message(db, content, msg_type="text", status="sent"):
    global _msg_seq
    _msg_seq += 1
    db.add(
        Message(
            msg_id=f"test-{_msg_seq}",
            sender_id=1,
            receiver_id=2,
            content=content,
            msg_type=msg_type,
            status=status,
        )
    )


def test_stats_buckets_match_sql_aggregation():
    """2 high (block: 密码), 1 medium (replace: 私聊), 3 low → total=6."""
    db = SessionLocal()
    try:
        _wipe(db)
        db.add(SensitiveWord(word="密码", replacement="***", action="block"))
        db.add(SensitiveWord(word="私聊", replacement="***", action="replace"))
        db.commit()

        # high (block word "密码")
        _add_message(db, "我的密码是123456")
        _add_message(db, "请把支付密码告诉我")
        # medium (replace word "私聊")
        _add_message(db, "加我微信私聊吧")
        # low (clean)
        _add_message(db, "今天天气真好")
        _add_message(db, "中午吃什么")
        _add_message(db, "下班了")
        # recalled / non-text must be excluded
        _add_message(db, "密码", status="recalled")
        _add_message(db, "密码图片", msg_type="image")
        db.commit()

        # 让 SensitiveFilter 重新加载缓存（seed 写入发生在缓存生效之后）
        sensitive_filter.invalidate_cache()
    finally:
        db.close()

    client = _make_client()
    try:
        resp = client.get("/api/smart-audit/messages/stats")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["total"] == 6, data
        assert data["high"] == 2, data
        assert data["medium"] == 1, data
        assert data["low"] == 3, data
        assert data["high_pct"] == round(2 / 6 * 100, 1), data
        assert data["medium_pct"] == round(1 / 6 * 100, 1), data
        assert data["low_pct"] == round(3 / 6 * 100, 1), data
    finally:
        app.dependency_overrides.clear()


def test_stats_with_no_sensitive_words_returns_all_low():
    """Empty sensitive_words table → every message falls in low bucket."""
    db = SessionLocal()
    try:
        _wipe(db)
        # 三条干净消息，无敏感词
        _add_message(db, "hello world")
        _add_message(db, "你好")
        _add_message(db, "good morning")
        db.commit()

        sensitive_filter.invalidate_cache()
    finally:
        db.close()

    client = _make_client()
    try:
        resp = client.get("/api/smart-audit/messages/stats")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["total"] == 3, data
        assert data["high"] == 0, data
        assert data["medium"] == 0, data
        assert data["low"] == 3, data
        assert data["high_pct"] == 0.0, data
        assert data["medium_pct"] == 0.0, data
        assert data["low_pct"] == 100.0, data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.slow
def test_stats_aggregation_perf_on_1000_messages():
    """1K messages aggregated in a single SQL query — should be < 500ms."""
    db = SessionLocal()
    try:
        _wipe(db)
        db.add(SensitiveWord(word="密码", replacement="***", action="block"))
        db.add(SensitiveWord(word="私聊", replacement="***", action="replace"))
        db.commit()

        for i in range(800):
            _add_message(db, f"普通消息 {i}")
        for i in range(150):
            _add_message(db, f"请私聊我 {i}")
        for i in range(50):
            _add_message(db, f"密码泄漏 {i}")
        db.commit()

        sensitive_filter.invalidate_cache()
    finally:
        db.close()

    client = _make_client()
    try:
        t0 = time.perf_counter()
        resp = client.get("/api/smart-audit/messages/stats")
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 1000, data
        assert data["high"] == 50, data
        assert data["medium"] == 150, data
        assert data["low"] == 800, data
        # 在 CI 时间断言容易抖动，仅在本地保留
        if not os.environ.get("CI"):
            assert elapsed_ms < 500, f"stats took {elapsed_ms:.1f}ms"
    finally:
        app.dependency_overrides.clear()

