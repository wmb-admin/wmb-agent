from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from .models import PromptDefinition, SkillDefinition, StandardSkillDefinition
from .skill_templates import build_standard_skill_definition


def _slugify_skill_name(name: str) -> str:
    """把技能名转换为文件名。"""
    return name.replace(" ", "-").strip()


def _render_skill_markdown(skill: SkillDefinition, source_title: str) -> str:
    """渲染原始技能 markdown。"""
    return (
        f"# {skill.name}\n\n"
        f"- 中文名称: {skill.title}\n"
        f"- 所属分组: {skill.group}\n"
        f"- 来源Prompt: {source_title}\n\n"
        "## Skill Prompt\n\n"
        f"{skill.content}\n"
    )


def _render_bullet_lines(items: list[str]) -> str:
    """渲染无序列表文本。"""
    if not items:
        return "- 无\n"
    return "".join(f"- {item}\n" for item in items)


def _render_numbered_lines(items: list[str]) -> str:
    """渲染有序列表文本。"""
    if not items:
        return "1. 无\n"
    return "".join(f"{index}. {item}\n" for index, item in enumerate(items, start=1))


def _render_standard_skill_markdown(skill: StandardSkillDefinition) -> str:
    """渲染标准化技能 markdown。"""
    return (
        f"# {skill.name}\n\n"
        f"- 中文名称: {skill.title}\n"
        f"- 所属分组: {skill.group}\n"
        f"- 来源Prompt: {skill.source_prompt}\n"
        "- 模板说明: 以下输入、输出、约束与交接项基于原始 Prompt 结构化整理，便于接入 Agent。\n\n"
        "## 核心目标\n\n"
        f"{skill.purpose}\n\n"
        "## 触发时机\n\n"
        f"{_render_bullet_lines(skill.when_to_use)}\n"
        "## 输入\n\n"
        f"{_render_bullet_lines(skill.inputs)}\n"
        "## 输出\n\n"
        f"{_render_bullet_lines(skill.outputs)}\n"
        "## 硬性约束\n\n"
        f"{_render_bullet_lines(skill.constraints)}\n"
        "## 执行清单\n\n"
        f"{_render_numbered_lines(skill.checklist)}\n"
        "## 交接对象\n\n"
        f"{_render_bullet_lines(skill.handoff_to)}\n"
        "## 原始 Prompt\n\n"
        f"{skill.raw_prompt}\n"
    )


def _build_standard_skill_map(definition: PromptDefinition) -> Dict[str, StandardSkillDefinition]:
    """构建标准化技能缓存，避免重复转换。"""
    return {
        skill_name: build_standard_skill_definition(skill, definition.title)
        for skill_name, skill in definition.skills.items()
    }


def build_skill_manifest(definition: PromptDefinition) -> Dict[str, object]:
    """生成原始技能 manifest。"""
    return {
        "title": definition.title,
        "execution_flow": definition.execution_flow,
        "constraints": definition.constraints,
        "skills": {
            name: {
                "title": skill.title,
                "group": skill.group,
                "content": skill.content,
            }
            for name, skill in definition.skills.items()
        },
    }


def build_standard_skill_manifest(definition: PromptDefinition) -> Dict[str, object]:
    """生成标准化技能 manifest。"""
    standard_skills = _build_standard_skill_map(definition)
    return {
        "title": definition.title,
        "note": "以下 standardized skill 中的输入、输出、约束、清单为基于原始 Prompt 的结构化整理。",
        "execution_flow": definition.execution_flow,
        "constraints": definition.constraints,
        "skills": {
            name: {
                "title": standard_skill.title,
                "group": standard_skill.group,
                "purpose": standard_skill.purpose,
                "when_to_use": standard_skill.when_to_use,
                "inputs": standard_skill.inputs,
                "outputs": standard_skill.outputs,
                "constraints": standard_skill.constraints,
                "checklist": standard_skill.checklist,
                "handoff_to": standard_skill.handoff_to,
                "raw_prompt": standard_skill.raw_prompt,
            }
            for name, standard_skill in standard_skills.items()
        },
    }


def export_skills(definition: PromptDefinition, output_dir: str | Path) -> Dict[str, Path]:
    """导出原始技能 markdown + manifest + 目录索引。"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    written_files: Dict[str, Path] = {}
    for skill_name, skill in definition.skills.items():
        filename = f"{_slugify_skill_name(skill_name)}.md"
        path = output_path / filename
        path.write_text(_render_skill_markdown(skill, definition.title), encoding="utf-8")
        written_files[skill_name] = path

    manifest_path = output_path / "skill-manifest.json"
    manifest_path.write_text(
        json.dumps(build_skill_manifest(definition), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    written_files["manifest"] = manifest_path

    catalog_lines = [
        f"# Skill Catalog",
        "",
        f"来源 Prompt: {definition.title}",
        "",
        "## Skills",
        "",
    ]
    for skill_name, skill in definition.skills.items():
        filename = f"{_slugify_skill_name(skill_name)}.md"
        catalog_lines.extend(
            [
                f"### {skill_name}",
                f"- 中文名称: {skill.title}",
                f"- 所属分组: {skill.group}",
                f"- 文件: `{filename}`",
                "",
            ]
        )
    catalog_path = output_path / "README.md"
    catalog_path.write_text("\n".join(catalog_lines).strip() + "\n", encoding="utf-8")
    written_files["catalog"] = catalog_path
    return written_files


def export_standardized_skills(definition: PromptDefinition, output_dir: str | Path) -> Dict[str, Path]:
    """导出标准化技能 markdown + manifest + 目录索引。"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    standard_skills = _build_standard_skill_map(definition)

    written_files: Dict[str, Path] = {}
    for skill_name, standard_skill in standard_skills.items():
        filename = f"{_slugify_skill_name(skill_name)}.md"
        path = output_path / filename
        path.write_text(_render_standard_skill_markdown(standard_skill), encoding="utf-8")
        written_files[skill_name] = path

    manifest_path = output_path / "skill-manifest.standard.json"
    manifest_path.write_text(
        json.dumps(build_standard_skill_manifest(definition), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    written_files["manifest"] = manifest_path

    catalog_lines = [
        "# Standardized Skill Catalog",
        "",
        f"来源 Prompt: {definition.title}",
        "",
        "说明: 输入、输出、约束、清单和交接对象为基于原始 Prompt 的结构化整理，方便后续接入本地 Agent。",
        "",
        "## Skills",
        "",
    ]
    for skill_name, standard_skill in standard_skills.items():
        filename = f"{_slugify_skill_name(skill_name)}.md"
        original_skill = definition.skills[skill_name]
        catalog_lines.extend(
            [
                f"### {skill_name}",
                f"- 中文名称: {original_skill.title}",
                f"- 所属分组: {original_skill.group}",
                f"- 核心目标: {standard_skill.purpose}",
                f"- 文件: `{filename}`",
                "",
            ]
        )
    catalog_path = output_path / "README.md"
    catalog_path.write_text("\n".join(catalog_lines).strip() + "\n", encoding="utf-8")
    written_files["catalog"] = catalog_path
    return written_files
