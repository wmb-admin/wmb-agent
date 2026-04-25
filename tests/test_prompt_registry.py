from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from beauty_saas_agent.config import Settings
from beauty_saas_agent.prompt_registry import PromptRegistry


class PromptRegistryTestCase(unittest.TestCase):
    def test_register_and_activate_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            docx_path = root / "prompt.docx"
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>测试 Prompt</w:t></w:r></w:p>
  </w:body>
</w:document>
""",
                )

            settings = Settings(
                prompt_docx_path=str(docx_path),
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

            registry = PromptRegistry(settings)
            items = registry.list_entries()
            self.assertEqual(len(items), 1)
            self.assertTrue(items[0].is_active)

            second_path = root / "prompt-2.docx"
            with zipfile.ZipFile(second_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>第二个 Prompt</w:t></w:r></w:p>
  </w:body>
</w:document>
""",
                )

            second = registry.register(str(second_path), label="second")
            active = registry.activate(second.prompt_id)
            self.assertEqual(active.prompt_id, second.prompt_id)
            self.assertEqual(registry.get_active_entry().prompt_id, second.prompt_id)


if __name__ == "__main__":
    unittest.main()
