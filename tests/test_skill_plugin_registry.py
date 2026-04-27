from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from beauty_saas_agent.config import Settings
from beauty_saas_agent.skill_plugin_registry import SkillPluginRegistry


class SkillPluginRegistryTestCase(unittest.TestCase):
    def test_register_local_skill_plugin_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_dir = root / "skills"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "DemoSkill.md").write_text("# DemoSkill", encoding="utf-8")

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

            registry = SkillPluginRegistry(settings)
            plugin = registry.register(name="demo", source_dir=str(plugin_dir), owner_agent="backend")
            self.assertEqual(plugin.name, "demo")
            self.assertEqual(plugin.skills, ["DemoSkill"])
            self.assertEqual(plugin.owner_agent, "backend")

    def test_list_active_plugins_respects_curated_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_dir = root / "skills"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "DemoSkill.md").write_text("# DemoSkill", encoding="utf-8")

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
                skill_runtime_mode="curated",
                skill_plugin_allowlist=["demo"],
                skill_plugin_blocklist=[],
            )

            registry = SkillPluginRegistry(settings)
            registry.register(name="demo", source_dir=str(plugin_dir), owner_agent="backend")

            active_plugins = registry.list_active_plugins()
            self.assertEqual([plugin.name for plugin in active_plugins], ["demo"])


if __name__ == "__main__":
    unittest.main()
