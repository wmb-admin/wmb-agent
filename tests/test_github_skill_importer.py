from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from beauty_saas_agent.config import Settings
from beauty_saas_agent.github_skill_importer import GitHubSkillImporter, parse_github_source


class GitHubSkillImporterTestCase(unittest.TestCase):
    def test_parse_github_source_from_tree_url(self) -> None:
        repo, ref, paths, url = parse_github_source(
            url="https://github.com/openai/skills/tree/main/skills/.curated/openai-docs"
        )

        self.assertEqual(repo, "openai/skills")
        self.assertEqual(ref, "main")
        self.assertEqual(paths, ["skills/.curated/openai-docs"])
        self.assertIn("openai-docs", url)

    def test_write_manifest_discovers_imported_skills(self) -> None:
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
            importer = GitHubSkillImporter(settings)
            plugin_root = root / "imported-skills" / "demo-plugin"
            skill_root = plugin_root / "frontend-prototyper"
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                "\n".join(
                    [
                        "---",
                        'name: "frontend-prototyper"',
                        'description: "Use for React UI work."',
                        "---",
                        "",
                        "# Frontend Prototyper",
                        "",
                        "Focus on browser UI implementation.",
                    ]
                ),
                encoding="utf-8",
            )

            manifest_path = importer._write_manifest(
                plugin_root=plugin_root,
                plugin_name="demo-plugin",
                repo="openai/skills",
                ref="main",
                source_url="https://github.com/openai/skills/tree/main/skills/.curated/frontend-prototyper",
                owner_agent="frontend",
                paths=["skills/.curated/frontend-prototyper"],
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(payload["plugin_name"], "demo-plugin")
            self.assertEqual(payload["skills"][0]["name"], "frontend-prototyper")
            self.assertEqual(payload["skills"][0]["owner_agent"], "frontend")


if __name__ == "__main__":
    unittest.main()
