from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from beauty_saas_agent.models import PromptDefinition, SkillDefinition, SkillPlugin
from beauty_saas_agent.plugin_skill_loader import (
    load_plugin_skill_definitions,
    merge_plugin_skills,
    parse_skill_markdown,
)


class PluginSkillLoaderTestCase(unittest.TestCase):
    def test_parse_skill_markdown_infers_bug_inspector_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir) / "bug-log-triage" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text(
                "\n".join(
                    [
                        "---",
                        'name: "bug-log-triage"',
                        'description: "Use for bug triage, sentry trace review, and root cause analysis."',
                        "---",
                        "",
                        "# Bug Log Triage",
                        "",
                        "Collect console stack and backend exception to locate root cause quickly.",
                    ]
                ),
                encoding="utf-8",
            )

            skill = parse_skill_markdown(skill_path, plugin_name="github-bug")

            self.assertIsNotNone(skill)
            assert skill is not None
            self.assertEqual(skill.name, "bug-log-triage")
            self.assertEqual(skill.owner_agent, "bug_inspector")
            self.assertEqual(skill.source, "plugin:github-bug")
            self.assertIn("root cause", skill.content)

    def test_parse_codex_skill_markdown_infers_frontend_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_path = Path(temp_dir) / "frontend-prototyper" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text(
                "\n".join(
                    [
                        "---",
                        'name: "frontend-prototyper"',
                        'description: "Use for React and Vue UI tasks."',
                        "---",
                        "",
                        "# Frontend Prototyper",
                        "",
                        "Build polished UI screens for browser-based apps.",
                    ]
                ),
                encoding="utf-8",
            )

            skill = parse_skill_markdown(skill_path, plugin_name="github-ui")

            self.assertIsNotNone(skill)
            assert skill is not None
            self.assertEqual(skill.name, "frontend-prototyper")
            self.assertEqual(skill.owner_agent, "frontend")
            self.assertEqual(skill.source, "plugin:github-ui")
            self.assertIn("Build polished UI screens", skill.content)

    def test_manifest_skills_override_prompt_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin_root = Path(temp_dir) / "plugin"
            plugin_root.mkdir(parents=True)
            (plugin_root / "plugin-manifest.json").write_text(
                json.dumps(
                    {
                        "skills": [
                            {
                                "name": "BackendCodeWriteSkill",
                                "title": "增强版后端代码开发",
                                "group": "外部插件Skill/后端",
                                "owner_agent": "backend",
                                "content": "新的后端实现规范",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plugin = SkillPlugin(
                plugin_id="plugin-1",
                name="external-backend",
                kind="github",
                source_dir=str(plugin_root),
                manifest_path=str(plugin_root / "plugin-manifest.json"),
            )

            prompt_definition = PromptDefinition(
                title="Prompt",
                raw_text="Prompt",
                agent_goal="goal",
                version_policy="policy",
                execution_flow=[],
                constraints=[],
                skills={
                    "BackendCodeWriteSkill": SkillDefinition(
                        name="BackendCodeWriteSkill",
                        title="旧后端技能",
                        group="（一）后端相关Skill",
                        lines=["旧规则"],
                    )
                },
            )

            merged = merge_plugin_skills(prompt_definition, [plugin])

            self.assertEqual(merged.skills["BackendCodeWriteSkill"].title, "增强版后端代码开发")
            self.assertEqual(merged.skills["BackendCodeWriteSkill"].owner_agent, "backend")
            self.assertIn("新的后端实现规范", merged.skills["BackendCodeWriteSkill"].content)

    def test_load_plugin_manifest_infers_builtin_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin_root = Path(temp_dir) / "plugin"
            plugin_root.mkdir(parents=True)
            (plugin_root / "skill-manifest.standard.json").write_text(
                json.dumps(
                    {
                        "skills": {
                            "FrontendTestSkill": {
                                "title": "前端页面自测",
                                "group": "（二）前端相关Skill",
                                "purpose": "执行前端自测",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            plugin = SkillPlugin(
                plugin_id="plugin-2",
                name="standardized-skills",
                kind="local-directory",
                source_dir=str(plugin_root),
            )

            skills = load_plugin_skill_definitions(plugin)

            self.assertEqual(skills["FrontendTestSkill"].owner_agent, "frontend")


if __name__ == "__main__":
    unittest.main()
