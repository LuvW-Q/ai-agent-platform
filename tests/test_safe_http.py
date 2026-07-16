"""安全 HTTP 重定向链测试。"""

import asyncio

import httpx
import pytest
from fastapi import HTTPException

from core.safe_http import request_public_url


def test_redirect_to_private_address_is_blocked(monkeypatch):
    monkeypatch.setattr("core.url_guard.socket.getaddrinfo", lambda *_: [
        (2, 1, 6, "", ("93.184.216.34", 0)),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(HTTPException) as exc:
                await request_public_url(client, "GET", "https://example.com")
            return exc.value

    error = asyncio.run(run())
    assert error.status_code == 400


def test_public_response_is_returned(monkeypatch):
    monkeypatch.setattr("core.url_guard.socket.getaddrinfo", lambda *_: [
        (2, 1, 6, "", ("93.184.216.34", 0)),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await request_public_url(client, "GET", "https://example.com")

    response = asyncio.run(run())
    assert response.status_code == 200
    assert response.json() == {"ok": True}
