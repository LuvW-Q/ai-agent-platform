"""
敏感词过滤器
从数据库按需加载敏感词，支持替换(replace)和阻断(block)两种策略。
内置 60 秒内存缓存，减少数据库查询。

动作说明:
  - replace: 将敏感词替换为指定文本（默认 "***"）
  - block:   命中即阻断整段文本（返回 blocked=True，由调用方拒绝处理）
"""
from __future__ import annotations

import re
import time
import threading
import logging
from typing import Any

from models.sensitive_word import SensitiveWord

logger = logging.getLogger(__name__)


class SensitiveFilter:
    """敏感词过滤器 —— 支持替换与阻断，带内存缓存"""

    # 缓存刷新间隔（秒）
    CACHE_TTL: int = 60

    def __init__(self):
        # 缓存: [{"word": str, "replacement": str, "action": str}, ...]
        self._cache: list[dict[str, str]] | None = None
        self._loaded_at: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 缓存管理
    # ------------------------------------------------------------------

    def _is_cache_fresh(self) -> bool:
        """缓存是否在有效期内"""
        return self._cache is not None and (time.time() - self._loaded_at) < self.CACHE_TTL

    def _load_from_db(self, db: Any) -> list[dict[str, str]]:
        """从数据库加载全部敏感词"""
        rows = db.query(SensitiveWord).all()
        return [
            {
                "word": row.word,
                "replacement": row.replacement or "***",
                "action": (row.action or "replace").lower(),
            }
            for row in rows
        ]

    def _ensure_cache(self, db: Any) -> list[dict[str, str]]:
        """确保缓存有效，过期则从数据库重新加载（双重检查锁）"""
        if self._is_cache_fresh():
            assert self._cache is not None
            return self._cache

        with self._lock:
            # Double-check: 拿到锁后再次确认，避免重复加载
            if self._is_cache_fresh():
                assert self._cache is not None
                return self._cache

            self._cache = self._load_from_db(db)
            self._loaded_at = time.time()
            logger.debug(
                "[SensitiveFilter] 缓存刷新完成: %d 条敏感词", len(self._cache)
            )
            return self._cache

    def invalidate_cache(self) -> None:
        """手动使缓存失效，下次调用 filter 时重新加载"""
        with self._lock:
            self._cache = None
            self._loaded_at = 0.0
            logger.debug("[SensitiveFilter] 缓存已手动失效")

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    def filter(self, text: str, db: Any) -> tuple[str, bool]:
        """
        过滤敏感词

        Args:
            text: 待过滤文本
            db:   数据库会话（SQLAlchemy Session）

        Returns:
            (filtered_text, blocked)
            - blocked=True  → 文本包含阻断类敏感词，应拒绝处理。
                              filtered_text 为原始文本（不做替换）。
            - blocked=False → 文本通过，敏感词已被替换。
                              filtered_text 为过滤后的文本。
        """
        if not text or not isinstance(text, str):
            return (text or "", False)

        words = self._ensure_cache(db)
        if not words:
            return (text, False)

        # 第一遍: 检查阻断类敏感词，命中即返回
        for w in words:
            if w["action"] == "block":
                if re.search(re.escape(w["word"]), text, re.IGNORECASE):
                    logger.info(
                        "[SensitiveFilter] 文本被阻断: 命中敏感词 '%s'", w["word"]
                    )
                    return (text, True)

        # 第二遍: 替换替换类敏感词
        filtered = text
        for w in words:
            if w["action"] == "replace":
                filtered = re.sub(
                    re.escape(w["word"]),
                    w["replacement"],
                    filtered,
                    flags=re.IGNORECASE,
                )

        if filtered != text:
            logger.debug("[SensitiveFilter] 文本已过滤（替换敏感词）")

        return (filtered, False)


# 全局单例
sensitive_filter = SensitiveFilter()
