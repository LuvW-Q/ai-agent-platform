"""
对称加密工具：用 Fernet 对 API key / auth key 等敏感字段做静态加密。

设计要点：
- 密钥来自环境变量 ``APP_SECRET_KEY``；未设置时回退到一个**仅用于开发**的硬编码密钥，
  并打印 warning。生产部署务必设置 ``APP_SECRET_KEY``。
- ``encrypt("")`` 返回 ``""``，``decrypt("")`` 返回 ``""``，
  避免破坏 seed 中 ``auth_key=""`` 这种空字符串约定。
- ``encrypt(None)`` / ``decrypt(None)`` 都返回 ``None``（防御性）。
- ``decrypt`` 在解密失败（InvalidToken 或其它异常）时**原样返回输入**，
  这样 DB 中遗留的明文（例如旧 seed 的 "sk-placeholder"）能继续被读出，
  而不会让启动/loading 流程崩溃。重新写回时会自动加密。
- 不在本模块做迁移：旧明文行通过 decrypt 的优雅降级返回原值，
  下一次写操作会经过 hybrid_property setter 转成密文存回 DB。
"""
from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# 仅用于开发的硬编码 Fernet 密钥（32 字节 url-safe base64）。
# **请勿在生产使用**：通过 APP_SECRET_KEY 环境变量覆盖。
# This is a deterministically generated valid Fernet key for local development only.
# DO NOT reuse in production — set APP_SECRET_KEY in the environment instead.
_DEV_KEY = b"MGAx5eSNSRKyEvpe553H9w0lZ8R2wg5yRTEKwmtaYdE="


def _get_key() -> bytes:
    """返回当前应使用的 Fernet 密钥。优先读 env，缺失时回退到 _DEV_KEY 并告警。"""
    k = os.environ.get("APP_SECRET_KEY")
    if not k:
        logger.warning(
            "APP_SECRET_KEY not set; using dev-only key — NOT SAFE for production"
        )
        return _DEV_KEY
    return k.encode() if isinstance(k, str) else k


def encrypt(plaintext: str | None) -> str | None:
    """加密明文。``None`` → ``None``；``""`` → ``""``；其余返回 Fernet 密文字符串。"""
    if plaintext is None:
        return None
    if plaintext == "":
        return ""
    f = Fernet(_get_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt(cipher: str | None) -> str | None:
    """解密密文。``None`` → ``None``；``""`` → ``""``；解密失败原样返回输入（兼容历史明文）。"""
    if cipher is None:
        return None
    if cipher == "":
        return ""
    try:
        f = Fernet(_get_key())
        return f.decrypt(cipher.encode()).decode()
    except (InvalidToken, Exception):
        # 兼容历史明文：legacy plaintext rows will be returned as-is by the decrypt fallback.
        return cipher
