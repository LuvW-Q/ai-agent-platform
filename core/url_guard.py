"""
SSRF 防护：在外发 httpx 请求前校验目标 URL。

`assert_public_url(url)` 解析 URL 并拒绝指向私网/环回/保留地址的目标。
通过 `SSRF_ALLOW_INTERNAL=1` 环境变量可在开发环境下旁路该校验，并记录 WARN 日志。
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

from fastapi import HTTPException

from core.config import config

logger = logging.getLogger(__name__)


def _is_blocked(ip: ipaddress._BaseAddress) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True
    # IPv6 唯一本地地址（fc00::/7）和 IPv6 环回（::1）已被 is_private / is_loopback 覆盖，
    # 这里显式再保一次以应对不同 Python 版本的判定差异。
    if isinstance(ip, ipaddress.IPv6Address):
        if ip in ipaddress.IPv6Network("fc00::/7"):
            return True
    return False


def assert_public_url(url: str) -> None:
    """校验 url 是否指向公网地址；否则抛出 HTTPException(400)。

    - 非法 scheme 直接拒绝
    - 直接给 IP 字面量时跳过 DNS 直接判定
    - 通过 DNS 解析后逐个判定解析结果
    - 设置 `SSRF_ALLOW_INTERNAL=1` 可旁路（记录 WARN）
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            400, f"URL not allowed: scheme {parsed.scheme!r} not permitted"
        )

    host = parsed.hostname or ""
    if not host:
        raise HTTPException(400, "URL not allowed: no hostname")
    if parsed.username or parsed.password:
        raise HTTPException(400, "URL not allowed: embedded credentials")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise HTTPException(400, "URL not allowed: invalid port")
    allowed_ports = {
        int(value.strip())
        for value in os.environ.get("SSRF_ALLOWED_PORTS", config.SSRF_ALLOWED_PORTS).split(",")
        if value.strip().isdigit()
    }
    if port not in allowed_ports:
        raise HTTPException(400, f"URL not allowed: port {port} not permitted")

    allowed_hosts = {
        value.strip().lower()
        for value in os.environ.get("SSRF_ALLOWED_HOSTS", config.SSRF_ALLOWED_HOSTS).split(",")
        if value.strip()
    }
    if allowed_hosts and host.lower() not in allowed_hosts:
        raise HTTPException(400, "URL not allowed: hostname is not allowlisted")

    allow_internal = os.environ.get("SSRF_ALLOW_INTERNAL")
    if allow_internal == "1" or (allow_internal is None and config.SSRF_ALLOW_INTERNAL):
        logger.warning("SSRF_ALLOW_INTERNAL=1 — bypassing IP guard for %s", url)
        return

    # 直接 IP 字面量
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if _is_blocked(ip):
            raise HTTPException(400, "URL not allowed: private/reserved IP")
        return

    # DNS 解析
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(400, "URL not allowed: DNS resolution failed")

    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked(ip):
            raise HTTPException(
                400,
                f"URL not allowed: resolves to private/reserved IP {addr}",
            )
