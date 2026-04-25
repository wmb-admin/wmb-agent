from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from beauty_saas_agent.config import Settings
from beauty_saas_agent.repo_manager import RepoManager


class RepoManagerExecutionTestCase(unittest.TestCase):
    def test_resolve_execution_repo_names_from_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
                prompt_docx_path=str(root / "prompt.docx"),
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

            manager = RepoManager(settings)

            self.assertEqual(
                manager.resolve_execution_repo_names(["orchestrator", "backend"], []),
                ["backend"],
            )
            self.assertEqual(
                manager.resolve_execution_repo_names(["orchestrator", "ops"], []),
                ["backend", "frontend"],
            )

    def test_execute_repo_commands_runs_and_records_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
                                "build_commands": ["printf build-ok"],
                                "test_commands": ["printf test-ok"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path=str(root / "prompt.docx"),
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

            manager = RepoManager(settings)
            results = manager.execute_repo_commands(["backend"], ["build", "test"], timeout_seconds=30)

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].status, "completed")
            self.assertEqual(results[0].phase, "build")
            self.assertIn("build-ok", results[0].stdout)
            self.assertEqual(results[1].status, "completed")
            self.assertEqual(results[1].phase, "test")
            self.assertIn("test-ok", results[1].stdout)

    def test_execute_repo_commands_marks_missing_phase_as_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
                prompt_docx_path=str(root / "prompt.docx"),
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

            manager = RepoManager(settings)
            results = manager.execute_repo_commands(["backend"], ["test"], timeout_seconds=30)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].status, "skipped")
            self.assertIn("No test commands configured", results[0].reason)

    def test_read_file_diff_returns_current_worktree_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backend_dir = root / "backend"
            backend_dir.mkdir()
            subprocess.run(["git", "init"], cwd=str(backend_dir), check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(backend_dir), check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(backend_dir), check=True)
            file_path = backend_dir / "service.txt"
            file_path.write_text("line-1\n", encoding="utf-8")
            subprocess.run(["git", "add", "service.txt"], cwd=str(backend_dir), check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=str(backend_dir), check=True, capture_output=True, text=True)
            file_path.write_text("line-1\nline-2\n", encoding="utf-8")

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
                prompt_docx_path=str(root / "prompt.docx"),
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

            manager = RepoManager(settings)
            payload = manager.read_file_diff(file_path)

            self.assertTrue(payload["in_repo"])
            self.assertEqual(payload["repo_name"], "backend")
            self.assertIn("+line-2", payload["diff"])

    def test_stop_running_processes_filters_targets_and_updates_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path=str(root / "prompt.docx"),
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
            manager = RepoManager(settings)

            registered = [
                {
                    "repo_name": "backend",
                    "phase": "start",
                    "command": "mvn spring-boot:run",
                    "cwd": str(backend_dir),
                    "pid": 10101,
                    "log_path": str(manager.process_log_dir / "backend.log"),
                    "started_at": manager._now(),
                },
                {
                    "repo_name": "frontend",
                    "phase": "start",
                    "command": "pnpm dev",
                    "cwd": str(frontend_dir),
                    "pid": 20202,
                    "log_path": str(manager.process_log_dir / "frontend.log"),
                    "started_at": manager._now(),
                },
            ]

            with patch.object(manager, "_cleanup_process_registry", return_value=registered), \
                patch.object(
                    manager,
                    "_terminate_process",
                    return_value={"status": "stopped", "signal": "SIGTERM(group)", "reason": "", "alive": False},
                ) as terminate_mock, \
                patch.object(manager, "_write_process_registry") as write_registry_mock:
                stopped_items = manager.stop_running_processes(repo_name="backend", phase="start")
                self.assertEqual(len(stopped_items), 1)
                self.assertEqual(stopped_items[0].get("repo_name"), "backend")
                self.assertEqual(stopped_items[0].get("stop_status"), "stopped")
                terminate_mock.assert_called_once_with(10101)
                write_registry_mock.assert_called_once()
                written_payload = write_registry_mock.call_args[0][0]
                self.assertEqual(len(written_payload["processes"]), 1)
                self.assertEqual(written_payload["processes"][0]["repo_name"], "frontend")

    def test_should_run_in_background_for_full_spring_boot_plugin_goal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
                prompt_docx_path=str(root / "prompt.docx"),
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
            manager = RepoManager(settings)

            command = "mvn -f ./gateway/pom.xml org.springframework.boot:spring-boot-maven-plugin:3.5.13:run -Dspring-boot.run.profiles=dev"
            self.assertTrue(manager._should_run_in_background(command))


if __name__ == "__main__":
    unittest.main()
