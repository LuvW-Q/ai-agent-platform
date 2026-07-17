"""对用户可配置 URL 的统一 HTTP 请求入口。"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException

from core.url_guard import assert_public_url


_REDIRECT_CODES = {301, 302, 303, 307, 308}


async def request_public_url(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_redirects: int = 3,
    **kwargs,
) -> httpx.Response:
    """校验初始目标和每一跳重定向后再发出请求。"""
    current_url = url
    current_method = method.upper()
    request_kwargs = dict(kwargs)

    for redirect_count in range(max_redirects + 1):
        assert_public_url(current_url)
        response = await client.request(
            current_method,
            current_url,
            follow_redirects=False,
            **request_kwargs,
        )
        if response.status_code not in _REDIRECT_CODES:
            return response

        location = response.headers.get("location")
        if not location:
            return response
        if redirect_count >= max_redirects:
            raise HTTPException(400, "URL not allowed: redirect limit exceeded")

        next_url = urljoin(str(response.url), location)
        if urlparse(next_url).hostname != urlparse(current_url).hostname:
            headers = dict(request_kwargs.get("headers") or {})
            headers.pop("Authorization", None)
            headers.pop("authorization", None)
            request_kwargs["headers"] = headers
        if response.status_code == 303:
            current_method = "GET"
            request_kwargs.pop("content", None)
            request_kwargs.pop("json", None)
        current_url = next_url

    raise HTTPException(400, "URL not allowed: redirect limit exceeded")
