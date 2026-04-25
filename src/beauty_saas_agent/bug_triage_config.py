from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .agent_registry import AGENT_REGISTRY


DEFAULT_BUG_TRIAGE_CONFIG: Dict[str, object] = {
    "version": 1,
    "enabled": True,
    "keyword_sets": {
        "task": [
            "bug",
            "bugs",
            "fix bug",
            "bugfix",
            "defect",
            "issue",
            "broken",
            "error",
            "exception",
            "报错",
            "异常",
            "故障",
            "修复",
            "修一下",
            "崩溃",
            "打不开",
            "白屏",
            "500",
            "502",
            "503",
        ],
        "backend": [
            "backend",
            "后端",
            "接口",
            "api",
            "controller",
            "service",
            "mapper",
            "dto",
            "vo",
            "数据库",
            "mysql",
            "sql",
            "gateway",
            "spring",
            "nacos",
        ],
        "frontend": [
            "frontend",
            "前端",
            "页面",
            "浏览器",
            "ui",
            "按钮",
            "样式",
            "路由",
            "组件",
            "vite",
            "vue",
            "react",
            "typescript",
            "ts",
            "白屏",
        ],
        "ops": [
            "ops",
            "运维",
            "部署",
            "发布",
            "启动",
            "日志",
            "监控",
            "端口",
            "容器",
            "docker",
            "k8s",
            "kubernetes",
            "nacos",
            "环境变量",
            "ci",
            "cd",
        ],
        "integration": [
            "联调",
            "前后端",
            "端到端",
            "e2e",
            "full stack",
            "fullstack",
        ],
    },
    "log_signals": {
        "ops_network": ["timeout", "timed out", "connection refused", "address already in use"],
        "dependency_failure": ["could not resolve dependencies", "failed to collect dependencies"],
    },
    "score_weights": {
        "integration_to_backend": 2,
        "integration_to_frontend": 2,
        "keyword_hit": 2,
        "execution_repo_hit": 3,
        "start_phase_hit": 2,
        "log_signal_hit": 1,
    },
    "fallback_agents": ["backend", "frontend"],
    "skill_map": {
        "bug_inspector": ["playwright-interactive", "sentry", "screenshot"],
        "backend": ["BackendCodeReadSkill", "BackendCodeWriteSkill", "BackendTestSkill", "ApiDocSkill"],
        "frontend": ["FrontendCodeReadSkill", "FrontendCodeWriteSkill", "FrontendTestSkill"],
        "ops": ["MonitorSkill", "CodeRuleCheckSkill", "DevOpsSkill"],
    },
    "notes": [
        "这个文件控制 bug 分诊规则：关键词、打分和自动注入技能。",
        "修改后会对新任务立即生效。",
    ],
}


def default_bug_triage_config() -> Dict[str, object]:
    return copy.deepcopy(DEFAULT_BUG_TRIAGE_CONFIG)


def load_bug_triage_config(path: str | Path) -> Tuple[Dict[str, object], str]:
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        payload = default_bug_triage_config()
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload, str(config_path)

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    payload = normalize_bug_triage_config(raw if isinstance(raw, dict) else {})
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload, str(config_path)


def save_bug_triage_config(path: str | Path, payload: Dict[str, object]) -> Tuple[Dict[str, object], str]:
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_bug_triage_config(payload)
    config_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized, str(config_path)


def reset_bug_triage_config(path: str | Path) -> Tuple[Dict[str, object], str]:
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = default_bug_triage_config()
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload, str(config_path)


def normalize_bug_triage_config(payload: Dict[str, object]) -> Dict[str, object]:
    base = default_bug_triage_config()
    if not isinstance(payload, dict):
        return base

    merged = _deep_merge_dict(base, payload)
    merged["enabled"] = bool(merged.get("enabled", True))
    merged["keyword_sets"] = _normalize_keyword_sets(merged.get("keyword_sets"))
    merged["log_signals"] = _normalize_log_signals(merged.get("log_signals"))
    merged["score_weights"] = _normalize_score_weights(merged.get("score_weights"))
    merged["fallback_agents"] = _normalize_agents(merged.get("fallback_agents"))
    merged["skill_map"] = _normalize_skill_map(merged.get("skill_map"))
    merged["version"] = int(merged.get("version", 1) or 1)
    merged["notes"] = _normalize_keywords(merged.get("notes"))
    return merged


def _deep_merge_dict(base: Dict[str, object], patch: Dict[str, object]) -> Dict[str, object]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(merged[key], value)  # type: ignore[arg-type]
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _normalize_keyword_sets(raw: Any) -> Dict[str, List[str]]:
    base = default_bug_triage_config()["keyword_sets"]
    base = base if isinstance(base, dict) else {}
    raw_map = raw if isinstance(raw, dict) else {}
    result: Dict[str, List[str]] = {}
    for key in ["task", "backend", "frontend", "ops", "integration"]:
        default_items = base.get(key, []) if isinstance(base.get(key, []), list) else []
        source_items = raw_map.get(key, default_items)
        normalized = _normalize_keywords(source_items)
        result[key] = normalized or _normalize_keywords(default_items)
    return result


def _normalize_log_signals(raw: Any) -> Dict[str, List[str]]:
    defaults = default_bug_triage_config()["log_signals"]
    defaults = defaults if isinstance(defaults, dict) else {}
    raw_map = raw if isinstance(raw, dict) else {}
    result: Dict[str, List[str]] = {}
    for key in ["ops_network", "dependency_failure"]:
        default_items = defaults.get(key, []) if isinstance(defaults.get(key, []), list) else []
        source_items = raw_map.get(key, default_items)
        normalized = _normalize_keywords(source_items)
        result[key] = normalized or _normalize_keywords(default_items)
    return result


def _normalize_score_weights(raw: Any) -> Dict[str, int]:
    defaults = default_bug_triage_config()["score_weights"]
    defaults = defaults if isinstance(defaults, dict) else {}
    raw_map = raw if isinstance(raw, dict) else {}
    result: Dict[str, int] = {}
    for key, default_value in defaults.items():
        try:
            result[key] = int(raw_map.get(key, default_value))
        except (TypeError, ValueError):
            result[key] = int(default_value)
    return result


def _normalize_skill_map(raw: Any) -> Dict[str, List[str]]:
    defaults = default_bug_triage_config()["skill_map"]
    defaults = defaults if isinstance(defaults, dict) else {}
    raw_map = raw if isinstance(raw, dict) else {}
    result: Dict[str, List[str]] = {}
    for key in AGENT_REGISTRY.keys():
        if key == "orchestrator":
            continue
        default_items = defaults.get(key, []) if isinstance(defaults.get(key, []), list) else []
        source_items = raw_map.get(key, default_items)
        result[key] = _normalize_keywords(source_items)
    return result


def _normalize_agents(raw: Any) -> List[str]:
    items = _normalize_keywords(raw)
    allowed = set(AGENT_REGISTRY.keys()) - {"orchestrator"}
    result: List[str] = []
    for item in items:
        if item in allowed and item not in result:
            result.append(item)
    return result


def _normalize_keywords(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    result: List[str] = []
    for item in raw:
        value = str(item).strip()
        if value and value not in result:
            result.append(value)
    return result
