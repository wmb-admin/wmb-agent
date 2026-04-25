from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


def load_env_file(path: str | Path = ".env") -> Dict[str, str]:
    """读取 .env 风格配置文件，仅解析 `KEY=VALUE` 结构。"""
    env_path = Path(path)
    values: Dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


@dataclass
class Settings:
    """运行时统一配置对象。"""
    prompt_docx_path: str
    model_provider: str
    model_base_url: str
    model_name: str
    model_api_key: str
    agent_http_host: str
    agent_http_port: int
    request_timeout: int
    task_storage_dir: str
    task_sqlite_path: str
    workspace_profile_path: str
    workspace_secrets_path: str
    prompt_registry_path: str
    skill_plugin_registry_path: str
    skill_import_root: str
    workflow_preset_path: str
    bug_triage_config_path: str = ""
    memory_enabled: bool = False
    memory_mysql_bin: str = "/Applications/ServBay/bin/mysql"
    memory_mysql_host: str = "127.0.0.1"
    memory_mysql_port: int = 3306
    memory_mysql_user: str = "root"
    memory_mysql_password: str = "123456"
    memory_mysql_database: str = "wmb_agent_memory"
    memory_recall_limit: int = 6
    memory_fetch_limit: int = 200
    model_retry_attempts: int = 2
    model_retry_backoff_ms: int = 400
    model_retry_backoff_max_ms: int = 3000
    model_circuit_fail_threshold: int = 3
    model_circuit_open_seconds: int = 20
    task_auto_cleanup: bool = True
    task_retention_days: int = 30
    task_event_retention_days: int = 30
    task_max_runs: int = 2000
    task_archive_pruned: bool = True

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        """按“环境变量优先，其次 .env 文件”的顺序加载配置。"""
        env_values = load_env_file(env_file)

        def get_any(names: tuple[str, ...], default: str) -> str:
            # 兼容历史变量名：传入候选名元组，命中任意一个即可。
            for name in names:
                value = os.getenv(name, env_values.get(name))
                if value is not None:
                    return value
            return default

        def get_int(names: tuple[str, ...], default: int) -> int:
            """安全解析整数配置，异常时回退默认值。"""
            raw = get_any(names, str(default))
            try:
                return int(raw)
            except ValueError:
                return default

        def get_bool(names: tuple[str, ...], default: bool) -> bool:
            """解析布尔配置，支持常见真值/假值写法。"""
            raw = get_any(names, "1" if default else "0").strip().lower()
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
            return default

        return cls(
            prompt_docx_path=get_any(
                ("PROMPT_DOCX_PATH",),
                "/Users/wmb/yuese/files/agent/美业SaaS自动迭代智能体完整版Prompt.docx",
            ),
            model_provider=get_any(("MODEL_PROVIDER", "QWEN_PROVIDER"), "openai-compatible"),
            model_base_url=get_any(("MODEL_BASE_URL", "QWEN_BASE_URL"), "http://127.0.0.1:8000/v1"),
            model_name=get_any(("MODEL_NAME", "QWEN_MODEL"), "qwen-v2"),
            model_api_key=get_any(("MODEL_API_KEY", "QWEN_API_KEY"), ""),
            agent_http_host=get_any(("AGENT_HTTP_HOST",), "127.0.0.1"),
            agent_http_port=int(get_any(("AGENT_HTTP_PORT",), "8787")),
            request_timeout=int(get_any(("AGENT_REQUEST_TIMEOUT",), "120")),
            task_storage_dir=get_any(("TASK_STORAGE_DIR",), ".data/tasks"),
            task_sqlite_path=get_any(("TASK_SQLITE_PATH",), ".data/tasks/task_runs.sqlite3"),
            workspace_profile_path=get_any(("WORKSPACE_PROFILE_PATH",), ".agent/workspace-profile.local.json"),
            workspace_secrets_path=get_any(("WORKSPACE_SECRETS_PATH",), ".agent/workspace-secrets.local.json"),
            prompt_registry_path=get_any(("PROMPT_REGISTRY_PATH",), ".agent/prompt-registry.local.json"),
            skill_plugin_registry_path=get_any(("SKILL_PLUGIN_REGISTRY_PATH",), ".agent/skill-plugins.local.json"),
            skill_import_root=get_any(("SKILL_IMPORT_ROOT",), "skills/imported"),
            workflow_preset_path=get_any(("WORKFLOW_PRESET_PATH",), ".agent/workflow-presets.local.json"),
            bug_triage_config_path=get_any(("BUG_TRIAGE_CONFIG_PATH",), ".agent/bug-triage-rules.local.json"),
            memory_enabled=get_bool(("MEMORY_ENABLED",), True),
            memory_mysql_bin=get_any(("MEMORY_MYSQL_BIN",), "/Applications/ServBay/bin/mysql"),
            memory_mysql_host=get_any(("MEMORY_MYSQL_HOST",), "127.0.0.1"),
            memory_mysql_port=get_int(("MEMORY_MYSQL_PORT",), 3306),
            memory_mysql_user=get_any(("MEMORY_MYSQL_USER",), "root"),
            memory_mysql_password=get_any(("MEMORY_MYSQL_PASSWORD",), "123456"),
            memory_mysql_database=get_any(("MEMORY_MYSQL_DATABASE",), "wmb_agent_memory"),
            memory_recall_limit=get_int(("MEMORY_RECALL_LIMIT",), 6),
            memory_fetch_limit=get_int(("MEMORY_FETCH_LIMIT",), 200),
            model_retry_attempts=get_int(("MODEL_RETRY_ATTEMPTS",), 2),
            model_retry_backoff_ms=get_int(("MODEL_RETRY_BACKOFF_MS",), 400),
            model_retry_backoff_max_ms=get_int(("MODEL_RETRY_BACKOFF_MAX_MS",), 3000),
            model_circuit_fail_threshold=get_int(("MODEL_CIRCUIT_FAIL_THRESHOLD",), 3),
            model_circuit_open_seconds=get_int(("MODEL_CIRCUIT_OPEN_SECONDS",), 20),
            task_auto_cleanup=get_bool(("TASK_AUTO_CLEANUP",), True),
            task_retention_days=get_int(("TASK_RETENTION_DAYS",), 30),
            task_event_retention_days=get_int(("TASK_EVENT_RETENTION_DAYS",), 30),
            task_max_runs=get_int(("TASK_MAX_RUNS",), 2000),
            task_archive_pruned=get_bool(("TASK_ARCHIVE_PRUNED",), True),
        )
