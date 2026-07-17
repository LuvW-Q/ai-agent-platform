"""验证演示环境的登录、问数、数字员工与大屏核心链路。"""

from __future__ import annotations

import argparse
import json
import time
from urllib.parse import urlsplit

import httpx


def request_json(base_url: str, path: str, *, body=None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.request(
        "POST" if body is not None else "GET",
        base_url + path,
        headers=headers,
        json=body,
        timeout=20,
    )
    if response.is_error:
        raise RuntimeError(f"{path} 返回 HTTP {response.status_code}: {response.text}")
    return response.status_code, response.json()


def wait_until_ready(base_url: str, timeout_seconds: int = 45) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            response = httpx.get(base_url + "/login", timeout=2)
            if response.status_code == 200:
                return
        except (httpx.HTTPError, TimeoutError):
            time.sleep(0.5)
    raise RuntimeError("服务在 45 秒内未就绪")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("--base-url 仅允许本机 http/https 地址")

    wait_until_ready(args.base_url)
    status, tokens = request_json(
        args.base_url,
        "/api/auth/login",
        body={"username": args.username, "password": args.password},
    )
    assert status == 200 and tokens.get("access_token") and tokens.get("refresh_token")
    token = tokens["access_token"]

    _, profile = request_json(args.base_url, "/api/auth/profile", token=token)
    assert profile["username"] == args.username and profile["role"] == "ROOT"

    _, query = request_json(
        args.base_url,
        "/api/query/nl2sql",
        body={"question": "近 7 天采集多少条新闻"},
        token=token,
    )
    assert query.get("explanation") and isinstance(query.get("rows"), list)

    _, agents = request_json(args.base_url, "/api/de/list", token=token)
    assert len(agents) >= 6
    _, reply = request_json(
        args.base_url,
        "/api/de/chat",
        body={
            "agent_id": agents[0]["id"],
            "messages": [{"role": "user", "content": "请简短介绍你的职责"}],
        },
        token=token,
    )
    assert reply.get("reply")

    response = httpx.get(args.base_url + "/screen", timeout=10)
    assert response.status_code == 200 and b"<!DOCTYPE html>" in response.content[:256]

    print(json.dumps({
        "login": "ok",
        "query_rows": len(query["rows"]),
        "published_agents": len(agents),
        "agent_reply": "ok",
        "screen": "ok",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
