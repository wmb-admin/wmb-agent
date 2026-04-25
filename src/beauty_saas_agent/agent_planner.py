from __future__ import annotations

from typing import Dict, List, Optional

from .agent_registry import AGENT_REGISTRY, WORKFLOW_AGENT_PRESETS, get_skill_owner, order_agents
from .models import AgentExecutionStep, ExecutionPlan


def resolve_agents(
    workflow: str | None,
    requested_agents: List[str],
    explicit_skills: List[str],
    skill_owner_overrides: Optional[Dict[str, str]] = None,
    workflow_agent_presets: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """根据 workflow、显式 agent 与技能归属，计算最终执行链路。"""
    agent_ids: List[str] = []
    presets = workflow_agent_presets or WORKFLOW_AGENT_PRESETS
    if workflow:
        agent_ids.extend(presets.get(workflow, []))
    agent_ids.extend(requested_agents)
    for skill_name in explicit_skills:
        owner = get_skill_owner(skill_name, overrides=skill_owner_overrides)
        if owner:
            agent_ids.append(owner)
    if not agent_ids:
        agent_ids.append("orchestrator")
        return order_agents(agent_ids)
    # Orchestrator 永远保留在链路中，确保任务编排/交接规则生效。
    agent_ids.append("orchestrator")
    return order_agents(agent_ids)


def map_skills_to_agents(
    agent_ids: List[str],
    resolved_skills: List[str],
    skill_owner_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, List[str]]:
    """把技能分配给对应负责人；无法归属的技能回落给 orchestrator。"""
    skill_map: Dict[str, List[str]] = {agent_id: [] for agent_id in agent_ids}
    for skill_name in resolved_skills:
        owner = get_skill_owner(skill_name, overrides=skill_owner_overrides)
        if owner in skill_map:
            skill_map[owner].append(skill_name)
        elif "orchestrator" in skill_map:
            skill_map["orchestrator"].append(skill_name)
    return skill_map


def build_execution_plan(
    workflow: str | None,
    requested_agents: List[str],
    resolved_skills: List[str],
    explicit_skills: List[str] | None = None,
    skill_owner_overrides: Optional[Dict[str, str]] = None,
    workflow_agent_presets: Optional[Dict[str, List[str]]] = None,
) -> ExecutionPlan:
    """构建完整执行计划（agent 顺序、技能映射、handoff 链路）。"""
    agent_ids = resolve_agents(
        workflow,
        requested_agents,
        explicit_skills or [],
        skill_owner_overrides=skill_owner_overrides,
        workflow_agent_presets=workflow_agent_presets,
    )
    skill_map = map_skills_to_agents(
        agent_ids,
        resolved_skills,
        skill_owner_overrides=skill_owner_overrides,
    )

    steps: List[AgentExecutionStep] = []
    for index, agent_id in enumerate(agent_ids):
        next_agent = agent_ids[index + 1] if index + 1 < len(agent_ids) else None
        steps.append(
            AgentExecutionStep(
                agent=agent_id,
                title=AGENT_REGISTRY[agent_id].title,
                skills=skill_map.get(agent_id, []),
                handoff_to=next_agent,
            )
        )

    return ExecutionPlan(
        workflow=workflow,
        agents=agent_ids,
        skill_map=skill_map,
        steps=steps,
    )
