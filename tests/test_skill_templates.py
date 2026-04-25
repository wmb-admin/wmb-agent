from __future__ import annotations

import unittest

from beauty_saas_agent.models import SkillDefinition
from beauty_saas_agent.skill_templates import build_standard_skill_definition


class SkillTemplateTestCase(unittest.TestCase):
    def test_build_standard_skill_definition_keeps_source_and_template_fields(self) -> None:
        skill = SkillDefinition(
            name="BackendCodeWriteSkill",
            title="后端代码开发",
            group="（一）后端相关Skill",
            lines=[
                "严格遵循芋道开发规范",
                "仅开发后端逻辑，绝不编写前端代码",
            ],
        )

        standard_skill = build_standard_skill_definition(skill, "测试 Prompt")

        self.assertEqual(standard_skill.name, "BackendCodeWriteSkill")
        self.assertEqual(standard_skill.source_prompt, "测试 Prompt")
        self.assertIn("实现后端版本化接口", standard_skill.purpose)
        self.assertIn("仅开发后端逻辑，不编写前端代码", standard_skill.constraints)
        self.assertIn("严格遵循芋道开发规范", standard_skill.raw_prompt)


if __name__ == "__main__":
    unittest.main()
