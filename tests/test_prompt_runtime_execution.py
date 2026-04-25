from __future__ import annotations

import tempfile
import threading
import time
import unittest
import zipfile
import json
from pathlib import Path
from unittest.mock import Mock
from xml.sax.saxutils import escape

from beauty_saas_agent.config import Settings
from beauty_saas_agent.models import ChatRequest, ExecutionCommandResult
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
            "（四）代码规范&部署Skill",
            "CodeRuleCheckSkill（代码规范检查）",
            "检查代码规范",
            "（三）数据库&监控Skill",
            "MonitorSkill（全链路日志监控）",
            "监控异常日志",
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


class PromptRuntimeExecutionTestCase(unittest.TestCase):
    def test_apply_runtime_defaults_prefers_full_iteration_validate_and_fullstack_repos(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            backend_dir = root / "backend"
            frontend_dir = root / "frontend"
            backend_dir.mkdir()
            frontend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": str(backend_dir),
                            },
                            {
                                "name": "frontend",
                                "kind": "frontend",
                                "remote_url": "https://example.com/frontend.git",
                                "branch": "dev",
                                "local_path": str(frontend_dir),
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
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
            request = ChatRequest(
                task="实现一个会员充值需求，覆盖前后端联动并完成测试",
                version="v1.0.0",
                workflow=None,
                execution_mode="off",
            )

            normalized = runtime.apply_runtime_defaults(request)

            self.assertEqual(normalized.workflow, "full_iteration")
            self.assertEqual(normalized.execution_mode, "validate")
            self.assertEqual(normalized.repos, ["backend", "frontend"])
            self.assertIn("runtime_defaults", normalized.context)

    def test_apply_runtime_defaults_prefers_bug_fix_for_bug_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            backend_dir = root / "backend"
            frontend_dir = root / "frontend"
            backend_dir.mkdir()
            frontend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": str(backend_dir),
                            },
                            {
                                "name": "frontend",
                                "kind": "frontend",
                                "remote_url": "https://example.com/frontend.git",
                                "branch": "dev",
                                "local_path": str(frontend_dir),
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
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
            request = ChatRequest(
                task="登录接口报错 500，帮我修复这个 bug",
                version="v1.0.0",
                workflow=None,
                execution_mode="off",
            )

            normalized = runtime.apply_runtime_defaults(request)

            self.assertEqual(normalized.workflow, "bug_fix")
            self.assertEqual(normalized.execution_mode, "validate")
            self.assertEqual(normalized.repos, ["backend", "frontend"])
            self.assertIn("runtime_defaults", normalized.context)

    def test_apply_runtime_defaults_supports_custom_bug_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            backend_dir = root / "backend"
            backend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": str(backend_dir),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            bug_triage_path = root / "bug-triage-rules.json"
            bug_triage_path.write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "keyword_sets": {"task": ["缺陷工单"]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
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
                bug_triage_config_path=str(bug_triage_path),
            )
            runtime = PromptRuntime(settings)
            request = ChatRequest(
                task="这是一个缺陷工单，需要修复登录失败问题",
                version="v1.0.0",
                workflow=None,
                execution_mode="off",
            )

            normalized = runtime.apply_runtime_defaults(request)

            self.assertEqual(normalized.workflow, "bug_fix")
            self.assertEqual(normalized.execution_mode, "validate")

    def test_apply_bug_triage_routing_routes_backend_bug_to_backend_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
                model_api_key="",
                agent_http_host="127.0.0.1",
                agent_http_port=8787,
                request_timeout=120,
                task_storage_dir=str(root / "tasks"),
                task_sqlite_path=str(root / "tasks" / "task_runs.sqlite3"),
                workspace_profile_path=str(root / "workspace-profile.json"),
                workspace_secrets_path=str(root / "workspace-secrets.json"),
                prompt_registry_path=str(root / "prompt-registry.json"),
                skill_plugin_registry_path=str(root / "skill-plugins.json"),
                skill_import_root=str(root / "imported-skills"),
                workflow_preset_path=str(root / "workflow-presets.json"),
            )
            runtime = PromptRuntime(settings)
            request = ChatRequest(
                task="后端接口报错，修复登录 bug",
                version="v1.0.0",
                workflow="bug_fix",
            )
            execution_context = {
                "mode": "validate",
                "repo_names": [],
                "repo_statuses": [],
                "phases": [],
                "command_results": [],
            }

            triaged = runtime.apply_bug_triage_routing(request, execution_context)

            self.assertIn("bug_inspector", triaged.agents)
            self.assertIn("backend", triaged.agents)
            self.assertNotIn("frontend", triaged.agents)
            self.assertIn("BackendCodeReadSkill", triaged.skills)
            self.assertIn("bug_triage", triaged.context)
            self.assertEqual(triaged.context["bug_triage"]["owner_domains"], ["backend"])  # type: ignore[index]

    def test_failed_workspace_commands_inject_ops_and_diagnostic_skills(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            backend_dir = root / "backend"
            backend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": str(backend_dir),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
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
            request = ChatRequest(
                task="检查后端执行失败后的路由策略",
                version="v1.0.0",
                workflow="backend_only",
            )
            execution_context = {
                "mode": "validate",
                "repo_names": ["backend"],
                "repo_statuses": [],
                "phases": ["build", "test"],
                "command_results": [
                    ExecutionCommandResult(
                        repo_name="backend",
                        phase="test",
                        command="pytest",
                        status="failed",
                        exit_code=1,
                        stdout="FAILED tests/test_demo.py::test_create_user - AssertionError\n\n================ short test summary info =================\nFAILED tests/test_demo.py::test_create_user - AssertionError: boom\n",
                    )
                ],
            }

            recommendations = runtime.build_execution_recommendations(execution_context)
            effective_request = runtime.build_effective_request(request, execution_context, recommendations)
            blocking_reasons = runtime.build_execution_blocking_reasons(execution_context)

            self.assertIn("ops", effective_request.agents)
            self.assertIn("CodeRuleCheckSkill", effective_request.skills)
            self.assertIn("MonitorSkill", effective_request.skills)
            self.assertTrue(blocking_reasons)
            self.assertIn("workspace_blocking_reasons", effective_request.context)
            self.assertTrue(recommendations)
            self.assertEqual(recommendations[0].title, "测试执行失败")
            self.assertTrue(any("pytest" in item for item in recommendations[0].suggested_commands))
            self.assertEqual(recommendations[0].suggested_workflow, "backend_api_tdd")
            self.assertEqual(recommendations[0].suggested_execution_mode, "test")
            self.assertTrue(recommendations[0].recovery_steps)
            self.assertIn("失败用例", " ".join(recommendations[0].recovery_steps))
            self.assertTrue(recommendations[0].locations)
            self.assertTrue(recommendations[0].locations[0].path.endswith("tests/test_demo.py"))

    def test_start_failure_with_missing_main_class_prefers_profile_start_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            backend_dir = root / "backend"
            backend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            module_start_cmd = f"mvn -f {backend_dir}/gateway/pom.xml org.springframework.boot:spring-boot-maven-plugin:3.5.13:run"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": str(backend_dir),
                                "start_commands": [module_start_cmd],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
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
            execution_context = {
                "mode": "start",
                "repo_names": ["backend"],
                "repo_statuses": [],
                "phases": ["start"],
                "command_results": [
                    ExecutionCommandResult(
                        repo_name="backend",
                        phase="start",
                        command="mvn -pl gateway -am spring-boot:run",
                        status="failed",
                        exit_code=1,
                        stderr="[ERROR] Failed to execute goal org.springframework.boot:spring-boot-maven-plugin:3.5.13:run (default-cli) on project backend-root: Unable to find a suitable main class, please add a 'mainClass' property -> [Help 1]",
                    )
                ],
            }

            recommendations = runtime.build_execution_recommendations(execution_context)

            self.assertTrue(recommendations)
            self.assertEqual(recommendations[0].failure_kind, "spring-boot-main-class")
            self.assertEqual(recommendations[0].title, "Spring Boot 启动入口识别失败")
            self.assertIn(module_start_cmd, recommendations[0].suggested_commands)
            self.assertIn("backend-root", recommendations[0].failed_targets)
            self.assertEqual(recommendations[0].suggested_execution_mode, "start")

    def test_run_emits_streaming_delta_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
                model_api_key="",
                agent_http_host="127.0.0.1",
                agent_http_port=8787,
                request_timeout=120,
                task_storage_dir=str(root / "tasks"),
                task_sqlite_path=str(root / "tasks" / "task_runs.sqlite3"),
                workspace_profile_path=str(root / "workspace-profile.json"),
                workspace_secrets_path=str(root / "workspace-secrets.json"),
                prompt_registry_path=str(root / "prompt-registry.json"),
                skill_plugin_registry_path=str(root / "skill-plugins.json"),
                skill_import_root=str(root / "imported-skills"),
                workflow_preset_path=str(root / "workflow-presets.json"),
            )
            runtime = PromptRuntime(settings)
            runtime.client.chat_stream = lambda messages: iter(["hello", " world"])  # type: ignore[assignment]
            runtime.client.chat = lambda messages: "fallback text"  # type: ignore[assignment]
            runtime.repo_manager.reload = Mock()  # type: ignore[method-assign]

            response = runtime.run(
                ChatRequest(
                    task="测试流式输出事件",
                    version="v1.0.0",
                    workflow="backend_only",
                )
            )

            detail = runtime.task_store.get_task(response.task_id)
            self.assertIsNotNone(detail)
            assert detail is not None
            events = detail["events"]
            self.assertTrue(any(item["event_type"] == "agent_step_delta" for item in events))
            self.assertIn("hello world", response.content)
            runtime.repo_manager.reload.assert_called_once()

    def test_run_emits_bug_triaged_event_for_bug_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            backend_dir = root / "backend"
            backend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": str(backend_dir),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
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
            runtime.client.chat_stream = lambda messages: iter(["ok"])  # type: ignore[assignment]
            runtime.client.chat = lambda messages: "fallback text"  # type: ignore[assignment]
            runtime.repo_manager.reload = Mock()  # type: ignore[method-assign]

            response = runtime.run(
                ChatRequest(
                    task="后端接口报错 500，修复登录 bug",
                    version="v1.0.0",
                    workflow=None,
                )
            )

            detail = runtime.task_store.get_task(response.task_id)
            self.assertIsNotNone(detail)
            assert detail is not None
            bug_events = [item for item in detail["events"] if item["event_type"] == "bug_triaged"]
            self.assertTrue(bug_events)
            inspection_events = [item for item in detail["events"] if item["event_type"] == "bug_inspection_collected"]
            self.assertTrue(inspection_events)
            payload = bug_events[0]["payload"]
            self.assertIn("backend", payload.get("owner_domains", []))
            self.assertIn("bug_inspector", response.used_agents)
            self.assertIn("backend", response.used_agents)

    def test_execution_context_and_blocking_summary_use_multiline_recommendation_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            backend_dir = root / "backend"
            backend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": str(backend_dir),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
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
            execution_context = {
                "mode": "validate",
                "repo_names": ["backend"],
                "repo_statuses": [],
                "phases": ["test"],
                "command_results": [
                    ExecutionCommandResult(
                        repo_name="backend",
                        phase="test",
                        command="pytest",
                        status="failed",
                        exit_code=1,
                        stdout="FAILED tests/test_demo.py::test_create_user - AssertionError\n\n================ short test summary info =================\nFAILED tests/test_demo.py::test_create_user - AssertionError: boom\n",
                    )
                ],
            }
            recommendations = runtime.build_execution_recommendations(execution_context)
            execution_context["recommendations"] = recommendations

            context_text = runtime._format_execution_context(execution_context)  # noqa: SLF001
            self.assertIn("建议命令:\n", context_text)
            self.assertIn("恢复步骤:\n", context_text)
            self.assertNotIn("建议命令: ", context_text)
            self.assertNotIn("恢复步骤: ", context_text)

    def test_full_iteration_runs_backend_and_frontend_in_parallel_before_ops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            backend_dir = root / "backend"
            frontend_dir = root / "frontend"
            backend_dir.mkdir()
            frontend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": str(backend_dir),
                            },
                            {
                                "name": "frontend",
                                "kind": "frontend",
                                "remote_url": "https://example.com/frontend.git",
                                "branch": "dev",
                                "local_path": str(frontend_dir),
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
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
            runtime.repo_manager.reload = Mock()  # type: ignore[method-assign]

            timings: dict[str, dict[str, float]] = {}
            timings_lock = threading.Lock()

            def _agent_name(messages) -> str:
                user_text = "\n".join(item.content for item in messages if item.role == "user")
                if "BackendAgent" in user_text:
                    return "backend"
                if "FrontendAgent" in user_text:
                    return "frontend"
                if "OpsAgent" in user_text:
                    return "ops"
                return "orchestrator"

            def fake_stream(messages):
                agent_name = _agent_name(messages)
                started = time.monotonic()
                with timings_lock:
                    timings.setdefault(agent_name, {})["start"] = started
                if agent_name in {"backend", "frontend"}:
                    time.sleep(0.25)
                yield f"{agent_name}-done"
                finished = time.monotonic()
                with timings_lock:
                    timings.setdefault(agent_name, {})["end"] = finished

            runtime.client.chat_stream = fake_stream  # type: ignore[assignment]
            runtime.client.chat = lambda messages: "fallback text"  # type: ignore[assignment]

            response = runtime.run(
                ChatRequest(
                    task="并行执行前后端开发并最终由测试收口",
                    version="v1.0.0",
                    workflow="full_iteration",
                )
            )

            self.assertEqual([step.agent for step in response.steps], ["orchestrator", "backend", "frontend", "ops"])
            self.assertIn("backend", timings)
            self.assertIn("frontend", timings)
            self.assertIn("ops", timings)

            backend = timings["backend"]
            frontend = timings["frontend"]
            ops = timings["ops"]
            overlap = backend["start"] < frontend["end"] and frontend["start"] < backend["end"]
            self.assertTrue(overlap, "backend/frontend should overlap in execution window")
            self.assertGreaterEqual(
                ops["start"],
                max(backend["end"], frontend["end"]),
                "ops should start after backend/frontend both completed",
            )

    def test_run_returns_canceled_status_when_cancel_event_is_triggered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
                model_api_key="",
                agent_http_host="127.0.0.1",
                agent_http_port=8787,
                request_timeout=120,
                task_storage_dir=str(root / "tasks"),
                task_sqlite_path=str(root / "tasks" / "task_runs.sqlite3"),
                workspace_profile_path=str(root / "workspace-profile.json"),
                workspace_secrets_path=str(root / "workspace-secrets.json"),
                prompt_registry_path=str(root / "prompt-registry.json"),
                skill_plugin_registry_path=str(root / "skill-plugins.json"),
                skill_import_root=str(root / "imported-skills"),
                workflow_preset_path=str(root / "workflow-presets.json"),
            )
            runtime = PromptRuntime(settings)
            runtime.repo_manager.reload = Mock()  # type: ignore[method-assign]
            cancel_event = threading.Event()

            def fake_stream(messages):
                yield "step-start"
                cancel_event.set()
                time.sleep(0.03)
                yield "step-end"

            runtime.client.chat_stream = fake_stream  # type: ignore[assignment]
            runtime.client.chat = lambda messages: "fallback text"  # type: ignore[assignment]

            response = runtime.run(
                ChatRequest(
                    task="执行后主动取消任务",
                    version="v1.0.0",
                    workflow="backend_only",
                ),
                cancel_event=cancel_event,
            )

            self.assertEqual(response.status, "canceled")
            self.assertEqual(response.content, "任务已取消。")
            detail = runtime.task_store.get_task(response.task_id)
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["status"], "canceled")
            plan_steps = ((detail.get("plan") or {}).get("steps")) or []
            self.assertTrue(any(item.get("status") == "canceled" for item in plan_steps))
            event_types = [item["event_type"] for item in detail["events"]]
            self.assertIn("task_canceled", event_types)

    def test_run_response_contains_gate_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            backend_dir = root / "backend"
            frontend_dir = root / "frontend"
            backend_dir.mkdir()
            frontend_dir.mkdir()
            profile_path = root / "workspace-profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": str(backend_dir),
                            },
                            {
                                "name": "frontend",
                                "kind": "frontend",
                                "remote_url": "https://example.com/frontend.git",
                                "branch": "dev",
                                "local_path": str(frontend_dir),
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
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
            runtime.repo_manager.reload = Mock()  # type: ignore[method-assign]
            runtime.client.chat_stream = lambda messages: iter(["ok"])  # type: ignore[assignment]
            runtime.client.chat = lambda messages: "fallback text"  # type: ignore[assignment]

            response = runtime.run(
                ChatRequest(
                    task="执行 full iteration 并返回质量门禁结果",
                    version="v1.0.0",
                    workflow="full_iteration",
                )
            )

            gate_names = [item.gate_name for item in response.gate_results]
            self.assertIn("workspace_checks", gate_names)
            self.assertIn("dev_parallel_complete", gate_names)
            workspace_gate = next(item for item in response.gate_results if item.gate_name == "workspace_checks")
            self.assertEqual(workspace_gate.status, "passed")

    def test_run_early_cancel_after_task_created_transitions_to_canceled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
                model_api_key="",
                agent_http_host="127.0.0.1",
                agent_http_port=8787,
                request_timeout=120,
                task_storage_dir=str(root / "tasks"),
                task_sqlite_path=str(root / "tasks" / "task_runs.sqlite3"),
                workspace_profile_path=str(root / "workspace-profile.json"),
                workspace_secrets_path=str(root / "workspace-secrets.json"),
                prompt_registry_path=str(root / "prompt-registry.json"),
                skill_plugin_registry_path=str(root / "skill-plugins.json"),
                skill_import_root=str(root / "imported-skills"),
                workflow_preset_path=str(root / "workflow-presets.json"),
            )
            runtime = PromptRuntime(settings)
            runtime.repo_manager.reload = Mock()  # type: ignore[method-assign]
            runtime.client.chat_stream = lambda messages: iter(["ok"])  # type: ignore[assignment]
            runtime.client.chat = lambda messages: "fallback text"  # type: ignore[assignment]
            cancel_event = threading.Event()

            def on_task_created(task_state: dict) -> None:
                _ = task_state.get("task_id")
                cancel_event.set()

            response = runtime.run(
                ChatRequest(
                    task="任务创建后立即取消",
                    version="v1.0.0",
                    workflow="backend_only",
                ),
                on_task_created=on_task_created,
                cancel_event=cancel_event,
            )

            self.assertEqual(response.status, "canceled")
            detail = runtime.task_store.get_task(response.task_id)
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["status"], "canceled")
            event_types = [item["event_type"] for item in detail["events"]]
            self.assertIn("task_canceled", event_types)

    def test_run_cancel_during_execution_context_transitions_to_canceled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prompt_path = root / "prompt.docx"
            _write_prompt_docx(prompt_path)
            settings = Settings(
                prompt_docx_path=str(prompt_path),
                model_provider="openai-compatible",
                model_base_url="http://127.0.0.1:8000/v1",
                model_name="qwen-v2",
                model_api_key="",
                agent_http_host="127.0.0.1",
                agent_http_port=8787,
                request_timeout=120,
                task_storage_dir=str(root / "tasks"),
                task_sqlite_path=str(root / "tasks" / "task_runs.sqlite3"),
                workspace_profile_path=str(root / "workspace-profile.json"),
                workspace_secrets_path=str(root / "workspace-secrets.json"),
                prompt_registry_path=str(root / "prompt-registry.json"),
                skill_plugin_registry_path=str(root / "skill-plugins.json"),
                skill_import_root=str(root / "imported-skills"),
                workflow_preset_path=str(root / "workflow-presets.json"),
            )
            runtime = PromptRuntime(settings)
            runtime.repo_manager.reload = Mock()  # type: ignore[method-assign]

            def fake_execute_repo_commands(repo_names, phases, timeout_seconds=1800, cancel_event=None):
                _ = repo_names, phases, timeout_seconds
                if cancel_event is not None:
                    cancel_event.set()
                return []

            runtime.repo_manager.execute_repo_commands = fake_execute_repo_commands  # type: ignore[method-assign]
            runtime.repo_manager.resolve_execution_repo_names = lambda agent_ids, requested_repos: ["backend"]  # type: ignore[method-assign]
            runtime.repo_manager.repo_status_for_names = lambda names: []  # type: ignore[method-assign]
            runtime.client.chat_stream = lambda messages: iter(["ok"])  # type: ignore[assignment]
            runtime.client.chat = lambda messages: "fallback text"  # type: ignore[assignment]
            cancel_event = threading.Event()

            response = runtime.run(
                ChatRequest(
                    task="执行工作区阶段中取消",
                    version="v1.0.0",
                    workflow="backend_only",
                    execution_mode="validate",
                    repos=["backend"],
                ),
                cancel_event=cancel_event,
            )

            self.assertEqual(response.status, "canceled")
            detail = runtime.task_store.get_task(response.task_id)
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["status"], "canceled")


if __name__ == "__main__":
    unittest.main()
