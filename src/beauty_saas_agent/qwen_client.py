from __future__ import annotations

import json
import time
from typing import Callable, Dict, Iterator, List, Optional, TypeVar
from urllib import error, request

from .config import Settings
from .models import ChatMessage


T = TypeVar("T")


class ModelRequestError(RuntimeError):
    """模型请求错误，带可重试标签。"""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = bool(retryable)


class ModelClient:
    """统一模型调用客户端，兼容 OpenAI-API 与 Ollama 两种协议。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def chat(self, messages: List[ChatMessage]) -> str:
        """非流式对话调用。"""
        provider = self.settings.model_provider.strip().lower()
        if provider == "ollama":
            return self._call_with_resilience(lambda: self._chat_with_ollama(messages))
        return self._call_with_resilience(lambda: self._chat_with_openai_compatible(messages))

    def chat_stream(self, messages: List[ChatMessage]) -> Iterator[str]:
        """流式对话调用。"""
        provider = self.settings.model_provider.strip().lower()
        if provider == "ollama":
            yield from self._stream_with_resilience(lambda: self._chat_stream_with_ollama(messages))
            return
        yield from self._stream_with_resilience(lambda: self._chat_stream_with_openai_compatible(messages))

    def list_models(self) -> List[Dict[str, object]]:
        """获取当前 provider 的可用模型列表。"""
        provider = self.settings.model_provider.strip().lower()
        if provider == "ollama":
            return self._call_with_resilience(self._list_ollama_models)
        return self._call_with_resilience(self._list_openai_compatible_models)

    def check_connection(self, prompt: str = "Reply with OK only.") -> Dict[str, object]:
        """连接检查：列模型 + 冒烟对话。"""
        models = self.list_models()
        reply = self.chat([ChatMessage(role="user", content=prompt)])
        return {
            "ok": True,
            "provider": self.settings.model_provider,
            "base_url": self.settings.model_base_url,
            "model": self.settings.model_name,
            "available_models": models,
            "smoke_test_reply": reply,
        }

    def _chat_with_openai_compatible(self, messages: List[ChatMessage]) -> str:
        url = f"{self.settings.model_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.model_name,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.model_api_key:
            headers["Authorization"] = f"Bearer {self.settings.model_api_key}"

        response = self._post_json(url, payload, headers)
        choices = response.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI-compatible response does not include choices.")
        return choices[0].get("message", {}).get("content", "").strip()

    def _chat_stream_with_openai_compatible(self, messages: List[ChatMessage]) -> Iterator[str]:
        url = f"{self.settings.model_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.settings.model_name,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": 0.2,
            "stream": True,
        }
        headers = {"Content-Type": "application/json"}
        if self.settings.model_api_key:
            headers["Authorization"] = f"Bearer {self.settings.model_api_key}"

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url=url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if not line:
                        continue
                    if line == "[DONE]":
                        break
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content is None:
                        content = choices[0].get("message", {}).get("content")
                    text = self._normalize_openai_stream_content(content)
                    if text:
                        yield text
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ModelRequestError(
                f"Model request failed with HTTP {exc.code}: {detail}",
                retryable=self._is_retryable_http_status(exc.code),
            ) from exc
        except error.URLError as exc:
            raise ModelRequestError(f"Failed to reach local model service: {exc}", retryable=True) from exc

    def _chat_with_ollama(self, messages: List[ChatMessage]) -> str:
        url = f"{self.settings.model_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.settings.model_name,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        response = self._post_json(url, payload, headers)
        return response.get("message", {}).get("content", "").strip()

    def _chat_stream_with_ollama(self, messages: List[ChatMessage]) -> Iterator[str]:
        url = f"{self.settings.model_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.settings.model_name,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "stream": True,
        }
        headers = {"Content-Type": "application/json"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url=url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise RuntimeError(f"Ollama stream error: {chunk['error']}")
                    message = chunk.get("message", {})
                    content = message.get("content", "")
                    if content:
                        yield str(content)
                    if chunk.get("done"):
                        break
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ModelRequestError(
                f"Model request failed with HTTP {exc.code}: {detail}",
                retryable=self._is_retryable_http_status(exc.code),
            ) from exc
        except error.URLError as exc:
            raise ModelRequestError(f"Failed to reach local model service: {exc}", retryable=True) from exc

    def _normalize_openai_stream_content(self, content: object) -> str:
        """兼容 OpenAI stream 中 string / content-part 两种返回结构。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    chunks.append(item["text"])
                    continue
                if isinstance(item.get("content"), str):
                    chunks.append(item["content"])
            return "".join(chunks)
        return ""

    def _list_openai_compatible_models(self) -> List[Dict[str, object]]:
        url = f"{self.settings.model_base_url.rstrip('/')}/models"
        headers = {"Content-Type": "application/json"}
        if self.settings.model_api_key:
            headers["Authorization"] = f"Bearer {self.settings.model_api_key}"
        response = self._get_json(url, headers)
        items = response.get("data", [])
        return [
            {
                "name": item.get("id", ""),
                "raw": item,
            }
            for item in items
        ]

    def _list_ollama_models(self) -> List[Dict[str, object]]:
        url = f"{self.settings.model_base_url.rstrip('/')}/api/tags"
        headers = {"Content-Type": "application/json"}
        response = self._get_json(url, headers)
        items = response.get("models", [])
        return [
            {
                "name": item.get("name", ""),
                "size": item.get("size"),
                "family": item.get("details", {}).get("family", ""),
                "parameter_size": item.get("details", {}).get("parameter_size", ""),
                "quantization_level": item.get("details", {}).get("quantization_level", ""),
            }
            for item in items
        ]

    def _post_json(self, url: str, payload: dict, headers: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url=url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ModelRequestError(
                f"Model request failed with HTTP {exc.code}: {detail}",
                retryable=self._is_retryable_http_status(exc.code),
            ) from exc
        except error.URLError as exc:
            raise ModelRequestError(f"Failed to reach local model service: {exc}", retryable=True) from exc

    def _get_json(self, url: str, headers: dict) -> dict:
        req = request.Request(url=url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=self.settings.request_timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ModelRequestError(
                f"Model request failed with HTTP {exc.code}: {detail}",
                retryable=self._is_retryable_http_status(exc.code),
            ) from exc
        except error.URLError as exc:
            raise ModelRequestError(f"Failed to reach local model service: {exc}", retryable=True) from exc

    def _is_retryable_http_status(self, status_code: int) -> bool:
        """判定 HTTP 状态码是否适合重试。"""
        return int(status_code) in {408, 409, 425, 429, 500, 502, 503, 504}

    def _retry_attempts(self) -> int:
        return max(0, int(self.settings.model_retry_attempts))

    def _retry_delay_seconds(self, attempt_index: int) -> float:
        base_ms = max(0, int(self.settings.model_retry_backoff_ms))
        max_ms = max(base_ms, int(self.settings.model_retry_backoff_max_ms))
        delay_ms = min(base_ms * (2**attempt_index), max_ms)
        return float(delay_ms) / 1000.0

    def _circuit_is_open(self) -> bool:
        return self._circuit_open_until > time.monotonic()

    def _ensure_circuit_closed(self) -> None:
        if not self._circuit_is_open():
            return
        retry_after = max(1, int(self._circuit_open_until - time.monotonic()))
        raise RuntimeError(f"Model circuit breaker is open, please retry after {retry_after}s.")

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        threshold = max(1, int(self.settings.model_circuit_fail_threshold))
        if self._consecutive_failures < threshold:
            return
        open_seconds = max(1, int(self.settings.model_circuit_open_seconds))
        self._circuit_open_until = time.monotonic() + float(open_seconds)
        self._consecutive_failures = 0

    def _call_with_resilience(self, operation: Callable[[], T]) -> T:
        self._ensure_circuit_closed()
        last_error: Optional[Exception] = None
        attempts = self._retry_attempts()
        for attempt in range(attempts + 1):
            try:
                result = operation()
                self._record_success()
                return result
            except ModelRequestError as exc:
                last_error = exc
                if attempt >= attempts or not exc.retryable:
                    self._record_failure()
                    raise RuntimeError(str(exc)) from exc
                time.sleep(self._retry_delay_seconds(attempt))
        self._record_failure()
        if last_error is not None:
            raise RuntimeError(str(last_error)) from last_error
        raise RuntimeError("Model call failed unexpectedly.")

    def _stream_with_resilience(self, operation: Callable[[], Iterator[str]]) -> Iterator[str]:
        self._ensure_circuit_closed()
        last_error: Optional[Exception] = None
        attempts = self._retry_attempts()
        for attempt in range(attempts + 1):
            emitted = False
            try:
                for chunk in operation():
                    emitted = True
                    yield chunk
                self._record_success()
                return
            except ModelRequestError as exc:
                last_error = exc
                # 已经输出过分片时，不做重试，避免重复输出污染流式内容。
                if emitted or attempt >= attempts or not exc.retryable:
                    self._record_failure()
                    raise RuntimeError(str(exc)) from exc
                time.sleep(self._retry_delay_seconds(attempt))
        self._record_failure()
        if last_error is not None:
            raise RuntimeError(str(last_error)) from last_error
        raise RuntimeError("Model stream call failed unexpectedly.")


QwenClient = ModelClient
