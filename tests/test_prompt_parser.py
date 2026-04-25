from __future__ import annotations

import unittest

from beauty_saas_agent.prompt_parser import parse_prompt_definition


SAMPLE_PROMPT = """
美业SaaS自动迭代智能体

一、Agent身份与核心目标
你是一个自动化智能体

二、全局版本号机制（强制统一）
版本规则：v主.次.迭代

三、核心Skill清单及能力定义
（一）后端相关Skill
BackendCodeWriteSkill（后端代码开发）
编写后端接口
添加日志
BackendTestSkill（后端一体化测试）
生成测试用例

四、标准执行流程（严格按顺序执行）
确认版本号
执行后端开发

五、强制行为约束
接口必须带版本号
测试失败禁止部署
""".strip()


class PromptParserTestCase(unittest.TestCase):
    def test_parse_prompt_definition_extracts_skills_and_sections(self) -> None:
        definition = parse_prompt_definition(SAMPLE_PROMPT)

        self.assertEqual(definition.title, "美业SaaS自动迭代智能体")
        self.assertIn("自动化智能体", definition.agent_goal)
        self.assertIn("版本规则", definition.version_policy)
        self.assertEqual(definition.execution_flow, ["确认版本号", "执行后端开发"])
        self.assertEqual(definition.constraints, ["接口必须带版本号", "测试失败禁止部署"])
        self.assertEqual(sorted(definition.skills), ["BackendCodeWriteSkill", "BackendTestSkill"])
        self.assertIn("添加日志", definition.skills["BackendCodeWriteSkill"].content)


if __name__ == "__main__":
    unittest.main()
