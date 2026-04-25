from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from .config import Settings


WORKFLOW_PRESETS = {
    "bug_fix": [],
    "backend_only": [
        "DBStructSkill",
        "BackendCodeReadSkill",
        "BackendCodeWriteSkill",
        "BackendTestSkill",
        "ApiDocSkill",
        "CodeRuleCheckSkill",
    ],
    "frontend_only": [
        "FrontendCodeReadSkill",
        "FrontendCodeWriteSkill",
        "FrontendUISkill",
        "FrontendTestSkill",
        "CodeRuleCheckSkill",
    ],
    "ops_only": [
        "DBStructSkill",
        "MonitorSkill",
        "CodeRuleCheckSkill",
        "DevOpsSkill",
    ],
    "full_iteration": [
        "DBStructSkill",
        "BackendCodeReadSkill",
        "BackendCodeWriteSkill",
        "BackendTestSkill",
        "ApiDocSkill",
        "FrontendCodeReadSkill",
        "FrontendCodeWriteSkill",
        "FrontendUISkill",
        "FrontendTestSkill",
        "MonitorSkill",
        "CodeRuleCheckSkill",
        "DevOpsSkill",
    ],
}


WORKFLOW_AGENT_PRESETS = {
    "bug_fix": ["orchestrator", "bug_inspector"],
    "backend_only": ["orchestrator", "backend"],
    "frontend_only": ["orchestrator", "frontend"],
    "ops_only": ["orchestrator", "ops"],
    "full_iteration": ["orchestrator", "backend", "frontend", "ops"],
}


DEFAULT_CUSTOM_WORKFLOWS = {
    "frontend_enhanced": {
        "description": "在内置前端开发流程上叠加高质量 UI 与浏览器自动化验证能力。",
        "agents": ["orchestrator", "frontend"],
        "skills": [
            "FrontendCodeReadSkill",
            "FrontendCodeWriteSkill",
            "FrontendUISkill",
            "FrontendTestSkill",
            "frontend-skill",
            "playwright",
            "CodeRuleCheckSkill",
        ],
    },
    "frontend_visual_upgrade": {
        "description": "面向页面改版与视觉升级，强调界面层级、体验与商用质感。",
        "agents": ["orchestrator", "frontend"],
        "skills": [
            "FrontendCodeReadSkill",
            "FrontendCodeWriteSkill",
            "FrontendUISkill",
            "frontend-skill",
            "FrontendTestSkill",
            "CodeRuleCheckSkill",
        ],
    },
    "frontend_regression": {
        "description": "面向联调后回归验证，强调浏览器流程、自测与问题复盘。",
        "agents": ["orchestrator", "frontend"],
        "skills": [
            "FrontendCodeReadSkill",
            "FrontendTestSkill",
            "playwright",
            "CodeRuleCheckSkill",
        ],
    },
    "backend_tdd": {
        "description": "先用 TDD 拆解后端迭代，再进入数据库、实现、测试和接口文档流程。",
        "agents": ["orchestrator", "backend"],
        "skills": [
            "tdd",
            "DBStructSkill",
            "BackendCodeReadSkill",
            "BackendCodeWriteSkill",
            "BackendTestSkill",
            "ApiDocSkill",
            "CodeRuleCheckSkill",
        ],
    },
    "backend_api_tdd": {
        "description": "聚焦后端接口交付，先做 TDD 拆解，再完成接口、测试和文档闭环。",
        "agents": ["orchestrator", "backend"],
        "skills": [
            "tdd",
            "DBStructSkill",
            "BackendCodeReadSkill",
            "BackendCodeWriteSkill",
            "BackendTestSkill",
            "ApiDocSkill",
        ],
    },
    "backend_change_review": {
        "description": "面向后端改动复核，强化差异评审、覆盖率和静态分析检查。",
        "agents": ["orchestrator", "backend", "ops"],
        "skills": [
            "BackendCodeReadSkill",
            "BackendTestSkill",
            "coverage-analysis",
            "differential-review",
            "codeql",
            "semgrep",
            "CodeRuleCheckSkill",
        ],
    },
    "quality_audit": {
        "description": "对代码质量、静态分析、覆盖率和供应链风险做集中审计。",
        "agents": ["orchestrator", "ops"],
        "skills": [
            "codeql",
            "semgrep",
            "sarif-parsing",
            "coverage-analysis",
            "supply-chain-risk-auditor",
            "differential-review",
            "sharp-edges",
            "testing-handbook-generator",
        ],
    },
    "release_guard": {
        "description": "围绕发布前安全、CI、监控和交付稳定性做守护检查。",
        "agents": ["orchestrator", "ops"],
        "skills": [
            "security-best-practices",
            "gh-fix-ci",
            "sentry",
            "MonitorSkill",
            "CodeRuleCheckSkill",
            "DevOpsSkill",
        ],
    },
    "pre_release_audit": {
        "description": "贴近上线前联查，串联后端测试、前端回归、监控、安全和 CI 风险。",
        "agents": ["orchestrator", "backend", "frontend", "ops"],
        "skills": [
            "BackendTestSkill",
            "FrontendTestSkill",
            "playwright",
            "MonitorSkill",
            "security-best-practices",
            "gh-fix-ci",
            "sentry",
            "CodeRuleCheckSkill",
        ],
    },
}


def load_workflow_catalog(settings: Settings) -> Tuple[Dict[str, List[str]], Dict[str, List[str]], str]:
    """加载内置+自定义 workflow 配置。"""
    path = Path(settings.workflow_preset_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_default_custom_workflows(path)

    workflow_presets = dict(WORKFLOW_PRESETS)
    workflow_agent_presets = dict(WORKFLOW_AGENT_PRESETS)

    payload = _read_json(path)
    for workflow_name, item in payload.get("workflows", {}).items():
        if not isinstance(item, dict):
            continue
        skills = [str(skill) for skill in item.get("skills", []) if str(skill).strip()]
        agents = [str(agent) for agent in item.get("agents", []) if str(agent).strip()]
        if skills:
            workflow_presets[workflow_name] = skills
        if agents:
            workflow_agent_presets[workflow_name] = agents

    return workflow_presets, workflow_agent_presets, str(path)


def _ensure_default_custom_workflows(path: Path) -> None:
    """首次运行时写入默认自定义 workflow 文件。"""
    if path.exists():
        return
    payload = {
        "version": 1,
        "notes": [
            "这里放项目级自定义 workflow preset。",
            "skills 里写 skill 名称，agents 里写 orchestrator/bug_inspector/backend/frontend/ops。",
        ],
        "workflows": DEFAULT_CUSTOM_WORKFLOWS,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Dict[str, object]:
    """读取 JSON 文件，文件不存在时返回空字典。"""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
