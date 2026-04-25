from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from beauty_saas_agent.config import Settings
from beauty_saas_agent.models import ExecutionCommandResult
from beauty_saas_agent.prompt_builder import PromptRuntime


def _write_prompt_docx(path: Path) -> None:
    prompt_text = "\n".join(
        [
            "测试 Prompt",
            "一、",
            "测试目标",
            "二、",
            "版本规则",
            "三、",
            "（一）后端相关Skill",
            "BackendCodeReadSkill（后端代码阅读）",
            "读取后端代码",
            "BackendTestSkill（后端一体化测试）",
            "执行后端测试",
            "（二）前端相关Skill",
            "FrontendTestSkill（前端页面自测）",
            "执行前端回归测试",
            "（三）数据库&监控Skill",
            "MonitorSkill（全链路日志监控）",
            "监控异常日志",
            "（四）代码规范&部署Skill",
            "CodeRuleCheckSkill（代码规范检查）",
            "检查代码规范",
            "四、",
            "按顺序执行",
            "五、",
            "保持版本一致",
        ]
    )
    document_xml = (
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>"""
        """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>"""
        + "".join(f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in prompt_text.splitlines())
        + "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)


class ExecutionWorkflowMappingTestCase(unittest.TestCase):
    def test_frontend_typescript_failure_maps_to_frontend_regression(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            frontend_dir = root / "frontend"
            frontend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            profile_path.write_text(
                '{"repos":[{"name":"frontend","kind":"frontend","remote_url":"https://example.com/frontend.git","branch":"dev","local_path":"'
                + str(frontend_dir)
                + '"}]}',
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="ollama",
                model_base_url="http://127.0.0.1:11434",
                model_name="deepseek-coder-v2:16b",
                model_api_key="",
                agent_http_host="127.0.0.1",
                agent_http_port=8787,
                request_timeout=120,
                task_storage_dir=str(root / "tasks"),
                task_sqlite_path=str(root / "tasks" / "task_runs.sqlite3"),
                workspace_profile_path=str(profile_path),
                workspace_secrets_path=str(root / "workspace-secrets.json"),
                prompt_registry_path=str(root / "prompt-registry.json"),
                skill_plugin_registry_path=str(root / "skill-plugins.json"),
                skill_import_root=str(root / "imported-skills"),
                workflow_preset_path=str(root / "workflow-presets.json"),
            )
            runtime = PromptRuntime(settings)

            recommendation = runtime._recommendation_for_command_result(
                ExecutionCommandResult(
                    repo_name="frontend",
                    phase="test",
                    command="pnpm check:type",
                    status="failed",
                    stderr="src/views/user/index.ts:12:5 - error TS2339: Property 'age' does not exist on type 'User'.",
                )
            )

            self.assertEqual(recommendation.failure_kind, "typescript")
            self.assertEqual(recommendation.suggested_workflow, "frontend_regression")
            self.assertEqual(recommendation.suggested_execution_mode, "validate")
            self.assertTrue(recommendation.recovery_steps)
            self.assertIn("TypeScript", " ".join(recommendation.recovery_steps))
            self.assertTrue(recommendation.locations)
            self.assertTrue(recommendation.locations[0].path.endswith("src/views/user/index.ts"))


if __name__ == "__main__":
    unittest.main()
