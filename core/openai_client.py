"""
OpenAI协议统一客户端
基于httpx实现，兼容所有遵循OpenAI协议的模型服务（OpenAI / DeepSeek / 通义千问 / 智谱等）
支持function calling（tools参数），不依赖openai SDK，最大兼容性
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 异常定义
# ---------------------------------------------------------------------------

class OpenAIError(Exception):
    """OpenAI客户端基础异常"""


class OpenAITimeoutError(OpenAIError):
    """请求超时异常"""


class OpenAIRateLimitError(OpenAIError):
    """触发速率限制 (HTTP 429)"""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class OpenAIResponseError(OpenAIError):
    """模型服务返回非2xx状态码"""

    def __init__(self, message: str, status_code: int, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class OpenAIConnectionError(OpenAIError):
    """网络连接异常"""


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

class OpenAIClient:
    """
    OpenAI协议客户端

    使用 httpx 直接调用 /chat/completions 接口，
    可对接任意兼容 OpenAI 协议的模型服务，无需安装 openai SDK。

    用法::

        client = OpenAIClient(
            api_key="sk-xxx",
            endpoint="https://api.openai.com/v1",
            model_name="gpt-4o",
            temperature=0.7,
            max_tokens=2048,
        )
        response = await client.chat_completion(messages, tools=tools)

    也可通过 AIModel 模型实例快速创建::

        client = OpenAIClient.from_model(ai_model)
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model_name: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self.model_name = model_name
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.timeout = float(timeout)
        # 懒加载的持久化 httpx 客户端，复用连接池
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    @property
    def url(self) -> str:
        """chat/completions 完整请求地址"""
        return f"{self.endpoint}/chat/completions"

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        """懒加载复用 httpx.AsyncClient，利用底层连接池减少握手开销"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers=self.headers,
            )
        return self._client

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """构造标准 OpenAI chat/completions 请求体"""
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            # 默认让模型自主决定是否调用工具
            payload.setdefault("tool_choice", "auto")
        # 允许调用方覆盖默认参数（stream / top_p / presence_penalty 等）
        payload.update(kwargs)
        return payload

    # ------------------------------------------------------------------
    # 核心方法
    # ------------------------------------------------------------------

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        调用 chat/completions 接口

        Args:
            messages:  OpenAI 格式消息列表
                       [{"role": "system", "content": "..."},
                        {"role": "user",   "content": "..."}]
            tools:     OpenAI function calling 格式的工具定义列表（可选）
            **kwargs:  额外请求参数，如 stream / top_p / presence_penalty 等

        Returns:
            标准 OpenAI 响应 dict，包含 id / model / choices / usage 等字段

        Raises:
            OpenAITimeoutError:    请求超时
            OpenAIRateLimitError:  触发速率限制 (HTTP 429)
            OpenAIResponseError:   模型服务返回错误状态码
            OpenAIConnectionError: 网络连接失败
            OpenAIError:           其他未知异常
        """
        client = await self._ensure_client()
        payload = self._build_payload(messages, tools, **kwargs)

        logger.debug(
            "[OpenAIClient] POST %s | model=%s | messages=%d | tools=%s",
            self.url,
            self.model_name,
            len(messages),
            len(tools) if tools else 0,
        )

        # ---- 发起请求 ----
        try:
            response = await client.post(self.url, json=payload)
        except httpx.TimeoutException as exc:
            logger.warning("[OpenAIClient] 请求超时: %s", exc)
            raise OpenAITimeoutError(f"请求超时（{self.timeout}s）: {exc}") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.warning("[OpenAIClient] 网络连接失败: %s", exc)
            raise OpenAIConnectionError(f"网络连接失败: {exc}") from exc
        except httpx.HTTPError as exc:
            logger.warning("[OpenAIClient] HTTP请求异常: %s", exc)
            raise OpenAIError(f"HTTP请求异常: {exc}") from exc

        # ---- 处理响应 ----
        # 速率限制
        if response.status_code == 429:
            retry_after_raw = response.headers.get("Retry-After")
            retry_after: float | None = None
            if retry_after_raw:
                try:
                    retry_after = float(retry_after_raw)
                except ValueError:
                    retry_after = None
            logger.warning(
                "[OpenAIClient] 速率限制 (429): retry_after=%s", retry_after
            )
            msg = (
                f"触发速率限制，建议等待 {retry_after}s 后重试"
                if retry_after
                else "触发速率限制，请稍后重试"
            )
            raise OpenAIRateLimitError(msg, retry_after=retry_after)

        # 其他非2xx
        if not response.is_success:
            body = response.text
            logger.warning(
                "[OpenAIClient] 模型服务错误: status=%d, body=%s",
                response.status_code,
                body[:500],
            )
            raise OpenAIResponseError(
                f"模型服务返回错误 (HTTP {response.status_code})",
                status_code=response.status_code,
                response_body=body,
            )

        # 解析 JSON
        try:
            data = response.json()
        except Exception as exc:
            raise OpenAIResponseError(
                f"响应JSON解析失败: {exc}",
                status_code=response.status_code,
                response_body=response.text,
            ) from exc

        choices = data.get("choices") or []
        finish_reason = choices[0].get("finish_reason") if choices else "n/a"
        logger.debug(
            "[OpenAIClient] 响应成功: model=%s, finish=%s, usage=%s",
            data.get("model"),
            finish_reason,
            data.get("usage"),
        )
        return data

    # ------------------------------------------------------------------
    # 便捷方法
    # ------------------------------------------------------------------

    @classmethod
    def from_model(cls, ai_model: Any) -> "OpenAIClient":
        """
        从 AIModel 模型实例快速创建客户端

        Args:
            ai_model: models.ai_model.AIModel 实例
        """
        return cls(
            api_key=ai_model.api_key,
            endpoint=ai_model.endpoint,
            model_name=ai_model.model_name,
            temperature=float(ai_model.temperature),
            max_tokens=int(ai_model.max_tokens),
        )

    @staticmethod
    def extract_content(response: dict[str, Any]) -> str:
        """从标准响应中提取 assistant 文本内容"""
        choices = response.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return message.get("content") or ""

    @staticmethod
    def extract_tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
        """从标准响应中提取 tool_calls 列表"""
        choices = response.get("choices") or []
        if not choices:
            return []
        message = choices[0].get("message") or {}
        return message.get("tool_calls") or []

    # ------------------------------------------------------------------
    # 生命周期管理
    # ------------------------------------------------------------------

    async def close(self):
        """关闭底层 httpx 连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "OpenAIClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
