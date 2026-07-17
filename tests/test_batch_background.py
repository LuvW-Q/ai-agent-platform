"""
Task 6 — 批量深度采集改为 FastAPI BackgroundTasks 的集成测试。

覆盖：
1. POST /api/dc/batch-deep-collect 立即返回 pending，任务入队后台执行。
2. 通过 mock httpx.AsyncClient.get 避免真实网络请求。
3. 轮询 GET /api/dc/tasks/{task_id} 直至 status == completed。
4. 校验 completed_count/total_count 等于待采集条数。
5. 校验 CollectedData.deep_collected 已被置为 True。
6. 批量上限 100：超过返回 422。
"""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from core.security import get_current_user
from models.collection_task import CollectionTask
from models.data_collection import CollectedData
from models.user import User


def _stub_user(role: str) -> User:
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
    from main import app
    app.dependency_overrides[get_current_user] = lambda: _stub_user(role)
    return TestClient(app)


def _seed_warehouse(db, n: int = 2, keyword: str = "test") -> list[int]:
    """写入 n 条已保存但未深度采集的数据，返回 id 列表。"""
    ids = []
    for i in range(n):
        cd = CollectedData(
            source_id=None,
            source_name="seed",
            keyword=keyword,
            title=f"测试条目-{i}",
            url=f"https://example.com/{i}",
            content="",
            saved=True,
            deep_collected=False,
        )
        db.add(cd)
        db.flush()
        ids.append(cd.id)
    db.commit()
    return ids


def _make_mock_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.status_code = 200
    return resp


def test_batch_deep_collect_runs_in_background(db_session):
    """批量深度采集走 BackgroundTasks，最终完成且 CollectedData 被更新。"""
    ids = _seed_warehouse(db_session, n=2)

    client = _make_client_with_role("root")

    def _fake_request(client, method, url, *args, **kwargs):
        # url 形如 https://example.com/{i}
        idx = url.rsplit("/", 1)[-1]
        return _make_mock_response(f"<html><body>test content {idx}</body></html>")

    with patch(
        "controller.dc_controller.request_public_url",
        new=AsyncMock(side_effect=_fake_request),
    ):
        resp = client.post(
            "/api/dc/batch-deep-collect",
            json={"keyword": "test", "source_ids": []},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["total"] == 2
    assert body["completed"] == 0
    task_id = body["task_id"]

    # TestClient 在 background tasks 完成后才返回响应，故任务应已结束。
    poll = client.get(f"/api/dc/tasks/{task_id}")
    assert poll.status_code == 200
    task = poll.json()
    assert task["status"] == "completed", task["log"]
    assert task["total_count"] == 2
    assert task["completed_count"] == 2

    # 校验 CollectedData 已被标记为 deep_collected
    db_session.expire_all()
    rows = (
        db_session.query(CollectedData)
        .filter(CollectedData.id.in_(ids))
        .all()
    )
    assert len(rows) == 2
    for r in rows:
        assert r.deep_collected is True
        assert "test content" in (r.content or "")


def test_batch_deep_collect_cap_exceeds_100(db_session):
    """超过 100 条时返回 422，且不应为本请求创建任务记录。"""
    keyword = "test-cap-exceeds"
    _seed_warehouse(db_session, n=101, keyword=keyword)

    client = _make_client_with_role("root")

    # 即便入队也应因 422 在后台执行前被拒绝，但仍然 mock 以防意外
    with patch(
        "controller.dc_controller.request_public_url",
        new=AsyncMock(return_value=_make_mock_response("x")),
    ):
        resp = client.post(
            "/api/dc/batch-deep-collect",
            json={"keyword": keyword, "source_ids": []},
        )

    assert resp.status_code == 422, resp.text
    assert "100" in resp.text
    # 没有任务应被创建（针对本关键词）
    tasks = (
        db_session.query(CollectionTask)
        .filter(CollectionTask.keyword == keyword)
        .all()
    )
    db_session.expire_all()
    assert len(tasks) == 0


def test_batch_deep_collect_no_items_completes_empty(db_session):
    """无待采集条目时也应正常入队并最终 completed。"""
    client = _make_client_with_role("root")

    # 不 mock 也会因为没有 item 而不发起 httpx 请求
    resp = client.post(
        "/api/dc/batch-deep-collect",
        json={"keyword": "test-no-items", "source_ids": []},
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]

    poll = client.get(f"/api/dc/tasks/{task_id}")
    task = poll.json()
    assert task["status"] == "completed"
    assert task["total_count"] == 0
    assert task["completed_count"] == 0


def teardown_module(module):
    from main import app
    app.dependency_overrides.clear()
