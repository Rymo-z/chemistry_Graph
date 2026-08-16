"""LLM 客户端封装（OpenAI 兼容：OpenAI / Azure / vLLM / Ollama，单例）。

通过 `.env` 的 `LLM_API_BASE` 切换后端：
- OpenAI 官方：https://api.openai.com/v1
- 本地 vLLM：http://localhost:8000/v1（api_key 填 EMPTY）
- Azure：填 Azure 的 OpenAI 兼容端点

对外提供 `chat` / `chat_json` / `complete` 三个稳定方法。
"""
from __future__ import annotations

import json
import threading
from typing import Any, Optional

from openai import OpenAI

from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)


class LLMClient:
    """OpenAI 兼容客户端单例，懒加载，线程安全。

    `_instance` 仅在 `_init_client()` 完成后才发布，避免并发线程拿到
    尚未初始化完成的半成品（`.__new__` 里先赋值再初始化会产生该竞态）。
    """

    _instance: Optional["LLMClient"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "LLMClient":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_client()
                    cls._instance = inst
        return cls._instance

    def _init_client(self) -> None:
        self.api_base: str = settings.LLM_API_BASE
        # 本地 vLLM/Ollama 对 api_key 不敏感，空值兜底为 EMPTY
        self.api_key: str = settings.LLM_API_KEY or "EMPTY"
        self.model: str = settings.LLM_MODEL
        self.temperature: float = settings.LLM_TEMPERATURE
        self.timeout: int = settings.LLM_TIMEOUT
        self.disable_thinking: bool = settings.LLM_DISABLE_THINKING
        self.client = OpenAI(base_url=self.api_base, api_key=self.api_key, timeout=self.timeout)
        logger.info("LLM 客户端初始化完成 base=%s model=%s", self.api_base, self.model)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> str:
        """基础对话接口，返回模型输出文本。

        Args:
            messages: OpenAI 格式消息列表。
            temperature: 覆盖默认温度（None 时用 .env 配置）。
            max_tokens: 最大生成 token 数。
            json_mode: 请求结构化 JSON 输出（部分本地模型不支持时会降级）。
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        # 关闭思考：推理模型会把 token 烧在 reasoning_content 上导致 content 为空。
        # 部分端点不认该参数（如 OpenAI 官方），失败则自动退回不带该参数重试。
        if self.disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            if self.disable_thinking and "extra_body" in kwargs:
                logger.warning("端点不支持关闭思考，重试: %s", str(exc)[:120])
                kwargs.pop("extra_body")
                try:
                    response = self.client.chat.completions.create(**kwargs)
                    return response.choices[0].message.content or ""
                except Exception as exc2:  # noqa: BLE001
                    logger.error("LLM 调用失败: %s", exc2)
                    raise
            logger.error("LLM 调用失败: %s", exc)
            raise

    def _chat_for_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """获取 chat 文本：json_mode 不可用/返回空时自动降级普通模式。"""
        try:
            content = self.chat(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True)
        except Exception:  # noqa: BLE001
            logger.warning("json_mode 不可用，降级为普通模式解析")
            content = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        # 部分本地/兼容模型对 response_format 静默返回空内容（而非抛错），
        # 此时也应降级普通模式，否则空串无法解析为 JSON。
        if not content or not content.strip():
            logger.warning("json_mode 返回空内容，降级为普通模式解析")
            content = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return content

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> dict[str, Any]:
        """对话并要求返回可解析的 JSON 对象（解析失败则抛出 ValueError）。

        兼容不支持 response_format 的本地模型：json_mode 失败后自动降级普通模式再解析。
        输出超限导致 JSON 截断时，自动提高 max_tokens 重试一次。
        """
        content = self._chat_for_json(messages, temperature=temperature, max_tokens=max_tokens)
        try:
            return self._safe_parse_json(content)
        except (ValueError, json.JSONDecodeError):
            retry_tokens = max(max_tokens * 2, 10000)
            logger.warning("JSON 解析失败（可能截断），提高 max_tokens=%d 重试一次", retry_tokens)
            content = self._chat_for_json(messages, temperature=temperature, max_tokens=retry_tokens)
            return self._safe_parse_json(content)

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 2000,
    ) -> str:
        """简化单轮问答。"""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)

    # ------------------------------------------------------------------
    # 流式接口
    # ------------------------------------------------------------------
    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int = 2000,
        json_mode: bool = False,
    ) -> Any:
        """流式对话生成器：逐增量 yield 模型输出文本。

        参数同 `chat()`，仅将 `stream=True` 传入 create；失败时的
        extra_body（关闭思考）降级重试逻辑与 `chat()` 保持一致。
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            response = self.client.chat.completions.create(stream=True, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if self.disable_thinking and "extra_body" in kwargs:
                logger.warning("端点不支持关闭思考（流式），重试: %s", str(exc)[:120])
                kwargs.pop("extra_body")
                try:
                    response = self.client.chat.completions.create(stream=True, **kwargs)
                except Exception as exc2:  # noqa: BLE001
                    logger.error("流式 LLM 调用失败: %s", exc2)
                    raise
            else:
                logger.error("流式 LLM 调用失败: %s", exc)
                raise
        for chunk in response:
            choices = chunk.choices or []
            if choices and choices[0].delta and choices[0].delta.content:
                yield choices[0].delta.content

    def complete_stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 2000,
    ) -> Any:
        """简化单轮问答的流式版本。"""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        yield from self.stream(messages, temperature=temperature, max_tokens=max_tokens)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_parse_json(text: str) -> dict[str, Any]:
        """宽容解析 JSON：容忍 markdown 代码块包裹、前后杂音。"""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip().strip("`").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if 0 <= start < end:
                return json.loads(cleaned[start : end + 1])
            raise ValueError(f"LLM 返回内容无法解析为 JSON: {text[:200]}")


def get_llm() -> LLMClient:
    """获取全局 LLM 客户端单例。"""
    return LLMClient()
