from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import Settings, load_env_file
from .github_skill_importer import GitHubSkillImporter
from .models import ChatMessage, ChatRequest
from .prompt_builder import PromptRuntime


SETTINGS = Settings.from_env()
RUNTIME = PromptRuntime(SETTINGS)
ASSET_ROOT = Path(__file__).resolve().parent / "dashboard_assets"
ENV_FILE_PATH = Path(os.getenv("ENV_FILE", ".env")).expanduser().resolve()
ASYNC_TASK_CANCEL_EVENTS: dict[str, threading.Event] = {}
ASYNC_TASK_CANCEL_LOCK = threading.Lock()
MODEL_MODE_LOCK = threading.Lock()
DEFAULT_MODEL_NAME_DEV = "deepseek-coder-v2:16b"
DEFAULT_MODEL_NAME_HQ = "qwen3.6:35b"


def _resolve_model_mode_settings(env_values: dict[str, str] | None = None) -> dict[str, str]:
    """统一解析模型模式相关配置（支持环境变量兜底）。"""
    values = env_values or {}
    model_name_dev = (
        values.get("MODEL_NAME_DEV")
        or os.getenv("MODEL_NAME_DEV")
        or DEFAULT_MODEL_NAME_DEV
    )
    model_name_hq = (
        values.get("MODEL_NAME_HQ")
        or os.getenv("MODEL_NAME_HQ")
        or DEFAULT_MODEL_NAME_HQ
    )
    model_name = values.get("MODEL_NAME") or SETTINGS.model_name
    raw_mode = (values.get("MODEL_MODE") or os.getenv("MODEL_MODE") or "").strip().lower()
    if raw_mode in {"dev", "hq"}:
        mode = raw_mode
    elif model_name == model_name_dev:
        mode = "dev"
    elif model_name == model_name_hq:
        mode = "hq"
    else:
        mode = "custom"
    return {
        "mode": mode,
        "model_name": model_name,
        "model_name_dev": model_name_dev,
        "model_name_hq": model_name_hq,
    }


def _upsert_env_values(path: Path, updates: dict[str, str]) -> None:
    """更新或追加 .env 键值，保留其他行与注释。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output: list[str] = []
    touched: set[str] = set()
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            output.append(raw_line)
            continue
        key, _ = raw_line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key in updates:
            output.append(f"{normalized_key}={updates[normalized_key]}")
            touched.add(normalized_key)
            continue
        output.append(raw_line)
    for key, value in updates.items():
        if key in touched:
            continue
        output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _read_model_mode_payload() -> dict[str, object]:
    """读取当前模型模式和模型名配置。"""
    env_values = load_env_file(ENV_FILE_PATH)
    mode_settings = _resolve_model_mode_settings(env_values)
    return {
        **mode_settings,
        "provider": SETTINGS.model_provider,
        "base_url": SETTINGS.model_base_url,
        "env_file": str(ENV_FILE_PATH),
    }


def _switch_model_mode(mode: str) -> dict[str, object]:
    """切换 dev/hq 模式并同步到 .env 与当前运行时。"""
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"dev", "hq"}:
        raise ValueError("mode must be 'dev' or 'hq'.")

    with MODEL_MODE_LOCK:
        env_values = load_env_file(ENV_FILE_PATH)
        mode_settings = _resolve_model_mode_settings(env_values)
        target_model = (
            mode_settings["model_name_dev"]
            if normalized_mode == "dev"
            else mode_settings["model_name_hq"]
        )
        _upsert_env_values(
            ENV_FILE_PATH,
            {
                "MODEL_MODE": normalized_mode,
                "MODEL_NAME": target_model,
            },
        )
        os.environ["MODEL_MODE"] = normalized_mode
        os.environ["MODEL_NAME"] = target_model
        SETTINGS.model_name = target_model
        RUNTIME.settings.model_name = target_model
        return _read_model_mode_payload()


class AgentHandler(BaseHTTPRequestHandler):
    """HTTP API 入口，承载任务执行、状态流式推送与运维接口。"""

    server_version = "BeautySaaSAgent/0.1"

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        """发送 JSON 响应（含基础 CORS 头）。"""
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Last-Event-ID")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = HTTPStatus.OK) -> None:
        """发送 HTML 响应。"""
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_headers(self) -> None:
        """发送 SSE 响应头。"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Last-Event-ID")
        self.end_headers()

    def _send_sse_event(self, event_name: str, payload: dict, event_id: int) -> None:
        """写入单条 SSE 事件。"""
        lines = [
            f"id: {event_id}",
            f"event: {event_name}",
        ]
        encoded_payload = json.dumps(payload, ensure_ascii=False)
        for line in encoded_payload.splitlines():
            lines.append(f"data: {line}")
        lines.append("")
        body = "\n".join(lines).encode("utf-8")
        self.wfile.write(body)
        self.wfile.write(b"\n")
        self.wfile.flush()

    def _stream_task_events(self, task_id: str, start_event_id: int) -> None:
        """持续推送任务事件流，直到任务终态或连接断开。"""
        if RUNTIME.task_store.get_task_status(task_id) is None:
            self._send_json({"error": "Task not found"}, status=HTTPStatus.NOT_FOUND)
            return

        self._send_sse_headers()
        cursor = max(0, start_event_id)
        last_heartbeat = time.monotonic()
        terminal_statuses = {"completed", "failed", "blocked", "canceled"}

        try:
            while True:
                events = RUNTIME.task_store.list_events(task_id, after_event_id=cursor, limit=300)
                for event in events:
                    cursor = max(cursor, event.event_id)
                    self._send_sse_event("task_event", asdict(event), cursor)
                    last_heartbeat = time.monotonic()

                status = RUNTIME.task_store.get_task_status(task_id)
                if status is None:
                    self._send_sse_event(
                        "task_terminal",
                        {
                            "task_id": task_id,
                            "status": "missing",
                        },
                        cursor,
                    )
                    return
                if status in terminal_statuses and not events:
                    # 终态且无新事件时发送 task_terminal，前端可安全停止轮询。
                    self._send_sse_event(
                        "task_terminal",
                        {
                            "task_id": task_id,
                            "status": status,
                        },
                        cursor,
                    )
                    return

                now = time.monotonic()
                if (now - last_heartbeat) >= 10:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    last_heartbeat = now
                time.sleep(0.3)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _read_json_body(self) -> dict:
        """读取并解析 JSON 请求体。"""
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        raw_body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(raw_body) if raw_body.strip() else {}

    def _build_chat_request(self, data: dict) -> ChatRequest:
        """把 API 入参组装成统一 ChatRequest 对象。"""
        return ChatRequest(
            task=data["task"],
            version=data["version"],
            workflow=data.get("workflow"),
            skills=data.get("skills", []),
            agents=data.get("agents", []),
            context=data.get("context", {}),
            conversation=[
                ChatMessage(role=item["role"], content=item["content"])
                for item in data.get("conversation", [])
            ],
            execution_mode=data.get("execution_mode", "off"),
            repos=data.get("repos", []),
        )

    def _read_file_snippet(self, path: str, line: int, context: int = 4) -> dict:
        """读取文件目标行附近片段，用于任务详情弹窗。"""
        file_path = Path(path).expanduser()
        if not file_path.exists() or not file_path.is_file():
            return {
                "path": str(file_path),
                "exists": False,
                "line": line,
                "start_line": 0,
                "end_line": 0,
                "lines": [],
            }
        content = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        target_line = max(1, line or 1)
        start_line = max(1, target_line - context)
        end_line = min(len(content), target_line + context)
        lines = [
            {
                "number": index,
                "text": content[index - 1],
                "highlight": index == target_line,
            }
            for index in range(start_line, end_line + 1)
        ]
        return {
            "path": str(file_path),
            "exists": True,
            "line": target_line,
            "start_line": start_line,
            "end_line": end_line,
            "lines": lines,
        }

    def _parse_int(self, raw: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
        """安全解析查询参数中的整数，避免非法入参导致接口 500。"""
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def _bind_cancel_event(self, task_id: str, event: threading.Event) -> None:
        """登记异步任务取消信号。"""
        with ASYNC_TASK_CANCEL_LOCK:
            ASYNC_TASK_CANCEL_EVENTS[task_id] = event

    def _pop_cancel_event(self, task_id: str) -> None:
        """清理异步任务取消信号。"""
        with ASYNC_TASK_CANCEL_LOCK:
            ASYNC_TASK_CANCEL_EVENTS.pop(task_id, None)

    def _get_cancel_event(self, task_id: str) -> threading.Event | None:
        """读取异步任务取消信号。"""
        with ASYNC_TASK_CANCEL_LOCK:
            return ASYNC_TASK_CANCEL_EVENTS.get(task_id)

    def _is_terminal_status(self, status: str | None) -> bool:
        """判断任务状态是否已到终态。"""
        return status in {"completed", "failed", "blocked", "canceled"}

    def do_OPTIONS(self) -> None:  # noqa: N802
        """处理 CORS 预检请求。"""
        self._send_json({"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        """处理 GET 路由。"""
        parsed = urlparse(self.path)

        # 阶段1：基础健康检查与页面入口。
        if parsed.path == "/health":
            self._send_json(
                {
                    "ok": True,
                    "model": SETTINGS.model_name,
                    "provider": SETTINGS.model_provider,
                }
            )
            return

        if parsed.path in ("/", "/dashboard"):
            asset_path = ASSET_ROOT / "index.html"
            self._send_html(asset_path.read_text(encoding="utf-8"))
            return

        # 阶段2：运行时元数据与资源信息查询。
        if parsed.path == "/api/v1/meta":
            self._send_json(RUNTIME.meta())
            return

        if parsed.path == "/api/v1/dashboard/summary":
            summary = RUNTIME.task_store.dashboard_summary()
            summary["skill_plugin_count"] = len(RUNTIME.skill_plugin_registry.list_plugins())
            summary["prompt_count"] = len(RUNTIME.prompt_registry.list_entries())
            summary["repo_count"] = len(RUNTIME.repo_manager.profile.repos)
            self._send_json(summary)
            return

        if parsed.path == "/api/v1/prompts":
            self._send_json(RUNTIME.prompt_registry.meta())
            return

        if parsed.path == "/api/v1/skills/plugins":
            self._send_json(RUNTIME.skill_plugin_registry.meta())
            return

        if parsed.path == "/api/v1/repos/meta":
            self._send_json(RUNTIME.repo_manager.meta())
            return

        if parsed.path == "/api/v1/repos/status":
            query = parse_qs(parsed.query)
            name = query.get("name", [None])[0]
            self._send_json({"items": RUNTIME.repo_manager.repo_status(name=name)})
            return

        if parsed.path == "/api/v1/runtime/processes":
            self._send_json({"items": RUNTIME.repo_manager.list_running_processes()})
            return

        # 阶段3：memory / model / 文件工具接口。
        if parsed.path == "/api/v1/memory":
            query = parse_qs(parsed.query)
            task = query.get("q", [""])[0]
            workflow = query.get("workflow", [""])[0] or None
            repos = [item for item in query.get("repo", []) if item]
            limit = self._parse_int(
                query.get("limit", [str(SETTINGS.memory_recall_limit)])[0],
                default=SETTINGS.memory_recall_limit,
                minimum=1,
                maximum=50,
            )
            self._send_json(
                {
                    "items": RUNTIME.project_memory.recall(
                        task=task,
                        workflow=workflow,
                        repos=repos,
                        limit=limit,
                    ),
                    "meta": RUNTIME.project_memory.meta(),
                }
            )
            return

        if parsed.path == "/api/v1/model/list":
            self._send_json({"items": RUNTIME.client.list_models()})
            return

        if parsed.path == "/api/v1/model/check":
            self._send_json(RUNTIME.client.check_connection())
            return

        if parsed.path == "/api/v1/model/mode":
            with MODEL_MODE_LOCK:
                self._send_json(_read_model_mode_payload())
            return

        if parsed.path == "/api/v1/bug-triage/config":
            self._send_json(RUNTIME.bug_triage_meta())
            return

        if parsed.path == "/api/v1/files/snippet":
            query = parse_qs(parsed.query)
            path = query.get("path", [""])[0]
            line = self._parse_int(query.get("line", ["1"])[0], default=1, minimum=1)
            context = self._parse_int(query.get("context", ["4"])[0], default=4, minimum=0, maximum=50)
            self._send_json(self._read_file_snippet(path=path, line=line, context=context))
            return

        if parsed.path == "/api/v1/files/diff":
            query = parse_qs(parsed.query)
            path = query.get("path", [""])[0]
            context = self._parse_int(query.get("context", ["3"])[0], default=3, minimum=0, maximum=100)
            self._send_json(RUNTIME.repo_manager.read_file_diff(file_path=path, context_lines=context))
            return

        # 阶段4：任务查询接口（列表、详情、事件、SSE）。
        if parsed.path == "/api/v1/tasks":
            query = parse_qs(parsed.query)
            limit = self._parse_int(query.get("limit", ["20"])[0], default=20, minimum=1, maximum=200)
            tasks = RUNTIME.task_store.list_tasks(limit=limit)
            self._send_json({"items": [asdict(item) for item in tasks]})
            return

        if parsed.path.startswith("/api/v1/tasks/"):
            if parsed.path.endswith("/stream"):
                task_id = parsed.path.split("/")[-2]
                query = parse_qs(parsed.query)
                last_event_id = self._parse_int(
                    query.get("last_event_id", ["0"])[0] or "0",
                    default=0,
                    minimum=0,
                )
                if self.headers.get("Last-Event-ID"):
                    # 优先使用 SSE 重连头，让前端断线后可以继续续传。
                    last_event_id = self._parse_int(
                        self.headers.get("Last-Event-ID", "0"),
                        default=last_event_id,
                        minimum=0,
                    )
                self._stream_task_events(task_id, last_event_id)
                return
            if parsed.path.endswith("/events"):
                task_id = parsed.path.split("/")[-2]
                query = parse_qs(parsed.query)
                after_event_id = self._parse_int(
                    query.get("after_event_id", ["0"])[0] or "0",
                    default=0,
                    minimum=0,
                )
                self._send_json(
                    {
                        "items": [
                            asdict(item)
                            for item in RUNTIME.task_store.list_events(task_id, after_event_id=after_event_id)
                        ]
                    }
                )
                return
            task_id = parsed.path.rsplit("/", 1)[-1]
            task = RUNTIME.task_store.get_task(task_id)
            if task is None:
                self._send_json({"error": "Task not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._send_json(task)
            return

        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        """处理 POST 路由。"""
        # 阶段1：Prompt 与插件注册/刷新接口。
        if self.path == "/api/v1/prompts/reload":
            try:
                RUNTIME.reload()
                RUNTIME.repo_manager.reload()
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json({"ok": True, "message": "Prompt reloaded."})
            return

        if self.path == "/api/v1/prompts/register":
            try:
                data = self._read_json_body()
                item = RUNTIME.prompt_registry.register(
                    source_path=data["path"],
                    label=data.get("label"),
                    notes=data.get("notes"),
                )
                RUNTIME.reload()
                self._send_json(asdict(item))
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if self.path == "/api/v1/prompts/activate":
            try:
                data = self._read_json_body()
                item = RUNTIME.prompt_registry.activate(data["prompt_id"])
                RUNTIME.reload()
                self._send_json(asdict(item))
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if self.path == "/api/v1/skills/plugins/register":
            try:
                data = self._read_json_body()
                item = RUNTIME.skill_plugin_registry.register(
                    name=data["name"],
                    source_dir=data["source_dir"],
                    kind=data.get("kind", "local-directory"),
                    manifest_path=data.get("manifest_path", ""),
                    notes=data.get("notes"),
                    owner_agent=data.get("owner_agent", ""),
                    repo=data.get("repo", ""),
                    ref=data.get("ref", ""),
                    source_url=data.get("source_url", ""),
                    import_paths=data.get("import_paths"),
                )
                RUNTIME.reload()
                self._send_json(asdict(item))
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        if self.path == "/api/v1/skills/plugins/import-github":
            try:
                data = self._read_json_body()
                item = GitHubSkillImporter(SETTINGS).import_plugin(
                    name=data["name"],
                    repo=data.get("repo", ""),
                    ref=data.get("ref", "main"),
                    paths=data.get("paths", []),
                    url=data.get("url", ""),
                    owner_agent=data.get("owner_agent", ""),
                    notes=data.get("notes"),
                )
                RUNTIME.reload()
                self._send_json(asdict(item))
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        # 阶段2：仓库与运行进程管理接口。
        if self.path.startswith("/api/v1/repos/sync"):
            try:
                data = self._read_json_body()
                self._send_json({"items": RUNTIME.repo_manager.sync_repos(name=data.get("name"))})
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if self.path == "/api/v1/runtime/processes/stop":
            try:
                data = self._read_json_body()
                repo_name = data.get("repo_name")
                repo_names_raw = data.get("repo_names", [])
                phase = data.get("phase")

                if repo_name is not None and not isinstance(repo_name, str):
                    raise ValueError("repo_name must be a string.")
                if repo_names_raw is not None and not isinstance(repo_names_raw, list):
                    raise ValueError("repo_names must be a string list.")

                repo_names = [name for name in (repo_names_raw or []) if isinstance(name, str) and name]
                items = RUNTIME.repo_manager.stop_running_processes(
                    repo_name=repo_name if isinstance(repo_name, str) and repo_name else None,
                    repo_names=repo_names,
                    phase=phase if isinstance(phase, str) and phase else None,
                )
                remaining = RUNTIME.repo_manager.list_running_processes()
                stopped_count = sum(1 for item in items if item.get("stop_status") in {"stopped", "not_running"})
                failed_count = sum(1 for item in items if item.get("stop_status") == "failed")
                self._send_json(
                    {
                        "items": items,
                        "stopped": stopped_count,
                        "failed": failed_count,
                        "remaining": len(remaining),
                    }
                )
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if self.path == "/api/v1/model/mode":
            try:
                data = self._read_json_body()
                mode = str(data.get("mode", "")).strip().lower()
                payload = _switch_model_mode(mode)
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if self.path == "/api/v1/bug-triage/config":
            try:
                data = self._read_json_body()
                if bool(data.get("reset", False)):
                    payload = RUNTIME.reset_bug_triage_config()
                else:
                    config_payload = data.get("config", data)
                    if not isinstance(config_payload, dict):
                        raise ValueError("config must be an object.")
                    payload = RUNTIME.update_bug_triage_config(config_payload)
                self._send_json(payload)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        parsed = urlparse(self.path)
        path = parsed.path

        # 阶段3：任务取消接口。
        if path.startswith("/api/v1/tasks/") and path.endswith("/cancel"):
            task_id = path[len("/api/v1/tasks/") : -len("/cancel")].strip("/")
            if not task_id:
                self._send_json({"error": "Invalid task_id"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                status = RUNTIME.task_store.get_task_status(task_id)
                if status is None:
                    self._send_json({"error": "Task not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                if self._is_terminal_status(status):
                    self._send_json(
                        {
                            "accepted": False,
                            "task_id": task_id,
                            "status": status,
                            "reason": "Task already reached terminal status.",
                        },
                    )
                    return

                cancel_event = self._get_cancel_event(task_id)
                if cancel_event is None:
                    self._send_json(
                        {
                            "accepted": False,
                            "task_id": task_id,
                            "status": status,
                            "reason": "Cancel handle not found for task.",
                        },
                    )
                    return

                cancel_event.set()
                RUNTIME.task_store.append_event(
                    task_id,
                    "task_cancel_requested",
                    {"source": "api", "status_before": status},
                )
                self._send_json(
                    {
                        "accepted": True,
                        "task_id": task_id,
                        "status": status,
                    },
                    status=HTTPStatus.ACCEPTED,
                )
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        # 阶段4：异步任务接口。
        if path == "/api/v1/chat/async":
            try:
                data = self._read_json_body()
                request = self._build_chat_request(data)
                cancel_event = threading.Event()
                created_event = threading.Event()
                created_state: dict = {}
                error_holder: dict = {}

                def on_task_created(task_state: dict) -> None:
                    task_id = str(task_state.get("task_id", "")).strip()
                    created_state["task_id"] = task_id
                    created_state["status"] = task_state.get("status", "planned")
                    if task_id:
                        self._bind_cancel_event(task_id, cancel_event)
                    created_event.set()

                def runner() -> None:
                    try:
                        RUNTIME.run(request, on_task_created=on_task_created, cancel_event=cancel_event)
                    except Exception as exc:  # pragma: no cover - background defensive path
                        error_holder["error"] = str(exc)
                        task_id = str(created_state.get("task_id", "")).strip()
                        if task_id:
                            snapshot = RUNTIME.task_store.get_task(task_id)
                            if snapshot and snapshot.get("status") in {"planned", "running"}:
                                snapshot["status"] = "failed"
                                snapshot["error_message"] = f"Async runner crashed: {exc}"
                                events = snapshot.get("events")
                                if not isinstance(events, list):
                                    events = []
                                events.append(
                                    asdict(
                                        RUNTIME.task_store.append_event(
                                            task_id,
                                            "task_failed",
                                            {
                                                "source": "async_runner",
                                                "error_message": f"Async runner crashed: {exc}",
                                            },
                                        )
                                    )
                                )
                                snapshot["events"] = events
                                RUNTIME.task_store.save_state(snapshot)
                        self.log_error("Async runner crashed: %s", str(exc))
                    finally:
                        task_id = str(created_state.get("task_id", "")).strip()
                        if task_id:
                            self._pop_cancel_event(task_id)
                        created_event.set()

                threading.Thread(
                    target=runner,
                    name="beauty-saas-agent-async-chat",
                    daemon=True,
                ).start()

                created_event.wait(timeout=2.0)
                if created_state.get("task_id"):
                    self._send_json(
                        {
                            "accepted": True,
                            "task_id": created_state["task_id"],
                            "status": created_state.get("status", "planned"),
                        },
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if error_holder.get("error"):
                    self._send_json(
                        {"error": error_holder["error"]},
                        status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    )
                    return
                self._send_json(
                    {"error": "Async task did not start in time."},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            except KeyError as exc:
                self._send_json(
                    {"error": f"Missing required field: {exc.args[0]}"},
                    status=HTTPStatus.BAD_REQUEST,
                )
            except Exception as exc:  # pragma: no cover - defensive path
                self._send_json(
                    {"error": str(exc)},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            return

        # 阶段5：同步任务接口。
        if path != "/api/v1/chat":
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            data = self._read_json_body()
            request = self._build_chat_request(data)
            response = RUNTIME.run(request)
            self._send_json(asdict(response))
        except KeyError as exc:
            self._send_json(
                {"error": f"Missing required field: {exc.args[0]}"},
                status=HTTPStatus.BAD_REQUEST,
            )
        except Exception as exc:  # pragma: no cover - defensive path
            self._send_json(
                {"error": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )


def run_server() -> None:
    """启动 HTTP 服务。"""
    address = (SETTINGS.agent_http_host, SETTINGS.agent_http_port)
    server = ThreadingHTTPServer(address, AgentHandler)
    print(
        f"Beauty SaaS Agent listening on http://{SETTINGS.agent_http_host}:{SETTINGS.agent_http_port}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    run_server()
