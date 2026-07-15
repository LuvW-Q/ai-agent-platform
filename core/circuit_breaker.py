"""
技能熔断器 (Circuit Breaker)
实时跟踪每个技能的调用失败情况，连续失败达到阈值后自动熔断（禁用），
冷却期过后自动恢复，无需数据库依赖。

熔断策略:
  - 1 分钟内失败 5 次 → 触发熔断
  - 熔断后冷却 10 分钟，期间该技能被禁用
  - 冷却期结束自动恢复（半开状态），下次调用若成功则完全重置
  - 调用成功时立即清除失败计数

数据结构:
  _state[skill_id] = {
      "failures":   [timestamp, ...],   # 滚动窗口内的失败时间戳
      "tripped_at": timestamp | None,    # 熔断触发时间
  }
"""
from __future__ import annotations

import time
import threading
import logging

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """技能熔断器 —— 纯内存实现，线程安全"""

    # 1 分钟内失败 5 次触发熔断
    FAILURE_THRESHOLD: int = 5
    FAILURE_WINDOW: int = 60          # 失败计数窗口（秒）
    COOLDOWN_DURATION: int = 600      # 熔断冷却时间（10 分钟，秒）

    def __init__(self):
        # skill_id → {"failures": [float], "tripped_at": float | None}
        self._state: dict[int | str, dict] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_state(self, skill_id: int | str) -> dict:
        """获取或初始化技能状态"""
        if skill_id not in self._state:
            self._state[skill_id] = {"failures": [], "tripped_at": None}
        return self._state[skill_id]

    @staticmethod
    def _prune_failures(failures: list[float], now: float) -> list[float]:
        """清理超出失败窗口的时间戳"""
        cutoff = now - CircuitBreaker.FAILURE_WINDOW
        return [ts for ts in failures if ts >= cutoff]

    def _check_and_trip(self, state: dict, now: float) -> bool:
        """检查失败计数是否达到阈值，达到则触发熔断"""
        state["failures"] = self._prune_failures(state["failures"], now)
        if (
            len(state["failures"]) >= self.FAILURE_THRESHOLD
            and state["tripped_at"] is None
        ):
            state["tripped_at"] = now
            logger.warning(
                "[CircuitBreaker] 熔断触发: %d 次失败 / %ds 窗口",
                len(state["failures"]),
                self.FAILURE_WINDOW,
            )
            return True
        return False

    def _check_cooldown(self, state: dict, now: float) -> bool:
        """检查熔断是否已过冷却期，过期则自动恢复"""
        if state["tripped_at"] is None:
            return False
        elapsed = now - state["tripped_at"]
        if elapsed >= self.COOLDOWN_DURATION:
            # 冷却结束，重置进入半开状态
            state["tripped_at"] = None
            state["failures"] = []
            logger.info("[CircuitBreaker] 冷却结束，技能恢复（半开）")
            return False
        return True

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def record_failure(self, skill_id: int | str) -> None:
        """
        记录一次调用失败

        Args:
            skill_id: 技能 ID
        """
        with self._lock:
            state = self._get_state(skill_id)
            now = time.time()
            state["failures"].append(now)
            state["failures"] = self._prune_failures(state["failures"], now)
            self._check_and_trip(state, now)
            logger.debug(
                "[CircuitBreaker] skill=%s 记录失败，当前窗口内 %d/%d",
                skill_id,
                len(state["failures"]),
                self.FAILURE_THRESHOLD,
            )

    def record_success(self, skill_id: int | str) -> None:
        """
        记录一次调用成功 —— 清除失败计数并解除熔断

        Args:
            skill_id: 技能 ID
        """
        with self._lock:
            if skill_id in self._state:
                self._state[skill_id] = {"failures": [], "tripped_at": None}
                logger.debug("[CircuitBreaker] skill=%s 成功，状态已重置", skill_id)

    def is_tripped(self, skill_id: int | str) -> bool:
        """
        判断技能是否处于熔断状态

        逻辑:
          1. 若已熔断且冷却未过 → True
          2. 若已熔断且冷却已过 → 自动重置，再检查失败计数
          3. 若未熔断 → 检查失败计数是否达到阈值

        Args:
            skill_id: 技能 ID

        Returns:
            True 表示技能已被熔断（应拒绝调用）
        """
        with self._lock:
            state = self._get_state(skill_id)
            now = time.time()

            # 1. 检查冷却期
            if self._check_cooldown(state, now):
                return True

            # 2. 冷却已过或未熔断，检查是否需要触发
            self._check_and_trip(state, now)

            return state["tripped_at"] is not None

    def get_status(self, skill_id: int | str) -> dict:
        """
        获取技能熔断状态

        Args:
            skill_id: 技能 ID

        Returns:
            {"tripped": bool, "remaining_time": int}
            - tripped:         是否处于熔断状态
            - remaining_time:  剩余冷却时间（秒），未熔断时为 0
        """
        with self._lock:
            state = self._get_state(skill_id)
            now = time.time()

            # 检查冷却期是否已过
            if self._check_cooldown(state, now):
                # 仍在冷却期
                elapsed = now - state["tripped_at"]
                remaining = max(0, int(self.COOLDOWN_DURATION - elapsed))
                return {"tripped": True, "remaining_time": remaining}

            # 冷却已过，检查是否需要重新触发
            self._check_and_trip(state, now)

            if state["tripped_at"] is not None:
                elapsed = now - state["tripped_at"]
                remaining = max(0, int(self.COOLDOWN_DURATION - elapsed))
                return {"tripped": True, "remaining_time": remaining}

            return {"tripped": False, "remaining_time": 0}

    def reset(self, skill_id: int | str) -> None:
        """手动重置指定技能的熔断状态"""
        with self._lock:
            if skill_id in self._state:
                self._state[skill_id] = {"failures": [], "tripped_at": None}
                logger.info("[CircuitBreaker] skill=%s 已手动重置", skill_id)

    def reset_all(self) -> None:
        """重置所有技能的熔断状态"""
        with self._lock:
            self._state.clear()
            logger.info("[CircuitBreaker] 所有技能状态已重置")


# 全局单例
circuit_breaker = CircuitBreaker()
