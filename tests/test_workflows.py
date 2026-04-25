from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from beauty_saas_agent.config import Settings
from beauty_saas_agent.workflows import load_workflow_catalog


class WorkflowCatalogTestCase(unittest.TestCase):
    def test_load_workflow_catalog_creates_default_local_presets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
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
                workspace_profile_path=str(root / "workspace-profile.json"),
                workspace_secrets_path=str(root / "workspace-secrets.json"),
                prompt_registry_path=str(root / "prompt-registry.json"),
                skill_plugin_registry_path=str(root / "skill-plugins.json"),
                skill_import_root=str(root / "imported-skills"),
                workflow_preset_path=str(root / "workflow-presets.json"),
            )

            workflow_presets, workflow_agent_presets, workflow_path = load_workflow_catalog(settings)

            self.assertEqual(workflow_path, str(root / "workflow-presets.json"))
            self.assertIn("bug_fix", workflow_presets)
            self.assertIn("frontend_enhanced", workflow_presets)
            self.assertIn("frontend_visual_upgrade", workflow_presets)
            self.assertIn("frontend_regression", workflow_presets)
            self.assertIn("backend_tdd", workflow_presets)
            self.assertIn("backend_api_tdd", workflow_presets)
            self.assertIn("backend_change_review", workflow_presets)
            self.assertIn("pre_release_audit", workflow_presets)
            self.assertEqual(workflow_agent_presets["bug_fix"], ["orchestrator", "bug_inspector"])
            self.assertEqual(workflow_agent_presets["backend_tdd"], ["orchestrator", "backend"])
            self.assertEqual(workflow_agent_presets["backend_change_review"], ["orchestrator", "backend", "ops"])
            self.assertEqual(
                workflow_agent_presets["pre_release_audit"],
                ["orchestrator", "backend", "frontend", "ops"],
            )
            self.assertTrue(Path(workflow_path).exists())

    def test_load_workflow_catalog_merges_custom_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow_path = root / "workflow-presets.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "workflows": {
                            "custom_release": {
                                "agents": ["orchestrator", "ops"],
                                "skills": ["gh-fix-ci", "sentry"],
                            }
                        }
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
                workspace_profile_path=str(root / "workspace-profile.json"),
                workspace_secrets_path=str(root / "workspace-secrets.json"),
                prompt_registry_path=str(root / "prompt-registry.json"),
                skill_plugin_registry_path=str(root / "skill-plugins.json"),
                skill_import_root=str(root / "imported-skills"),
                workflow_preset_path=str(workflow_path),
            )

            workflow_presets, workflow_agent_presets, _ = load_workflow_catalog(settings)

            self.assertEqual(workflow_presets["custom_release"], ["gh-fix-ci", "sentry"])
            self.assertEqual(workflow_agent_presets["custom_release"], ["orchestrator", "ops"])
            self.assertIn("backend_only", workflow_presets)


if __name__ == "__main__":
    unittest.main()
