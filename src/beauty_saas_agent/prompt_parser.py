from __future__ import annotations

import re
from typing import Dict, List

from .models import PromptDefinition, SkillDefinition


SKILL_HEADING_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]+Skill)（(.+)）$")
IGNORABLE_LINE_RE = re.compile(r"^[（(].*AI生成.*[）)]$")


def _normalize_lines(text: str) -> List[str]:
    """清洗原始 prompt 文本，移除空行和无效行。"""
    normalized = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or IGNORABLE_LINE_RE.match(line):
            continue
        normalized.append(line)
    return normalized


def _join_lines(lines: List[str]) -> str:
    """把分散行拼回多行文本。"""
    return "\n".join(lines).strip()


def parse_prompt_definition(text: str) -> PromptDefinition:
    """把文档文本解析为结构化 PromptDefinition。"""
    lines = _normalize_lines(text)
    title = lines[0] if lines else "Untitled Prompt"

    section = ""
    skill_group = "未分组"
    agent_lines: List[str] = []
    version_lines: List[str] = []
    flow_lines: List[str] = []
    constraint_lines: List[str] = []
    skills: Dict[str, SkillDefinition] = {}
    current_skill: SkillDefinition | None = None

    def flush_current_skill() -> None:
        """结束当前技能块并落库到 skills 字典。"""
        nonlocal current_skill
        if current_skill is not None:
            skills[current_skill.name] = current_skill
            current_skill = None

    for line in lines[1:]:
        if line.startswith("一、"):
            flush_current_skill()
            section = "agent"
            continue
        if line.startswith("二、"):
            flush_current_skill()
            section = "version"
            continue
        if line.startswith("三、"):
            flush_current_skill()
            section = "skills"
            continue
        if line.startswith("四、"):
            flush_current_skill()
            section = "flow"
            continue
        if line.startswith("五、"):
            flush_current_skill()
            section = "constraints"
            continue

        if section == "skills" and line.startswith("（") and line.endswith("Skill"):
            skill_group = line
            continue

        if section == "skills":
            match = SKILL_HEADING_RE.match(line)
            if match:
                flush_current_skill()
                current_skill = SkillDefinition(
                    name=match.group(1),
                    title=match.group(2),
                    group=skill_group,
                )
                continue

        if current_skill is not None:
            current_skill.lines.append(line)
            continue

        if section == "agent":
            agent_lines.append(line)
        elif section == "version":
            version_lines.append(line)
        elif section == "flow":
            flow_lines.append(line)
        elif section == "constraints":
            constraint_lines.append(line)

    flush_current_skill()

    return PromptDefinition(
        title=title,
        raw_text=text.strip(),
        agent_goal=_join_lines(agent_lines),
        version_policy=_join_lines(version_lines),
        execution_flow=flow_lines,
        constraints=constraint_lines,
        skills=skills,
    )
