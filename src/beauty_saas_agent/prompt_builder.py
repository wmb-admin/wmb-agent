from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from .agent_planner import build_execution_plan
from .agent_registry import AGENT_EXECUTION_ORDER, AGENT_REGISTRY
from .bug_triage_config import (
    load_bug_triage_config,
    reset_bug_triage_config,
    save_bug_triage_config,
)
from .config import Settings
from .docx_loader import load_docx_text
from .execution_diagnostics import analyze_command_output
from .models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ExecutionCommandResult,
    ExecutionGateResult,
    ExecutionLocation,
    ExecutionRecommendation,
    HandoffRecord,
    PromptDefinition,
)
from .plugin_skill_loader import merge_plugin_skills
from .prompt_registry import PromptRegistry
from .prompt_parser import parse_prompt_definition
from .project_memory import ProjectMemoryService
from .qwen_client import ModelClient
from .repo_manager import RepoManager
from .skill_plugin_registry import SkillPluginRegistry
from .task_store import TaskStore
from .workflows import load_workflow_catalog

START_TASK_KEYWORDS = [
    "启动",
    "拉起",
    "跑起来",
    "运行项目",
    "运行前端",
    "运行后端",
    "启动前端",
    "启动后端",
    "启动项目",
    "start the project",
    "start frontend",
    "start backend",
    "run frontend",
    "run backend",
]

FULLSTACK_REPO_KEYWORDS = ["前后端", "前后端项目", "frontend backend", "backend frontend", "full stack"]
FRONTEND_REPO_KEYWORDS = ["前端", "frontend", "web", "ui", "页面", "vite", "pnpm"]
BACKEND_REPO_KEYWORDS = ["后端", "backend", "api", "service", "server", "gateway", "spring", "maven"]


class TaskCancelledError(RuntimeError):
    """任务被用户主动取消。"""


class PromptRuntime:
    """运行时核心编排器：负责计划、执行、流式输出与持久化。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.prompt_registry = PromptRegistry(settings)
        self.skill_plugin_registry = SkillPluginRegistry(settings)
        self.workflow_presets, self.workflow_agent_presets, self.workflow_preset_path = load_workflow_catalog(settings)
        bug_triage_path = self._resolve_bug_triage_config_path()
        self.bug_triage_config, self.bug_triage_config_path = load_bug_triage_config(bug_triage_path)
        self.definition = self._load_definition()
        self.client = ModelClient(settings)
        self.task_store = TaskStore(settings)
        self.repo_manager = RepoManager(settings)
        self.project_memory = ProjectMemoryService(settings)

    def _load_definition(self) -> PromptDefinition:
        """加载当前激活 Prompt，并合并插件技能。"""
        active_prompt = self.prompt_registry.get_active_entry()
        raw_text = load_docx_text(Path(active_prompt.source_path))
        definition = parse_prompt_definition(raw_text)
        return merge_plugin_skills(definition, self.skill_plugin_registry.list_active_plugins())

    def reload(self) -> None:
        """热重载 Prompt、插件、workflow 与 memory 服务。"""
        self.prompt_registry = PromptRegistry(self.settings)
        self.skill_plugin_registry = SkillPluginRegistry(self.settings)
        self.workflow_presets, self.workflow_agent_presets, self.workflow_preset_path = load_workflow_catalog(
            self.settings
        )
        bug_triage_path = self._resolve_bug_triage_config_path()
        self.bug_triage_config, self.bug_triage_config_path = load_bug_triage_config(bug_triage_path)
        self.definition = self._load_definition()
        self.project_memory = ProjectMemoryService(self.settings)

    def _resolve_bug_triage_config_path(self) -> str:
        path = (self.settings.bug_triage_config_path or "").strip()
        if path:
            return path
        workflow_path = Path(self.settings.workflow_preset_path).expanduser()
        return str(workflow_path.with_name("bug-triage-rules.local.json"))

    def resolve_skills(self, workflow: str | None, requested_skills: List[str]) -> List[str]:
        """合并 workflow 默认技能与请求技能，并按定义过滤去重。"""
        merged: List[str] = []
        if workflow:
            merged.extend(self.workflow_presets.get(workflow, []))
        merged.extend(requested_skills)

        seen = set()
        valid_skills = []
        for skill in merged:
            if skill in self.definition.skills and skill not in seen:
                seen.add(skill)
                valid_skills.append(skill)
        return valid_skills

    def build_execution_plan(self, request: ChatRequest):
        """基于请求生成 agent 执行链路。"""
        resolved_skills = self.resolve_skills(request.workflow, request.skills)
        return build_execution_plan(
            workflow=request.workflow,
            requested_agents=request.agents,
            resolved_skills=resolved_skills,
            explicit_skills=[skill for skill in request.skills if skill in self.definition.skills],
            skill_owner_overrides=self.skill_owner_overrides(),
            workflow_agent_presets=self.workflow_agent_presets,
        )

    def skill_owner_overrides(self) -> Dict[str, str]:
        """从技能定义读取 owner 覆盖关系。"""
        return {
            name: skill.owner_agent
            for name, skill in self.definition.skills.items()
            if skill.owner_agent
        }

    def resolve_execution_mode(self, request: ChatRequest) -> str:
        """解析最终执行模式，并按任务语义自动推断 start/off。"""
        mode = (request.execution_mode or "off").strip().lower()
        if mode in {"off", "status", "build", "test", "validate", "start"}:
            if mode != "off":
                return mode
            if self._task_requests_startup(request):
                return "start"
            return mode
        return "start" if self._task_requests_startup(request) else "off"

    def apply_runtime_defaults(self, request: ChatRequest) -> ChatRequest:
        """补齐缺省 workflow/execution/repo，降低手工输入成本。"""
        workflow = request.workflow
        execution_mode = (request.execution_mode or "off").strip().lower() or "off"
        repos = list(dict.fromkeys(request.repos))
        context = dict(request.context)
        defaults_applied: Dict[str, object] = {}

        if not workflow and not request.agents and not request.skills:
            if self._task_looks_like_bug(request) and "bug_fix" in self.workflow_presets:
                workflow = "bug_fix"
                defaults_applied["workflow"] = "bug_fix"
            elif "full_iteration" in self.workflow_presets:
                workflow = "full_iteration"
                defaults_applied["workflow"] = "full_iteration"

        if execution_mode == "off" and not self._task_requests_startup(request):
            execution_mode = "validate"
            defaults_applied["execution_mode"] = "validate"

        if not repos and execution_mode != "off":
            configured_repo_names = [repo.name for repo in self.repo_manager.profile.repos]
            preferred = [name for name in ["backend", "frontend"] if name in configured_repo_names]
            if preferred:
                repos = preferred
            elif configured_repo_names:
                repos = configured_repo_names[:2]
            if repos:
                defaults_applied["repos"] = list(repos)

        if defaults_applied:
            # 记录自动补全细节，便于前端和日志解释“为什么这么跑”。
            context["runtime_defaults"] = defaults_applied

        return replace(
            request,
            workflow=workflow,
            execution_mode=execution_mode,
            repos=repos,
            context=context,
        )

    def infer_execution_repos(self, request: ChatRequest) -> List[str]:
        """从任务文本中推断应执行的仓库范围。"""
        if request.repos:
            return list(dict.fromkeys(request.repos))
        text = self._execution_hint_text(request)
        if any(keyword in text for keyword in FULLSTACK_REPO_KEYWORDS):
            return ["backend", "frontend"]
        wants_frontend = any(keyword in text for keyword in FRONTEND_REPO_KEYWORDS)
        wants_backend = any(keyword in text for keyword in BACKEND_REPO_KEYWORDS)
        if wants_frontend and wants_backend:
            return ["backend", "frontend"]
        if wants_backend:
            return ["backend"]
        if wants_frontend:
            return ["frontend"]
        return []

    def _task_requests_startup(self, request: ChatRequest) -> bool:
        text = self._execution_hint_text(request)
        return any(keyword in text for keyword in START_TASK_KEYWORDS)

    def _execution_hint_text(self, request: ChatRequest) -> str:
        context_text = json.dumps(request.context, ensure_ascii=False) if request.context else ""
        return f"{request.task} {context_text}".lower()

    def _bug_triage_rules(self) -> Dict[str, object]:
        rules = self.bug_triage_config
        return rules if isinstance(rules, dict) else {}

    def _bug_triage_enabled(self) -> bool:
        return bool(self._bug_triage_rules().get("enabled", True))

    def _bug_keywords(self, key: str) -> List[str]:
        keyword_sets = self._bug_triage_rules().get("keyword_sets", {})
        if not isinstance(keyword_sets, dict):
            return []
        raw = keyword_sets.get(key, [])
        if not isinstance(raw, list):
            return []
        return [str(item).lower() for item in raw if str(item).strip()]

    def _bug_log_signals(self, key: str) -> List[str]:
        signal_sets = self._bug_triage_rules().get("log_signals", {})
        if not isinstance(signal_sets, dict):
            return []
        raw = signal_sets.get(key, [])
        if not isinstance(raw, list):
            return []
        return [str(item).lower() for item in raw if str(item).strip()]

    def _bug_triage_weight(self, key: str, default: int) -> int:
        weights = self._bug_triage_rules().get("score_weights", {})
        if not isinstance(weights, dict):
            return default
        try:
            return int(weights.get(key, default))
        except (TypeError, ValueError):
            return default

    def _bug_fallback_agents(self) -> List[str]:
        raw = self._bug_triage_rules().get("fallback_agents", [])
        if not isinstance(raw, list):
            return ["backend", "frontend"]
        candidates = [str(item).strip() for item in raw if str(item).strip()]
        filtered = [item for item in candidates if item in AGENT_EXECUTION_ORDER and item != "orchestrator"]
        return filtered or ["backend", "frontend"]

    def _task_looks_like_bug(self, request: ChatRequest) -> bool:
        if not self._bug_triage_enabled():
            return False
        text = self._execution_hint_text(request)
        task_keywords = self._bug_keywords("task")
        return any(keyword in text for keyword in task_keywords)

    def _infer_bug_owner_agents(
        self,
        request: ChatRequest,
        execution_context: Dict[str, object],
    ) -> tuple[List[str], List[str], List[str]]:
        text = self._execution_hint_text(request)
        scores: Dict[str, int] = {"backend": 0, "frontend": 0, "ops": 0}
        signals: List[str] = []

        def _add_score(agent_id: str, amount: int, reason: str) -> None:
            scores[agent_id] += amount
            if reason not in signals:
                signals.append(reason)

        if any(keyword in text for keyword in self._bug_keywords("integration")):
            _add_score(
                "backend",
                self._bug_triage_weight("integration_to_backend", 2),
                "任务描述包含联调/跨端关键词，后端需参与。",
            )
            _add_score(
                "frontend",
                self._bug_triage_weight("integration_to_frontend", 2),
                "任务描述包含联调/跨端关键词，前端需参与。",
            )
        if any(keyword in text for keyword in self._bug_keywords("backend")):
            _add_score("backend", self._bug_triage_weight("keyword_hit", 2), "任务描述命中后端关键词。")
        if any(keyword in text for keyword in self._bug_keywords("frontend")):
            _add_score("frontend", self._bug_triage_weight("keyword_hit", 2), "任务描述命中前端关键词。")
        if any(keyword in text for keyword in self._bug_keywords("ops")):
            _add_score("ops", self._bug_triage_weight("keyword_hit", 2), "任务描述命中运维/启动/部署关键词。")

        for item in execution_context.get("command_results", []):
            result = item if isinstance(item, ExecutionCommandResult) else ExecutionCommandResult(**item)
            repo_name = (result.repo_name or "").lower()
            if repo_name.startswith("front"):
                _add_score(
                    "frontend",
                    self._bug_triage_weight("execution_repo_hit", 3),
                    f"工作区失败来自 {result.repo_name} 仓库。",
                )
            if repo_name.startswith("back") or "gateway" in repo_name or "server" in repo_name:
                _add_score(
                    "backend",
                    self._bug_triage_weight("execution_repo_hit", 3),
                    f"工作区失败来自 {result.repo_name} 仓库。",
                )
            if result.phase == "start":
                _add_score(
                    "ops",
                    self._bug_triage_weight("start_phase_hit", 2),
                    "失败发生在启动阶段，需运维排查环境与依赖。",
                )
            output = f"{result.command} {result.stdout} {result.stderr} {result.reason}".lower()
            if any(token in output for token in self._bug_log_signals("ops_network")):
                _add_score("ops", self._bug_triage_weight("log_signal_hit", 1), "日志包含超时/连接/端口类异常。")
            if any(token in output for token in self._bug_log_signals("dependency_failure")):
                _add_score("ops", self._bug_triage_weight("log_signal_hit", 1), "日志包含依赖解析异常，需排查私服/网络/构建环境。")

        routed_agents: List[str] = []
        if scores["backend"] > 0:
            routed_agents.append("backend")
        if scores["frontend"] > 0:
            routed_agents.append("frontend")
        if scores["ops"] > 0:
            routed_agents.append("ops")

        if not routed_agents and self._task_looks_like_bug(request):
            routed_agents = self._bug_fallback_agents()
            signals.append("任务被识别为 bug，但缺少明确域信息，默认前后端并行排查。")

        ordered_agents = [
            agent_id
            for agent_id in AGENT_EXECUTION_ORDER
            if agent_id in routed_agents and agent_id != "orchestrator"
        ]
        owner_domains = list(ordered_agents)
        return ordered_agents, owner_domains, signals[:8]

    def _bug_triage_skills_for_agents(self, agent_ids: List[str]) -> List[str]:
        rules = self._bug_triage_rules()
        skill_map = rules.get("skill_map", {}) if isinstance(rules, dict) else {}
        if not isinstance(skill_map, dict):
            skill_map = {}
        candidates: List[str] = []
        for agent_id in agent_ids:
            raw = skill_map.get(agent_id, [])
            if isinstance(raw, list):
                candidates.extend(str(item) for item in raw if str(item).strip())
        seen = set()
        resolved: List[str] = []
        for skill_name in candidates:
            if skill_name in self.definition.skills and skill_name not in seen:
                seen.add(skill_name)
                resolved.append(skill_name)
        return resolved

    def apply_bug_triage_routing(
        self,
        request: ChatRequest,
        execution_context: Dict[str, object],
    ) -> ChatRequest:
        if not self._bug_triage_enabled():
            return request
        is_bug_task = self._task_looks_like_bug(request)
        has_execution_failure = self.execution_has_failures(execution_context)
        if not is_bug_task and not has_execution_failure:
            return request

        routed_agents, owner_domains, signals = self._infer_bug_owner_agents(request, execution_context)
        if not routed_agents:
            return request

        merged_agents = list(request.agents)
        if "bug_inspector" in AGENT_REGISTRY and "bug_inspector" not in merged_agents:
            merged_agents.append("bug_inspector")
        for agent_id in routed_agents:
            if agent_id not in merged_agents:
                merged_agents.append(agent_id)

        skill_agents = ["bug_inspector", *routed_agents]
        injected_skills = self._bug_triage_skills_for_agents(skill_agents)
        merged_skills = list(request.skills)
        for skill_name in injected_skills:
            if skill_name not in merged_skills:
                merged_skills.append(skill_name)

        merged_context = dict(request.context)
        merged_context["bug_triage"] = {
            "enabled": True,
            "is_bug_task": is_bug_task,
            "execution_failed": has_execution_failure,
            "owner_domains": owner_domains,
            "routed_agents": routed_agents,
            "injected_skills": injected_skills,
            "signals": signals,
        }

        workflow = request.workflow
        if not workflow and "bug_fix" in self.workflow_presets:
            workflow = "bug_fix"

        return replace(
            request,
            workflow=workflow,
            agents=merged_agents,
            skills=merged_skills,
            context=merged_context,
        )

    def collect_bug_inspection_evidence(
        self,
        request: ChatRequest,
        execution_context: Dict[str, object],
    ) -> Dict[str, object]:
        is_bug_task = self._task_looks_like_bug(request)
        has_execution_failure = self.execution_has_failures(execution_context)
        if not is_bug_task and not has_execution_failure:
            return {}

        command_evidence = self._collect_failed_command_evidence(execution_context)
        process_logs = self._collect_running_process_log_evidence()
        db_probes = self._collect_database_probe_evidence()
        frontend_console_hints = self._collect_frontend_console_hints(command_evidence, process_logs)
        backend_error_hints = self._collect_backend_error_hints(command_evidence, process_logs)

        summary = {
            "command_failures": len(command_evidence),
            "running_logs": len(process_logs),
            "frontend_error_hints": len(frontend_console_hints),
            "backend_error_hints": len(backend_error_hints),
            "database_probes": len(db_probes),
        }
        return {
            "enabled": True,
            "generated_at": self._now(),
            "is_bug_task": is_bug_task,
            "execution_failed": has_execution_failure,
            "summary": summary,
            "failed_commands": command_evidence[:8],
            "running_process_logs": process_logs[:8],
            "frontend_console_hints": frontend_console_hints[:10],
            "backend_error_hints": backend_error_hints[:10],
            "database_probes": db_probes[:8],
        }

    def _collect_failed_command_evidence(self, execution_context: Dict[str, object]) -> List[Dict[str, object]]:
        items: List[Dict[str, object]] = []
        for raw in execution_context.get("command_results", []):
            result = raw if isinstance(raw, ExecutionCommandResult) else ExecutionCommandResult(**raw)
            if result.status != "failed":
                continue
            output = result.stderr.strip() or result.stdout.strip() or result.reason.strip()
            items.append(
                {
                    "repo_name": result.repo_name,
                    "phase": result.phase,
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "reason": result.reason,
                    "error_lines": self._extract_error_lines(output),
                    "output_excerpt": self._truncate_text(output, limit=1200),
                }
            )
        return items

    def _collect_running_process_log_evidence(self) -> List[Dict[str, object]]:
        evidence: List[Dict[str, object]] = []
        for item in self.repo_manager.list_running_processes():
            log_path = str(item.get("log_path", "")).strip()
            if not log_path:
                continue
            tail = self._read_log_tail(Path(log_path), max_lines=120, max_chars=3600)
            evidence.append(
                {
                    "repo_name": str(item.get("repo_name", "")),
                    "phase": str(item.get("phase", "")),
                    "pid": int(item.get("pid", 0) or 0),
                    "command": str(item.get("command", "")),
                    "log_path": log_path,
                    "log_error_lines": self._extract_error_lines(tail),
                    "log_tail": tail,
                }
            )
        return evidence

    def _collect_frontend_console_hints(
        self,
        command_evidence: List[Dict[str, object]],
        process_logs: List[Dict[str, object]],
    ) -> List[str]:
        lines: List[str] = []
        for item in command_evidence:
            repo_name = str(item.get("repo_name", "")).lower()
            if "front" not in repo_name:
                continue
            for line in item.get("error_lines", []):
                lines.append(str(line))
        for item in process_logs:
            repo_name = str(item.get("repo_name", "")).lower()
            if "front" not in repo_name:
                continue
            for line in item.get("log_error_lines", []):
                lines.append(str(line))
        return self._dedupe_strings(lines, limit=14)

    def _collect_backend_error_hints(
        self,
        command_evidence: List[Dict[str, object]],
        process_logs: List[Dict[str, object]],
    ) -> List[str]:
        lines: List[str] = []
        for item in command_evidence:
            repo_name = str(item.get("repo_name", "")).lower()
            if "back" not in repo_name and "gateway" not in repo_name and "server" not in repo_name:
                continue
            for line in item.get("error_lines", []):
                lines.append(str(line))
        for item in process_logs:
            repo_name = str(item.get("repo_name", "")).lower()
            if "back" not in repo_name and "gateway" not in repo_name and "server" not in repo_name:
                continue
            for line in item.get("log_error_lines", []):
                lines.append(str(line))
        return self._dedupe_strings(lines, limit=14)

    def _collect_database_probe_evidence(self) -> List[Dict[str, object]]:
        probes: List[Dict[str, object]] = []
        for service in self.repo_manager.profile.services:
            if not self._service_looks_like_db(service):
                continue
            probes.append(self._probe_database_service(service))
        return probes

    def _service_looks_like_db(self, service) -> bool:
        name = str(getattr(service, "name", "")).lower()
        return any(token in name for token in ["mysql", "postgres", "pg", "database", "db"])

    def _probe_database_service(self, service) -> Dict[str, object]:
        service_name = str(getattr(service, "name", ""))
        host = str(getattr(service, "host", "") or "127.0.0.1")
        try:
            port = int(getattr(service, "port", 0) or 0)
        except (TypeError, ValueError):
            port = 0
        username = str(getattr(service, "username", "") or "root")
        password = str(getattr(service, "password", ""))
        database = str(getattr(service, "database", ""))

        if "mysql" not in service_name.lower() and "mysql" not in str(self.settings.memory_mysql_bin).lower():
            return {
                "service": service_name,
                "status": "skipped",
                "reason": "仅实现了 MySQL 只读探测；该服务不属于 MySQL。",
            }
        if not port:
            return {
                "service": service_name,
                "status": "skipped",
                "reason": "服务未配置端口，无法探测。",
            }

        cmd = [
            self.settings.memory_mysql_bin,
            f"-h{host}",
            f"-P{port}",
            f"-u{username}",
            f"-p{password}",
            "--connect-timeout=4",
            "-N",
            "-e",
            "SELECT NOW() as now_ts, DATABASE() as db_name;",
        ]
        if database:
            cmd.insert(-2, f"--database={database}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except FileNotFoundError:
            return {
                "service": service_name,
                "status": "skipped",
                "reason": f"MySQL 客户端不存在: {self.settings.memory_mysql_bin}",
            }
        except subprocess.TimeoutExpired:
            return {
                "service": service_name,
                "status": "failed",
                "reason": "数据库只读探测超时。",
            }

        if result.returncode != 0:
            error_text = result.stderr.strip() or result.stdout.strip() or "mysql probe failed"
            return {
                "service": service_name,
                "status": "failed",
                "reason": self._truncate_text(error_text, limit=400),
            }

        rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return {
            "service": service_name,
            "status": "ok",
            "database": database,
            "sample_rows": rows[:5],
        }

    def _read_log_tail(self, path: Path, max_lines: int = 120, max_chars: int = 3600) -> str:
        if not path.exists() or not path.is_file():
            return ""
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return ""
        tail = "\n".join(lines[-max_lines:])
        return self._truncate_text(tail, limit=max_chars)

    def _extract_error_lines(self, text: str) -> List[str]:
        if not text:
            return []
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        tokens = [
            "error",
            "exception",
            "traceback",
            "failed",
            "refused",
            "timeout",
            "报错",
            "异常",
            "失败",
        ]
        matched: List[str] = []
        for line in lines:
            lowered = line.lower()
            if any(token in lowered for token in tokens):
                matched.append(self._truncate_text(line, limit=260))
        if not matched:
            matched = [self._truncate_text(item, limit=260) for item in lines[:6]]
        return self._dedupe_strings(matched, limit=8)

    def _dedupe_strings(self, values: List[str], limit: int = 10) -> List[str]:
        seen = set()
        result: List[str] = []
        for item in values:
            normalized = item.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
            if len(result) >= limit:
                break
        return result

    def inject_project_memory(self, request: ChatRequest) -> ChatRequest:
        # Recall task-relevant project memory and merge into context.
        # This is not chat history: only reusable workflow/entity knowledge.
        memory_items = self.project_memory.recall(
            task=request.task,
            workflow=request.workflow,
            repos=request.repos,
            limit=self.settings.memory_recall_limit,
        )
        if not memory_items:
            return request

        merged_context = dict(request.context)
        merged_context["project_memory"] = {
            "note": "以下为项目高价值记忆（非对话历史），优先用于补齐流程、配置和关联实体。",
            "items": [
                {
                    "title": item.get("title", ""),
                    "memory_type": item.get("memory_type", ""),
                    "score": item.get("score", 0),
                    "workflow": item.get("workflow", ""),
                    "repos": item.get("repos", []),
                    "entities": item.get("entities", {}),
                    "checklist": item.get("checklist", []),
                    "summary": self._truncate_text(str(item.get("content", "")), limit=360),
                }
                for item in memory_items
            ],
        }
        return replace(request, context=merged_context)

    def collect_execution_context(
        self,
        request: ChatRequest,
        plan,
        cancel_event: Optional[threading.Event] = None,
    ) -> Dict[str, object]:
        """执行工作区命令并收集状态，作为后续阻断与建议依据。"""
        self._assert_not_cancelled(cancel_event)
        mode = self.resolve_execution_mode(request)
        requested_repos = self.infer_execution_repos(request)
        repo_names = self.repo_manager.resolve_execution_repo_names(plan.agents, requested_repos) if mode != "off" else []
        repo_statuses = self.repo_manager.repo_status_for_names(repo_names) if repo_names else []
        phases: List[str] = []
        if mode == "start":
            phases.append("start")
        if mode in {"build", "validate"}:
            phases.append("build")
        if mode in {"test", "validate"}:
            phases.append("test")
        command_results = (
            self.repo_manager.execute_repo_commands(repo_names, phases, cancel_event=cancel_event)
            if phases
            else []
        )
        self._assert_not_cancelled(cancel_event)
        return {
            "mode": mode,
            "repo_names": repo_names,
            "repo_statuses": repo_statuses,
            "phases": phases,
            "command_results": command_results,
        }

    def execution_has_failures(self, execution_context: Dict[str, object]) -> bool:
        """判断工作区命令是否出现失败。"""
        return any(item.status == "failed" for item in execution_context.get("command_results", []))

    def build_execution_blocking_reasons(self, execution_context: Dict[str, object]) -> List[str]:
        reasons: List[str] = []
        for item in execution_context.get("command_results", []):
            if item.status != "failed":
                continue
            reason = f"[{item.phase}] {item.repo_name} 执行失败"
            if item.exit_code is not None:
                reason += f" (exit={item.exit_code})"
            if item.reason:
                reason += f": {item.reason}"
            reasons.append(reason)
        return reasons

    def recommended_execution_failure_skills(self, execution_context: Dict[str, object]) -> List[str]:
        if not self.execution_has_failures(execution_context):
            return []

        candidates = ["CodeRuleCheckSkill", "MonitorSkill", "differential-review"]
        if any(item.phase == "test" and item.status == "failed" for item in execution_context.get("command_results", [])):
            candidates.append("coverage-analysis")
        if any(item.phase == "start" and item.status == "failed" for item in execution_context.get("command_results", [])):
            candidates.append("DevOpsSkill")
            candidates.append("MonitorSkill")
        if any("ci" in (item.command or "").lower() for item in execution_context.get("command_results", [])):
            candidates.append("gh-fix-ci")

        available = []
        seen = set()
        for skill_name in candidates:
            if skill_name in self.definition.skills and skill_name not in seen:
                seen.add(skill_name)
                available.append(skill_name)
        return available

    def build_execution_recommendations(self, execution_context: Dict[str, object]) -> List[ExecutionRecommendation]:
        recommendations: List[ExecutionRecommendation] = []
        for item in execution_context.get("command_results", []):
            if item.status != "failed":
                continue
            recommendations.append(self._recommendation_for_command_result(item))
        return recommendations

    def _recommendation_for_command_result(self, result: ExecutionCommandResult) -> ExecutionRecommendation:
        try:
            repo = self.repo_manager.get_repo(result.repo_name)
        except Exception:
            repo = None
        diagnostic = analyze_command_output(
            command=result.command,
            stdout=result.stdout,
            stderr=result.stderr,
            reason=result.reason,
        )
        evidence = self._truncate_text(diagnostic.evidence_text or result.stderr.strip() or result.stdout.strip() or result.reason, limit=500)
        summary = diagnostic.summary
        title = diagnostic.title
        priority = "medium"
        related_skills = ["CodeRuleCheckSkill"]

        lower_output = " ".join(
            [
                result.command.lower(),
                result.stdout.lower(),
                result.stderr.lower(),
                result.reason.lower(),
            ]
        )
        if "timed out" in lower_output or "timeout" in lower_output:
            title = "命令执行超时"
            priority = "high"
            related_skills = ["MonitorSkill", "CodeRuleCheckSkill"]
        elif "coverage" in lower_output:
            title = "覆盖率或质量门禁未达标"
            priority = "high"
            related_skills = ["coverage-analysis", "CodeRuleCheckSkill"]
        elif any(
            token in lower_output
            for token in [
                "compilation failure",
                "cannot find symbol",
                "cannot find module",
                "type error",
                "ts2304",
                "ts2339",
                "package does not exist",
            ]
        ):
            title = "编译或类型检查失败"
            summary = "代码在编译阶段失败，优先检查本次改动涉及的 API、依赖和类型签名是否一致。"
            priority = "high"
            related_skills = ["CodeRuleCheckSkill", "differential-review"]
        elif any(
            token in lower_output
            for token in [
                "could not resolve dependencies",
                "failed to collect dependencies",
                "could not transfer artifact",
                "err_pnpm",
                "npm err",
                "lockfile",
            ]
        ):
            title = "依赖解析或包管理失败"
            summary = "依赖安装或解析阶段失败，优先检查仓库配置、网络、私服或锁文件差异。"
            priority = "high"
            related_skills = ["supply-chain-risk-auditor", "CodeRuleCheckSkill"]
        elif diagnostic.failure_kind == "spring-boot-main-class":
            title = "Spring Boot 启动入口识别失败"
            summary = "当前启动命令没有命中可执行主类，常见原因是把 spring-boot:run 跑在聚合工程。建议改为目标模块 pom 的 `-f .../pom.xml ...:run`。"
            priority = "high"
            related_skills = ["DevOpsSkill", "CodeRuleCheckSkill", "MonitorSkill"]
        elif result.phase == "start":
            title = "启动阶段失败"
            summary = "项目启动命令执行失败，建议先检查依赖服务、环境变量、端口冲突和日志输出。"
            priority = "high"
            related_skills = ["DevOpsSkill", "MonitorSkill", "CodeRuleCheckSkill"]
        elif result.phase == "test":
            title = "测试执行失败"
            summary = "测试阶段出现失败，建议先确认失败用例，再结合覆盖率和差异评审定位根因。"
            priority = "high"
            related_skills = ["coverage-analysis", "differential-review", "MonitorSkill"]
        elif result.phase == "build":
            title = "构建阶段失败"
            summary = "构建阶段已被阻断，建议先排查编译、依赖和代码规范问题。"
            priority = "high"
            related_skills = ["CodeRuleCheckSkill", "differential-review"]

        suggested_commands = self._suggested_commands_for_result(result, diagnostic.failure_kind)
        suggested_workflow, suggested_execution_mode, suggested_repos = self._suggested_workflow_for_result(
            result=result,
            failure_kind=diagnostic.failure_kind,
            repo_kind=getattr(repo, "kind", ""),
        )
        locations = self._resolved_locations_for_result(diagnostic.locations, repo)
        recovery_steps = self._recovery_steps_for_result(
            result=result,
            failure_kind=diagnostic.failure_kind,
            repo_kind=getattr(repo, "kind", ""),
            primary_error=diagnostic.primary_error,
            failed_targets=diagnostic.failed_targets,
        )
        available_related_skills = [
            skill_name for skill_name in related_skills if skill_name in self.definition.skills
        ]
        return ExecutionRecommendation(
            repo_name=result.repo_name,
            phase=result.phase,
            title=title,
            summary=summary,
            priority=priority,
            suggested_commands=suggested_commands,
            related_skills=available_related_skills,
            evidence=evidence,
            failure_kind=diagnostic.failure_kind,
            primary_error=diagnostic.primary_error,
            failed_targets=diagnostic.failed_targets,
            suggested_workflow=suggested_workflow,
            suggested_execution_mode=suggested_execution_mode,
            suggested_repos=suggested_repos,
            recovery_steps=recovery_steps,
            locations=locations,
        )

    def _suggested_commands_for_result(self, result: ExecutionCommandResult, failure_kind: str = "") -> List[str]:
        commands: List[str] = []
        try:
            repo = self.repo_manager.get_repo(result.repo_name)
        except Exception:
            repo = None

        if repo is not None:
            commands.append(f"git -C {repo.local_path} status --short")
        if (
            repo is not None
            and result.phase == "start"
            and failure_kind == "spring-boot-main-class"
        ):
            commands.extend(
                command for command in repo.start_commands if command and command not in commands
            )
        if result.command:
            commands.append(result.command)
        if repo is not None and result.phase == "build":
            commands.extend(command for command in repo.test_commands if command and command not in commands)
        if repo is not None and result.phase == "test":
            commands.extend(command for command in repo.build_commands if command and command not in commands)
        return commands[:3]

    def _suggested_workflow_for_result(
        self,
        result: ExecutionCommandResult,
        failure_kind: str,
        repo_kind: str,
    ) -> tuple[str, str, List[str]]:
        workflow = ""
        execution_mode = "status"
        repos = [result.repo_name] if result.repo_name else []

        if repo_kind == "frontend":
            if result.phase == "start":
                workflow = "frontend_regression"
                execution_mode = "start"
            elif failure_kind in {"typescript", "pytest"}:
                workflow = "frontend_regression"
                execution_mode = "validate"
            elif failure_kind == "dependencies":
                workflow = "quality_audit"
                execution_mode = "build"
            elif failure_kind == "timeout":
                workflow = "pre_release_audit"
                execution_mode = "status"
            else:
                workflow = "frontend_regression"
                execution_mode = "status"
        elif repo_kind == "backend":
            if result.phase == "start":
                workflow = "backend_change_review"
                execution_mode = "start"
            elif failure_kind in {"maven-test", "pytest"}:
                workflow = "backend_api_tdd"
                execution_mode = "test"
            elif failure_kind == "maven-compile":
                workflow = "backend_change_review"
                execution_mode = "validate"
            elif failure_kind == "dependencies":
                workflow = "quality_audit"
                execution_mode = "build"
            elif failure_kind == "timeout":
                workflow = "pre_release_audit"
                execution_mode = "status"
            else:
                workflow = "backend_change_review"
                execution_mode = "status"
        else:
            if failure_kind == "timeout":
                workflow = "pre_release_audit"
                execution_mode = "status"
            elif failure_kind == "dependencies":
                workflow = "quality_audit"
                execution_mode = "build"
            else:
                workflow = "quality_audit"
                execution_mode = "validate"
            if not repos:
                repos = ["backend", "frontend"]

        if workflow not in self.workflow_presets:
            workflow = ""
            execution_mode = ""
        return workflow, execution_mode, repos

    def _resolved_locations_for_result(
        self,
        locations: List[ExecutionLocation],
        repo,
    ) -> List[ExecutionLocation]:
        resolved: List[ExecutionLocation] = []
        for item in locations:
            path = item.path.strip()
            if not path:
                continue
            candidate = Path(path)
            if not candidate.is_absolute() and repo is not None:
                candidate = Path(repo.local_path) / path
            candidate = candidate.expanduser()
            resolved.append(
                ExecutionLocation(
                    path=str(candidate),
                    label=item.label,
                    line=item.line,
                    column=item.column,
                    exists=candidate.exists(),
                )
            )
        return resolved

    def _recovery_steps_for_result(
        self,
        result: ExecutionCommandResult,
        failure_kind: str,
        repo_kind: str,
        primary_error: str,
        failed_targets: List[str],
    ) -> List[str]:
        steps: List[str] = []
        if failure_kind == "pytest":
            steps = [
                "先定位首个失败用例，确认是断言失败、依赖缺失，还是测试环境问题。",
                "查看失败用例涉及的业务改动，优先修复第一个失败点，再回头看连带失败。",
                "修复后先重跑单个失败测试，再执行完整测试命令。",
            ]
            if failed_targets:
                steps.insert(1, f"优先查看失败目标: {', '.join(failed_targets[:3])}。")
        elif failure_kind == "typescript":
            steps = [
                "先修复第一个 TypeScript 报错位置，避免被后续连锁错误干扰。",
                "检查接口字段、类型定义、导入路径和返回值结构是否与最新代码一致。",
                "修复后重新执行类型检查，再决定是否需要跑前端回归。",
            ]
            if primary_error:
                steps.insert(1, f"当前首个关键错误: {primary_error}")
        elif failure_kind == "maven-compile":
            steps = [
                "先看第一条 `cannot find symbol` 或编译错误，优先修复导入、类型、方法签名不一致问题。",
                "检查本次改动是否同步更新了 DTO、VO、Service、Mapper 或模块依赖。",
                "修复编译问题后先重跑构建，再补跑测试命令。",
            ]
        elif failure_kind == "maven-test":
            steps = [
                "先读取 Surefire/Failsafe 的首个失败测试，确认是业务回归还是测试数据问题。",
                "优先修复第一个失败测试，再回看是否存在更多连锁失败。",
                "测试转绿后再做覆盖率或质量门禁复核。",
            ]
        elif failure_kind == "dependencies":
            steps = [
                "先确认网络、私服、镜像源或锁文件是否发生变化。",
                "检查依赖版本冲突、锁文件漂移和本地缓存损坏。",
                "依赖恢复后先重跑构建命令，再决定是否继续跑测试。",
            ]
        elif failure_kind == "timeout":
            steps = [
                "先判断是命令本身很慢，还是卡在依赖下载、外部服务连接或死循环。",
                "查看命令最后输出的位置，优先排查卡住的阶段。",
                "必要时先用 `status` 模式检查仓库状态，再单独重跑该命令。",
            ]
        elif failure_kind == "spring-boot-main-class":
            steps = [
                "先确认失败命令是否在聚合工程执行了 `spring-boot:run`，这类工程通常没有直接可启动主类。",
                "改为指定目标模块 pom（`-f <module>/pom.xml`）再执行 Spring Boot Maven Plugin 全限定 `...:run`。",
                "优先先启动 gateway 或 server 主模块，确认进程拉起后再串联前端联调。",
            ]
        else:
            steps = [
                "先看首条关键错误，确认失败发生在编译、测试还是依赖阶段。",
                "优先修复最早出现的错误，再重跑原命令验证。",
                "如果仍然失败，再切到推荐 workflow 做针对性复核。",
            ]

        if repo_kind == "backend":
            steps.append("后端场景优先关注接口签名、DTO/VO、Service 依赖和测试数据。")
        elif repo_kind == "frontend":
            steps.append("前端场景优先关注类型定义、接口字段映射、组件导入和页面回归。")
        return steps[:6]

    def build_effective_request(
        self,
        request: ChatRequest,
        execution_context: Dict[str, object],
        execution_recommendations: List[ExecutionRecommendation],
    ) -> ChatRequest:
        """发生阻断时，向请求注入补救技能/agent 与执行建议上下文。"""
        if not self.execution_has_failures(execution_context):
            return request

        blocking_reasons = self.build_execution_blocking_reasons(execution_context)
        injected_skills = self.recommended_execution_failure_skills(execution_context)
        merged_skills = list(request.skills)
        for skill_name in injected_skills:
            if skill_name not in merged_skills:
                merged_skills.append(skill_name)

        merged_agents = list(request.agents)
        if "ops" not in merged_agents:
            merged_agents.append("ops")

        merged_context = dict(request.context)
        merged_context["workspace_execution_mode"] = execution_context["mode"]
        merged_context["workspace_blocking_reasons"] = blocking_reasons
        merged_context["workspace_execution_recommendations"] = [
            {
                "title": item.title,
                "summary": item.summary,
                "priority": item.priority,
                "related_skills": item.related_skills,
            }
            for item in execution_recommendations
        ]

        return replace(
            request,
            skills=merged_skills,
            agents=merged_agents,
            context=merged_context,
        )

    def _truncate_text(self, text: str, limit: int = 1800) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _format_command_lines(self, commands: List[str], indent: str = "  ") -> str:
        items = [item for item in commands if item]
        if not items:
            return ""
        return "\n".join(f"{indent}- {item}" for item in items)

    def _format_recovery_lines(self, steps: List[str], indent: str = "  ") -> str:
        items = [item for item in steps if item]
        if not items:
            return ""
        return "\n".join(f"{indent}{index}. {item}" for index, item in enumerate(items, start=1))

    def _format_execution_command_evidence(self, execution_context: Dict[str, object]) -> str:
        command_results = execution_context.get("command_results", [])
        lines: List[str] = []
        for item in command_results:
            if isinstance(item, ExecutionCommandResult):
                result = item
            else:
                result = ExecutionCommandResult(**item)
            if not result.command:
                continue
            line = f"- [{result.phase}] {result.repo_name}: {result.command}"
            if result.status:
                line += f" -> {result.status}"
            if result.exit_code is not None:
                line += f" (exit={result.exit_code})"
            lines.append(line)
        return "\n".join(lines) if lines else "- 无命令执行记录"

    def _format_skill_blocks(self, skill_names: List[str]) -> str:
        definition = self.definition
        skill_blocks = []
        for skill_name in skill_names:
            skill = definition.skills[skill_name]
            skill_blocks.append(
                f"[{skill.name}] {skill.title}\n所属分组: {skill.group}\n{skill.content}"
            )
        return "\n\n".join(skill_blocks) if skill_blocks else "当前 Agent 不直接执行业务 Skill。"

    def _format_execution_context(self, execution_context: Dict[str, object]) -> str:
        mode = str(execution_context.get("mode", "off"))
        if mode == "off":
            return "当前任务未启用工作区执行模式。"

        repo_statuses = execution_context.get("repo_statuses", [])
        command_results = execution_context.get("command_results", [])
        status_lines = []
        for item in repo_statuses:
            status_lines.append(
                f"- {item['name']}: exists={item['exists']}, branch={item['current_branch'] or item['branch']}, dirty={bool(item['git_status'])}"
            )
        result_lines = []
        for item in command_results:
            if isinstance(item, ExecutionCommandResult):
                result = item
            else:
                result = ExecutionCommandResult(**item)
            summary = f"- [{result.phase}] {result.repo_name}: {result.status}"
            if result.exit_code is not None:
                summary += f" (exit={result.exit_code})"
            if result.command:
                summary += f"\n  cmd: {result.command}"
            output = result.stderr.strip() or result.stdout.strip()
            if output:
                summary += f"\n  output: {self._truncate_text(output, limit=400)}"
            if result.reason:
                summary += f"\n  reason: {result.reason}"
            result_lines.append(summary)
        sections = [
            f"执行模式: {mode}",
            "仓库状态:\n" + ("\n".join(status_lines) if status_lines else "- 无"),
            "命令执行结果:\n" + ("\n".join(result_lines) if result_lines else "- 未执行 workspace 命令"),
        ]
        recommendations = execution_context.get("recommendations", [])
        if recommendations:
            recommendation_lines = []
            for item in recommendations:
                if isinstance(item, ExecutionRecommendation):
                    recommendation = item
                else:
                    recommendation = ExecutionRecommendation(**item)
                recommendation_lines.append(
                    f"- [{recommendation.priority}] {recommendation.title}: {recommendation.summary}"
                    + (
                        f"\n  关键错误: {recommendation.primary_error}"
                        if recommendation.primary_error
                        else ""
                    )
                    + (
                        f"\n  建议 workflow: {recommendation.suggested_workflow} ({recommendation.suggested_execution_mode})"
                        if recommendation.suggested_workflow
                        else ""
                    )
                    + (
                        "\n  建议命令:\n" + self._format_command_lines(recommendation.suggested_commands)
                        if recommendation.suggested_commands
                        else ""
                    )
                    + (
                        "\n  恢复步骤:\n" + self._format_recovery_lines(recommendation.recovery_steps)
                        if recommendation.recovery_steps
                        else ""
                    )
                )
            sections.append("自动建议:\n" + "\n".join(recommendation_lines))
        return "\n\n".join(sections)

    def build_agent_system_prompt(self, request: ChatRequest, plan, step_index: int, completed_steps, execution_context) -> str:
        definition = self.definition
        current_step = plan.steps[step_index]
        current_agent = AGENT_REGISTRY[current_step.agent]
        route = " -> ".join(AGENT_REGISTRY[agent_id].title for agent_id in plan.agents)
        constraints = "\n".join(f"- {item}" for item in definition.constraints)
        responsibilities = "\n".join(f"- {item}" for item in current_agent.responsibilities)
        handoffs = "\n".join(
            f"- {AGENT_REGISTRY[agent_id].title}" for agent_id in current_agent.allowed_handoffs
        ) or "- 无"
        context_json = json.dumps(request.context, ensure_ascii=False, indent=2) if request.context else "{}"

        upstream_blocks = []
        for step in completed_steps:
            if step.output.strip():
                upstream_blocks.append(
                    f"[{step.title}] 输出摘要\n{self._truncate_text(step.output, limit=1500)}"
                )
        upstream_text = "\n\n".join(upstream_blocks) if upstream_blocks else "暂无上游 Agent 输出。"

        flow = "\n".join(f"{index}. {item}" for index, item in enumerate(definition.execution_flow, start=1))
        step_goal = (
            f"当前步骤由 {current_agent.title} 执行。"
            f"激活 Skills: {', '.join(current_step.skills) if current_step.skills else '无显式 Skill'}。"
        )
        bug_triage_context = request.context.get("bug_triage", {})
        if current_agent.name == "orchestrator":
            agent_rule = (
                "当前 Agent 只负责拆解、路由、版本一致性和交接安排，不代替领域 Agent 展开全部实现。"
            )
        elif current_agent.name == "bug_inspector":
            agent_rule = (
                "当前 Agent 负责故障诊断与归因，不直接展开大规模业务改造；先交付结构化故障卡片，再交接给对应领域 Agent。"
            )
        else:
            agent_rule = (
                "当前 Agent 只在自己负责的领域内输出，不替代其他 Agent 完成其职责。"
            )
        bug_triage_rule = ""
        if (
            current_agent.name == "orchestrator"
            and isinstance(bug_triage_context, dict)
            and bug_triage_context.get("enabled")
        ):
            owner_domains = ", ".join(str(item) for item in bug_triage_context.get("owner_domains", [])) or "未判定"
            signals = "\n".join(
                f"- {item}" for item in bug_triage_context.get("signals", []) if str(item).strip()
            ) or "- 无"
            bug_triage_rule = (
                "Bug 分诊规则:\n"
                "1. 必须先判断当前需求是否属于 BUG 修复任务。\n"
                "2. 若判定为 BUG，必须给出判责依据，并明确是 frontend/backend/ops 哪些域。\n"
                "3. 仅交接必要 Agent，禁止无依据地把所有 Agent 全量串行执行。\n"
                "4. 若根因在编排层/配置层且当前 Agent 能直接修复，可先直接修复再交接。\n"
                f"5. 本次已识别 owner_domains: {owner_domains}\n"
                f"6. 识别信号:\n{signals}"
            )
        bug_inspector_rule = ""
        if current_agent.name == "bug_inspector":
            bug_inspector_rule = (
                "BugInspector 输出模板:\n"
                "1. 故障卡片（问题现象、影响范围、优先级）\n"
                "2. 证据清单（前端/后端/命令/数据库）\n"
                "3. 根因判断（含置信度）\n"
                "4. 派工建议（backend/frontend/ops，按必要最小集合）\n"
                "5. 修复后回归检查项"
            )

        sections = [
            f"标题:\n{definition.title}",
            f"Agent目标:\n{definition.agent_goal}",
            f"版本规则:\n{definition.version_policy}",
            f"当前迭代版本:\n{request.version}",
            f"启用工作流:\n{request.workflow or 'manual'}",
            f"执行路线:\n{route}",
            f"当前Agent:\n{current_agent.title} ({current_agent.name})",
            f"当前Agent使命:\n{current_agent.mission}",
            f"当前Agent职责:\n{responsibilities}",
            f"当前Agent可交接对象:\n{handoffs}",
            f"当前步骤说明:\n{step_goal}",
            f"Agent规则:\n{agent_rule}",
            (f"{bug_triage_rule}" if bug_triage_rule else "Bug 分诊规则:\n未激活"),
            (bug_inspector_rule if bug_inspector_rule else "BugInspector 模板:\n仅在 BugInspectorAgent 步骤生效"),
            "当前Agent激活Skills:\n" + self._format_skill_blocks(current_step.skills),
            f"标准执行流程:\n{flow}",
            f"强制行为约束:\n{constraints}",
            "工作区执行证据:\n" + self._format_execution_context(execution_context),
            f"附加上下文:\n{context_json}",
            f"上游交接摘要:\n{upstream_text}",
            (
                "输出要求:\n"
                "1. 先说明当前 Agent 的判断和职责边界\n"
                "2. 再输出当前 Agent 的执行结果或建议\n"
                "3. 如果任务涉及接口、版本、测试或部署，必须显式引用当前版本号\n"
                "4. 最后给出交接建议；若有下一 Agent，明确交接给谁以及交付什么\n"
                "5. 如果缺少关键上下文，先列出假设，再继续给出可执行方案\n"
                "6. 涉及命令、日志、路径时，只能引用“工作区执行证据”里真实出现的值；若未执行请写“未执行”，禁止编造示例命令（如 `mvn spring-boot:run`）或占位符日志路径（如 `YYYYMMDD-HHmmss`）"
            ),
        ]
        return "\n\n".join(sections).strip()

    def build_messages(self, request: ChatRequest, plan, step_index: int, completed_steps, execution_context) -> List[ChatMessage]:
        current_step = plan.steps[step_index]
        current_agent = AGENT_REGISTRY[current_step.agent]

        user_sections = [
            f"用户任务:\n{request.task}",
            f"请以 {current_agent.title} 身份处理当前步骤。",
        ]
        if current_step.skills:
            user_sections.append(f"当前步骤需要聚焦的 Skills:\n{', '.join(current_step.skills)}")
        if execution_context.get("command_results"):
            user_sections.append(
                "工作区已执行命令（只可引用以下真实命令与结果，不可改写为模板命令）:\n"
                + self._format_execution_command_evidence(execution_context)
            )
        if current_step.handoff_to:
            user_sections.append(
                f"完成后请准备交接给:\n{AGENT_REGISTRY[current_step.handoff_to].title}"
            )
        else:
            user_sections.append("你是最后一个 Agent，需要输出最终可交付结论。")

        messages = [
            ChatMessage(
                role="system",
                content=self.build_agent_system_prompt(request, plan, step_index, completed_steps, execution_context),
            )
        ]
        messages.extend(request.conversation)
        messages.append(ChatMessage(role="user", content="\n\n".join(user_sections)))
        return messages

    def _append_task_event(
        self,
        task_state: Dict[str, object],
        event_type: str,
        payload: Dict[str, object],
        keep_in_state: bool = True,
    ) -> None:
        event = asdict(
            self.task_store.append_event(
                str(task_state["task_id"]),
                event_type,
                payload,
            )
        )
        if keep_in_state:
            task_state["events"].append(event)

    def _now(self) -> str:
        """返回 UTC ISO 时间戳。"""
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _is_cancelled(self, cancel_event: Optional[threading.Event]) -> bool:
        """判断任务是否已被取消。"""
        return bool(cancel_event is not None and cancel_event.is_set())

    def _assert_not_cancelled(self, cancel_event: Optional[threading.Event]) -> None:
        """取消后抛出统一异常，交给上层收敛。"""
        if self._is_cancelled(cancel_event):
            raise TaskCancelledError("Task canceled by user.")

    def _build_step_dependencies(self, plan) -> Dict[int, Set[int]]:
        """构建步骤依赖图（DAG），支持 backend/frontend 并行。"""
        steps = plan.steps
        deps: Dict[int, Set[int]] = {index: set() for index in range(len(steps))}
        for index in range(1, len(steps)):
            deps[index].add(index - 1)

        # 识别相邻 backend/frontend：两者只依赖前置步骤，后续步骤依赖两者。
        for index in range(len(steps) - 1):
            pair = {steps[index].agent, steps[index + 1].agent}
            if pair != {"backend", "frontend"}:
                continue
            left = index
            right = index + 1
            shared_prev = index - 1
            deps[right].discard(left)
            if shared_prev >= 0:
                deps[left].add(shared_prev)
                deps[right].add(shared_prev)
            if right + 1 < len(steps):
                deps[right + 1].discard(right)
                deps[right + 1].add(left)
                deps[right + 1].add(right)
        return deps

    def _ready_steps(
        self,
        pending: Set[int],
        completed: Set[int],
        deps: Dict[int, Set[int]],
    ) -> List[int]:
        """返回当前可执行的步骤下标。"""
        return sorted(index for index in pending if deps.get(index, set()).issubset(completed))

    def _build_quality_gates(
        self,
        *,
        execution_context: Dict[str, object],
        blocking_reasons: List[str],
        plan,
        completed_step_indexes: Set[int],
    ) -> List[ExecutionGateResult]:
        """评估质量门禁结果。"""
        gates: List[ExecutionGateResult] = []
        workspace_passed = not blocking_reasons
        gates.append(
            ExecutionGateResult(
                gate_name="workspace_checks",
                status="passed" if workspace_passed else "failed",
                summary="工作区执行门禁（start/build/test）",
                details=blocking_reasons[:8],
                blocking=not workspace_passed,
            )
        )

        required_agents = {step.agent for step in plan.steps if step.agent in {"backend", "frontend"}}
        if required_agents:
            completed_agents = {plan.steps[index].agent for index in completed_step_indexes}
            missing_agents = sorted(required_agents.difference(completed_agents))
            gates.append(
                ExecutionGateResult(
                    gate_name="dev_parallel_complete",
                    status="passed" if not missing_agents else "failed",
                    summary="前后端开发并行完成门禁",
                    details=([f"缺少完成步骤: {', '.join(missing_agents)}"] if missing_agents else []),
                    blocking=bool(missing_agents),
                )
            )
        return gates

    def _collect_streamed_step_output(
        self,
        task_state: Dict[str, object],
        request: ChatRequest,
        plan,
        step_index: int,
        completed_steps,
        execution_context,
        persist_step_snapshots: bool = True,
        cancel_event: Optional[threading.Event] = None,
    ) -> str:
        """拉取模型流式输出并写入事件流，同时定期做任务快照。"""
        step = plan.steps[step_index]
        messages = self.build_messages(request, plan, step_index, completed_steps, execution_context)
        emitted_chunks: List[str] = []
        buffer: List[str] = []
        buffer_chars = 0
        emitted_chars = 0
        last_event_at = time.monotonic()
        last_snapshot_at = last_event_at

        try:
            for chunk in self.client.chat_stream(messages):
                self._assert_not_cancelled(cancel_event)
                if not chunk:
                    continue
                text = str(chunk)
                emitted_chunks.append(text)
                buffer.append(text)
                buffer_chars += len(text)
                now = time.monotonic()
                should_emit = (
                    buffer_chars >= 140
                    or "\n" in text
                    or (now - last_event_at) >= 0.35
                )
                if should_emit:
                    delta = "".join(buffer)
                    emitted_chars += len(delta)
                    self._append_task_event(
                        task_state,
                        "agent_step_delta",
                        {
                            "agent": step.agent,
                            "title": step.title,
                            "step_index": step_index,
                            "delta": delta,
                            "content_length": emitted_chars,
                        },
                        keep_in_state=False,
                    )
                    buffer = []
                    buffer_chars = 0
                    last_event_at = now
                if persist_step_snapshots and (now - last_snapshot_at) >= 1.2:
                    # 流式长输出期间定期落盘，避免异常中断导致状态丢失。
                    step.output = "".join(emitted_chunks)
                    task_state["plan"] = asdict(plan)
                    self.task_store.save_state(task_state)
                    last_snapshot_at = now
        except Exception:
            if emitted_chunks:
                raise
            self._append_task_event(
                task_state,
                "agent_step_stream_fallback",
                {
                    "agent": step.agent,
                    "title": step.title,
                    "step_index": step_index,
                },
                keep_in_state=persist_step_snapshots,
            )
            return self.client.chat(messages).strip()

        if buffer:
            delta = "".join(buffer)
            emitted_chars += len(delta)
            self._append_task_event(
                task_state,
                "agent_step_delta",
                {
                    "agent": step.agent,
                    "title": step.title,
                    "step_index": step_index,
                    "delta": delta,
                    "content_length": emitted_chars,
                },
                keep_in_state=False,
            )

        content = "".join(emitted_chunks).strip()
        if content:
            return content
        return self.client.chat(messages).strip()

    def _execute_plan_step(
        self,
        *,
        task_state: Dict[str, object],
        request: ChatRequest,
        plan,
        step_index: int,
        completed_steps,
        execution_context,
        handoffs,
        state_lock: threading.Lock | None = None,
        persist_step_snapshots: bool = True,
        handoff_override: str | None = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> str:
        """执行单个步骤并写入事件/快照。"""
        self._assert_not_cancelled(cancel_event)
        step = plan.steps[step_index]
        started_wall = self._now()
        started_mono = time.monotonic()
        lock = state_lock
        if lock is not None:
            lock.acquire()
        try:
            step.status = "running"
            task_state["status"] = "running"
            task_state["plan"] = asdict(plan)
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "agent_step_started",
                        {
                            "agent": step.agent,
                            "title": step.title,
                            "skills": step.skills,
                            "started_at": started_wall,
                        },
                    )
                )
            )
            self.task_store.save_state(task_state)
        finally:
            if lock is not None:
                lock.release()

        content = self._collect_streamed_step_output(
            task_state=task_state,
            request=request,
            plan=plan,
            step_index=step_index,
            completed_steps=completed_steps,
            execution_context=execution_context,
            persist_step_snapshots=persist_step_snapshots,
            cancel_event=cancel_event,
        )

        finished_wall = self._now()
        duration_ms = int((time.monotonic() - started_mono) * 1000)
        if lock is not None:
            lock.acquire()
        try:
            step.status = "completed"
            step.output = content
            task_state["plan"] = asdict(plan)
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "agent_step_completed",
                        {
                            "agent": step.agent,
                            "title": step.title,
                            "skills": step.skills,
                            "output_length": len(content),
                            "started_at": started_wall,
                            "finished_at": finished_wall,
                            "duration_ms": duration_ms,
                        },
                    )
                )
            )

            target_agent = handoff_override if handoff_override is not None else step.handoff_to
            if target_agent:
                handoff = HandoffRecord(
                    from_agent=step.agent,
                    to_agent=target_agent,
                    reason=(
                        f"{AGENT_REGISTRY[step.agent].title} 已完成当前职责，"
                        f"继续交接给 {AGENT_REGISTRY[target_agent].title}。"
                    ),
                    payload=self._truncate_text(content, limit=2000),
                )
                handoffs.append(handoff)
                task_state["handoffs"] = [asdict(item) for item in handoffs]
                task_state["events"].append(
                    asdict(
                        self.task_store.append_event(
                            task_state["task_id"],
                            "handoff_created",
                            asdict(handoff),
                        )
                    )
                )

            self.task_store.save_state(task_state)
        finally:
            if lock is not None:
                lock.release()
        return content

    def _finalize_canceled_task(
        self,
        *,
        task_state: Dict[str, object],
        plan,
        handoffs: List[HandoffRecord],
        completed_steps,
        used_skills: List[str],
        workflow: Optional[str],
        version: str,
        execution_mode: str,
        repos: List[str],
        execution_results: List[ExecutionCommandResult],
        execution_recommendations: List[ExecutionRecommendation],
        gate_results: List[ExecutionGateResult],
        reason: str,
    ) -> ChatResponse:
        """统一收敛任务取消落盘与响应构建，覆盖早取消与执行中取消。"""
        for step in plan.steps:
            if step.status == "running":
                step.status = "canceled"
        if not isinstance(task_state.get("events"), list):
            task_state["events"] = []
        task_state["status"] = "canceled"
        task_state["error_message"] = reason
        task_state["plan"] = asdict(plan)
        task_state["handoffs"] = [asdict(item) for item in handoffs]
        task_state["events"].append(
            asdict(
                self.task_store.append_event(
                    str(task_state["task_id"]),
                    "task_canceled",
                    {"reason": reason},
                )
            )
        )
        self.task_store.save_state(task_state)
        response = ChatResponse(
            task_id=str(task_state["task_id"]),
            model=self.settings.model_name,
            content="任务已取消。",
            used_skills=used_skills,
            workflow=workflow,
            version=version,
            status="canceled",
            created_at=str(task_state["created_at"]),
            updated_at=str(task_state["updated_at"]),
            used_agents=plan.agents,
            steps=completed_steps,
            handoffs=handoffs,
            execution_mode=execution_mode,
            repos=repos,
            execution_results=execution_results,
            execution_recommendations=execution_recommendations,
            gate_results=gate_results,
        )
        task_state["response"] = asdict(response)
        task_state["gates"] = [asdict(item) for item in gate_results]
        self.task_store.save_state(task_state, touch_updated_at=False)
        return response

    def run(
        self,
        request: ChatRequest,
        on_task_created=None,
        cancel_event: Optional[threading.Event] = None,
    ) -> ChatResponse:
        """执行一次完整任务：请求归一化、工作区执行、Agent 链路、结果持久化。"""
        # 阶段1：准备运行时上下文（刷新配置 + 归一化请求 + 注入项目记忆）。
        # Always refresh workspace profile/secrets before each run so
        # start/build/test commands immediately reflect local config edits.
        self._assert_not_cancelled(cancel_event)
        self.repo_manager.reload()
        normalized_request = self.apply_runtime_defaults(request)
        memory_augmented_request = self.inject_project_memory(normalized_request)

        # 用“初始计划”先创建任务壳，保证异步模式下能立即拿到 task_id。
        base_plan = self.build_execution_plan(memory_augmented_request)
        initial_used_skills = self.resolve_skills(memory_augmented_request.workflow, memory_augmented_request.skills)
        task_state = self.task_store.start_task(memory_augmented_request, base_plan, initial_used_skills)
        if on_task_created is not None:
            try:
                on_task_created(task_state)
            except Exception:
                pass

        # 阶段2：执行工作区命令并生成诊断建议（可能触发阻断）。
        try:
            self._assert_not_cancelled(cancel_event)
        except TaskCancelledError as exc:
            return self._finalize_canceled_task(
                task_state=task_state,
                plan=base_plan,
                handoffs=[],
                completed_steps=[],
                used_skills=initial_used_skills,
                workflow=memory_augmented_request.workflow,
                version=memory_augmented_request.version,
                execution_mode=str(memory_augmented_request.execution_mode),
                repos=list(memory_augmented_request.repos),
                execution_results=[],
                execution_recommendations=[],
                gate_results=[],
                reason=str(exc),
            )
        try:
            execution_context = self.collect_execution_context(
                memory_augmented_request,
                base_plan,
                cancel_event=cancel_event,
            )
        except TaskCancelledError as exc:
            return self._finalize_canceled_task(
                task_state=task_state,
                plan=base_plan,
                handoffs=[],
                completed_steps=[],
                used_skills=initial_used_skills,
                workflow=memory_augmented_request.workflow,
                version=memory_augmented_request.version,
                execution_mode=str(memory_augmented_request.execution_mode),
                repos=list(memory_augmented_request.repos),
                execution_results=[],
                execution_recommendations=[],
                gate_results=[],
                reason=str(exc),
            )
        execution_recommendations = self.build_execution_recommendations(execution_context)
        # recommendations 会被前端展示，也会注入后续 agent 提示词。
        execution_context["recommendations"] = execution_recommendations
        bug_inspection_evidence = self.collect_bug_inspection_evidence(memory_augmented_request, execution_context)
        effective_request = self.build_effective_request(memory_augmented_request, execution_context, execution_recommendations)
        if bug_inspection_evidence:
            merged_context = dict(effective_request.context)
            merged_context["bug_inspection_evidence"] = bug_inspection_evidence
            effective_request = replace(effective_request, context=merged_context)
        effective_request = self.apply_bug_triage_routing(effective_request, execution_context)
        used_skills = self.resolve_skills(effective_request.workflow, effective_request.skills)
        plan = self.build_execution_plan(effective_request)
        blocking_reasons = self.build_execution_blocking_reasons(execution_context)
        task_state["workflow"] = effective_request.workflow
        task_state["version"] = effective_request.version
        task_state["task"] = effective_request.task
        task_state["used_agents"] = plan.agents
        task_state["used_skills"] = used_skills
        task_state["request"] = asdict(effective_request)
        task_state["plan"] = asdict(plan)
        task_state["events"] = []
        completed_steps = []
        handoffs = []
        task_state["user_request"] = asdict(request)
        task_state["normalized_request"] = asdict(normalized_request)
        task_state["effective_request"] = asdict(effective_request)
        task_state["execution"] = {
            "mode": execution_context["mode"],
            "repo_names": execution_context["repo_names"],
            "repo_statuses": execution_context["repo_statuses"],
            "phases": execution_context["phases"],
            "command_results": [asdict(item) for item in execution_context["command_results"]],
            "blocking_reasons": blocking_reasons,
            "recommendations": [asdict(item) for item in execution_recommendations],
            "bug_inspection_evidence": bug_inspection_evidence,
        }

        # 阶段3：写入任务生命周期起始事件（创建、启动、工作区检查、阻断等）。
        task_state["events"].append(
            asdict(
                self.task_store.append_event(
                    task_state["task_id"],
                    "task_created",
                    {
                        "workflow": memory_augmented_request.workflow,
                        "version": memory_augmented_request.version,
                        "task": memory_augmented_request.task,
                    },
                )
            )
        )
        project_memory_payload = memory_augmented_request.context.get("project_memory", {})
        recalled_memories = project_memory_payload.get("items", []) if isinstance(project_memory_payload, dict) else []
        if recalled_memories:
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "project_memory_recalled",
                        {
                            "count": len(recalled_memories),
                            "titles": [str(item.get("title", "")) for item in recalled_memories[:8]],
                        },
                    )
                )
            )
        task_state["events"].append(
            asdict(
                self.task_store.append_event(
                    task_state["task_id"],
                    "task_started",
                    {"used_agents": plan.agents, "used_skills": used_skills},
                )
            )
        )
        if bug_inspection_evidence:
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "bug_inspection_collected",
                        {
                            "summary": bug_inspection_evidence.get("summary", {}),
                            "has_database_probe": bool(bug_inspection_evidence.get("database_probes")),
                        },
                    )
                )
            )
        bug_triage_context = effective_request.context.get("bug_triage", {})
        if isinstance(bug_triage_context, dict) and bug_triage_context.get("enabled"):
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "bug_triaged",
                        {
                            "is_bug_task": bool(bug_triage_context.get("is_bug_task")),
                            "owner_domains": list(bug_triage_context.get("owner_domains", [])),
                            "routed_agents": list(bug_triage_context.get("routed_agents", [])),
                            "signals": list(bug_triage_context.get("signals", [])),
                        },
                    )
                )
            )
        if execution_context["repo_statuses"]:
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "workspace_inspected",
                        {
                            "mode": execution_context["mode"],
                            "repos": execution_context["repo_names"],
                        },
                    )
                )
            )
        for result in execution_context["command_results"]:
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "workspace_command_completed",
                        {
                            "repo_name": result.repo_name,
                            "phase": result.phase,
                            "status": result.status,
                            "exit_code": result.exit_code,
                        },
                    )
                )
            )
        if blocking_reasons:
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "workspace_blocked",
                        {
                            "blocking_reasons": blocking_reasons,
                            "injected_agents": effective_request.agents,
                            "injected_skills": effective_request.skills,
                        },
                    )
                )
            )
        if execution_recommendations:
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "workspace_recommendations_generated",
                        {
                            "count": len(execution_recommendations),
                            "titles": [item.title for item in execution_recommendations],
                        },
                )
            )
        )
        self.task_store.save_state(task_state)

        gate_results: List[ExecutionGateResult] = self._build_quality_gates(
            execution_context=execution_context,
            blocking_reasons=blocking_reasons,
            plan=plan,
            completed_step_indexes=set(),
        )
        task_state["gates"] = [asdict(item) for item in gate_results]
        self.task_store.save_state(task_state)

        # 阶段4：按 DAG 批次执行 Agent 步骤（支持并行批次）。
        step_lock = threading.Lock()
        try:
            deps = self._build_step_dependencies(plan)
            pending: Set[int] = set(range(len(plan.steps)))
            completed_indexes: Set[int] = set()
            while pending:
                self._assert_not_cancelled(cancel_event)
                ready = self._ready_steps(pending, completed_indexes, deps)
                if not ready:
                    raise RuntimeError("Invalid execution DAG: no ready step found.")

                completed_snapshot = list(completed_steps)
                errors: List[Exception] = []

                if len(ready) == 1:
                    index = ready[0]
                    self._execute_plan_step(
                        task_state=task_state,
                        request=effective_request,
                        plan=plan,
                        step_index=index,
                        completed_steps=completed_snapshot,
                        execution_context=execution_context,
                        handoffs=handoffs,
                        persist_step_snapshots=True,
                        cancel_event=cancel_event,
                    )
                else:
                    with ThreadPoolExecutor(max_workers=len(ready)) as executor:
                        futures = [
                            executor.submit(
                                self._execute_plan_step,
                                task_state=task_state,
                                request=effective_request,
                                plan=plan,
                                step_index=index,
                                completed_steps=completed_snapshot,
                                execution_context=execution_context,
                                handoffs=handoffs,
                                state_lock=step_lock,
                                persist_step_snapshots=False,
                                cancel_event=cancel_event,
                            )
                            for index in ready
                        ]
                        for future in futures:
                            try:
                                future.result()
                            except Exception as exc:  # pragma: no cover - defensive branch
                                errors.append(exc)
                    # 并行批次结束后统一落一次快照，避免并发频繁写盘。
                    task_state["plan"] = asdict(plan)
                    self.task_store.save_state(task_state)

                for index in sorted(ready):
                    if plan.steps[index].status == "completed":
                        completed_indexes.add(index)
                        pending.discard(index)
                        completed_steps.append(plan.steps[index])
                if errors:
                    raise errors[0]

                gate_results = self._build_quality_gates(
                    execution_context=execution_context,
                    blocking_reasons=blocking_reasons,
                    plan=plan,
                    completed_step_indexes=completed_indexes,
                )
                task_state["gates"] = [asdict(item) for item in gate_results]
                self.task_store.save_state(task_state)
        except TaskCancelledError as exc:
            return self._finalize_canceled_task(
                task_state=task_state,
                plan=plan,
                handoffs=handoffs,
                completed_steps=completed_steps,
                used_skills=used_skills,
                workflow=effective_request.workflow,
                version=effective_request.version,
                execution_mode=str(execution_context["mode"]),
                repos=list(execution_context["repo_names"]),
                execution_results=list(execution_context["command_results"]),
                execution_recommendations=execution_recommendations,
                gate_results=gate_results,
                reason=str(exc),
            )
        except Exception as exc:
            # 阶段4-异常分支：记录失败步骤并持久化错误状态。
            failed_step = next((step for step in plan.steps if step.status == "running"), None)
            if failed_step is not None:
                failed_step.status = "failed"
                failed_step.output = str(exc)
            task_state["status"] = "failed"
            task_state["error_message"] = str(exc)
            task_state["plan"] = asdict(plan)
            task_state["handoffs"] = [asdict(item) for item in handoffs]
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "task_failed",
                        {"error_message": str(exc)},
                    )
                )
            )
            self.task_store.save_state(task_state)
            raise

        # 阶段5：汇总多 Agent 输出，并在存在阻断时拼接阻断前缀。
        if len(completed_steps) == 1:
            content = completed_steps[0].output
        else:
            content = "\n\n".join(
                f"## {step.title}\n{step.output}" for step in completed_steps
            ).strip()
        gate_blocking_reasons = [
            item.summary
            for item in gate_results
            if item.blocking and item.status != "passed"
        ]
        if blocking_reasons:
            blocker_text = "\n".join(f"- {item}" for item in blocking_reasons)
            recommendation_text = "\n".join(
                (
                    f"- [{item.priority}] {item.title}: {item.summary}"
                    + (f"\n  关键错误: {item.primary_error}" if item.primary_error else "")
                    + (
                        f"\n  失败目标: {', '.join(item.failed_targets)}"
                        if item.failed_targets
                        else ""
                    )
                    + (
                        "\n  建议命令:\n" + self._format_command_lines(item.suggested_commands)
                        if item.suggested_commands
                        else ""
                    )
                    + (
                        f"\n  建议 workflow: {item.suggested_workflow} / {item.suggested_execution_mode}"
                        if item.suggested_workflow
                        else ""
                    )
                    + (
                        "\n  恢复步骤:\n" + self._format_recovery_lines(item.recovery_steps)
                        if item.recovery_steps
                        else ""
                    )
                )
                for item in execution_recommendations
            )
            prefix = f"## 工作区执行阻断\n{blocker_text}"
            if recommendation_text:
                prefix += f"\n\n## 自动修复建议\n{recommendation_text}"
            content = f"{prefix}\n\n{content}".strip()
        elif gate_blocking_reasons:
            gate_text = "\n".join(f"- {item}" for item in gate_blocking_reasons)
            content = f"## 质量门禁阻断\n{gate_text}\n\n{content}".strip()

        final_status = "blocked" if (blocking_reasons or gate_blocking_reasons) else "completed"

        # 阶段6：构建最终响应并同步任务状态。
        response = ChatResponse(
            task_id=task_state["task_id"],
            model=self.settings.model_name,
            content=content,
            used_skills=used_skills,
            workflow=effective_request.workflow,
            version=effective_request.version,
            status=final_status,
            created_at=task_state["created_at"],
            updated_at=task_state["updated_at"],
            used_agents=plan.agents,
            steps=completed_steps,
            handoffs=handoffs,
            execution_mode=str(execution_context["mode"]),
            repos=list(execution_context["repo_names"]),
            execution_results=list(execution_context["command_results"]),
            execution_recommendations=execution_recommendations,
            gate_results=gate_results,
        )
        task_state["status"] = final_status
        task_state["response"] = asdict(response)
        task_state["plan"] = asdict(plan)
        task_state["handoffs"] = [asdict(item) for item in handoffs]
        task_state["gates"] = [asdict(item) for item in gate_results]

        # 仅在任务最终 completed 时沉淀项目记忆；blocked/failed 不入库。
        memory_saved_count = self.project_memory.persist_from_task(
            task_id=response.task_id,
            request=effective_request,
            steps=completed_steps,
            final_content=content,
            final_status=final_status,
        )
        if memory_saved_count:
            task_state["events"].append(
                asdict(
                    self.task_store.append_event(
                        task_state["task_id"],
                        "project_memory_updated",
                        {"saved_count": memory_saved_count},
                    )
                )
            )
        final_event_type = "task_blocked" if final_status == "blocked" else "task_completed"
        task_state["events"].append(
            asdict(
                self.task_store.append_event(
                    task_state["task_id"],
                    final_event_type,
                    {
                        "used_agents": plan.agents,
                        "used_skills": used_skills,
                        "blocking_reasons": blocking_reasons,
                        "gate_blocking_reasons": gate_blocking_reasons,
                    },
                )
            )
        )

        # 先常规落盘，再做一次不更新时间戳的对齐落盘，避免 updated_at 漂移。
        self.task_store.save_state(task_state)
        response.updated_at = task_state["updated_at"]
        task_state["response"] = asdict(response)
        # Keep final response snapshot aligned with persisted updated_at
        # without bumping timestamp one more time.
        self.task_store.save_state(task_state, touch_updated_at=False)
        return response

    def bug_triage_meta(self) -> Dict[str, object]:
        return {
            "path": self.bug_triage_config_path,
            "config": self.bug_triage_config,
        }

    def update_bug_triage_config(self, payload: Dict[str, object]) -> Dict[str, object]:
        config, path = save_bug_triage_config(self.bug_triage_config_path, payload)
        self.bug_triage_config = config
        self.bug_triage_config_path = path
        return self.bug_triage_meta()

    def reset_bug_triage_config(self) -> Dict[str, object]:
        config, path = reset_bug_triage_config(self.bug_triage_config_path)
        self.bug_triage_config = config
        self.bug_triage_config_path = path
        return self.bug_triage_meta()

    def meta(self) -> Dict[str, object]:
        return {
            "title": self.definition.title,
            "prompt_docx_path": self.settings.prompt_docx_path,
            "architecture": "multi-agent-single-model",
            "model_provider": self.settings.model_provider,
            "model_name": self.settings.model_name,
            "model_base_url": self.settings.model_base_url,
            "prompt_registry": self.prompt_registry.meta(),
            "skill_plugin_registry": self.skill_plugin_registry.meta(),
            "workflow_preset_path": self.workflow_preset_path,
            "bug_triage_config_path": self.bug_triage_config_path,
            "task_storage_dir": self.settings.task_storage_dir,
            "task_sqlite_path": self.settings.task_sqlite_path,
            "project_memory": self.project_memory.meta(),
            "workspace": self.repo_manager.meta(),
            "execution_modes": ["off", "status", "build", "test", "validate", "start"],
            "agents": {
                name: {
                    "title": agent.title,
                    "mission": agent.mission,
                    "responsibilities": agent.responsibilities,
                    "owned_skills": agent.owned_skills,
                    "allowed_handoffs": agent.allowed_handoffs,
                }
                for name, agent in AGENT_REGISTRY.items()
            },
            "skills": {
                name: {
                    "title": skill.title,
                    "group": skill.group,
                    "owner_agent": skill.owner_agent,
                    "source": skill.source,
                }
                for name, skill in self.definition.skills.items()
            },
            "workflows": self.workflow_presets,
            "workflow_agents": self.workflow_agent_presets,
        }
