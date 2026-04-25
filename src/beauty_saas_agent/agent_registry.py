from __future__ import annotations

from typing import Dict, List, Optional

from .models import AgentDefinition


AGENT_EXECUTION_ORDER = ["orchestrator", "bug_inspector", "backend", "frontend", "ops"]


AGENT_REGISTRY: Dict[str, AgentDefinition] = {
    "orchestrator": AgentDefinition(
        name="orchestrator",
        title="OrchestratorAgent",
        mission="负责统一版本、任务拆解、Agent 路由、执行顺序控制与最终汇总。",
        responsibilities=[
            "确认本次迭代版本号、工作流和执行边界",
            "根据任务范围决定调用 BackendAgent、FrontendAgent、OpsAgent 的顺序",
            "保证前后端版本一致、流程不越级、失败即阻断",
            "汇总各 Agent 输出并形成最终交付结果",
        ],
        owned_skills=[],
        allowed_handoffs=["bug_inspector", "backend", "frontend", "ops"],
    ),
    "bug_inspector": AgentDefinition(
        name="bug_inspector",
        title="BugInspectorAgent",
        mission="负责快速故障定位：汇总控制台、后端日志、执行失败证据和数据库只读探测，给出归因与修复入口。",
        responsibilities=[
            "汇总前端控制台报错、网络失败和后端日志关键异常",
            "结合工作区执行失败信息定位首个阻断点",
            "在只读前提下探测数据库连通性与关键数据异常",
            "输出结构化故障卡片，并交接给最少必要 Agent 修复",
        ],
        owned_skills=[
            "playwright-interactive",
            "sentry",
            "screenshot",
        ],
        allowed_handoffs=["backend", "frontend", "ops"],
    ),
    "backend": AgentDefinition(
        name="backend",
        title="BackendAgent",
        mission="负责后端阅读、开发、测试与接口文档，确保接口版本化和后端稳定性。",
        responsibilities=[
            "管理后端代码理解与业务流转梳理",
            "输出 Controller、Service、Mapper、DTO、VO 等后端实现建议",
            "执行后端测试、覆盖率与接口文档准备",
            "向 FrontendAgent 或 OpsAgent 交接后端结果",
        ],
        owned_skills=[
            "BackendCodeReadSkill",
            "BackendCodeWriteSkill",
            "BackendTestSkill",
            "ApiDocSkill",
        ],
        allowed_handoffs=["frontend", "ops"],
    ),
    "frontend": AgentDefinition(
        name="frontend",
        title="FrontendAgent",
        mission="负责前端阅读、页面开发、UI 优化和自测，确保联调与体验统一。",
        responsibilities=[
            "理解现有前端结构、路由、组件和权限体系",
            "基于接口文档实现前端页面和 API 对接逻辑",
            "执行商用级 UI 强化与前端自测",
            "向 OpsAgent 交接可部署的前端结果",
        ],
        owned_skills=[
            "FrontendCodeReadSkill",
            "FrontendCodeWriteSkill",
            "FrontendUISkill",
            "FrontendTestSkill",
        ],
        allowed_handoffs=["ops"],
    ),
    "ops": AgentDefinition(
        name="ops",
        title="OpsAgent",
        mission="负责数据库规范、监控、代码规范检查与部署交付，保证上线稳定性。",
        responsibilities=[
            "审查数据库结构和慢 SQL 风险",
            "检查日志监控、代码规范和部署阻断项",
            "管理构建、发布、服务控制和回滚建议",
            "输出最终版本交付和部署结论",
        ],
        owned_skills=[
            "DBStructSkill",
            "MonitorSkill",
            "CodeRuleCheckSkill",
            "DevOpsSkill",
        ],
        allowed_handoffs=[],
    ),
}


WORKFLOW_AGENT_PRESETS = {
    "bug_fix": ["orchestrator", "bug_inspector"],
    "backend_only": ["orchestrator", "backend"],
    "frontend_only": ["orchestrator", "frontend"],
    "ops_only": ["orchestrator", "ops"],
    "full_iteration": ["orchestrator", "backend", "frontend", "ops"],
}


def order_agents(agent_ids: List[str]) -> List[str]:
    """去重并按系统固定执行顺序排序 agent。"""
    unique = []
    seen = set()
    for agent_id in agent_ids:
        if agent_id in AGENT_REGISTRY and agent_id not in seen:
            seen.add(agent_id)
            unique.append(agent_id)
    return sorted(unique, key=lambda item: AGENT_EXECUTION_ORDER.index(item))


def get_skill_owner(skill_name: str, overrides: Optional[Dict[str, str]] = None) -> Optional[str]:
    """返回技能归属 agent，优先使用 overrides。"""
    if overrides:
        owner = overrides.get(skill_name, "")
        if owner in AGENT_REGISTRY:
            return owner
    for agent_id, definition in AGENT_REGISTRY.items():
        if skill_name in definition.owned_skills:
            return agent_id
    return None
