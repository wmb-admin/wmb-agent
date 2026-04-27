from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from beauty_saas_agent.config import Settings
from beauty_saas_agent.workspace_profile import load_workspace_profile, load_workspace_secrets


class WorkspaceProfileTestCase(unittest.TestCase):
    def test_load_workspace_profile_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "profile.json"
            secrets_path = root / "secrets.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "repos": [
                            {
                                "name": "backend",
                                "kind": "backend",
                                "remote_url": "https://example.com/backend.git",
                                "branch": "dev",
                                "local_path": "/tmp/backend"
                            }
                        ],
                        "toolchain": {
                            "maven_bin": "/opt/mvn/bin/mvn",
                            "java_bin": "/usr/bin/java",
                            "pnpm_bin": "/usr/local/bin/pnpm"
                        },
                        "git_policy": {
                            "allow_branch_delete": False,
                            "forbidden_operations": ["git branch -D"]
                        },
                        "services": [
                            {
                                "name": "mysql",
                                "host": "127.0.0.1",
                                "port": 3306,
                                "username": "root",
                                "password": "test-password",
                                "database": "ruoyi-vue-pro"
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            secrets_path.write_text(
                json.dumps(
                    {
                        "git_auth": {
                            "username": "demo",
                            "password": "git-password"
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            settings = Settings(
                prompt_docx_path="prompt.docx",
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
                workspace_secrets_path=str(secrets_path),
                prompt_registry_path=str(root / "prompt-registry.json"),
                skill_plugin_registry_path=str(root / "skill-plugins.json"),
                skill_import_root=str(root / "imported-skills"),
                workflow_preset_path=str(root / "workflow-presets.json"),
            )

            profile = load_workspace_profile(settings)
            secrets = load_workspace_secrets(settings)

            self.assertEqual(profile.repos[0].name, "backend")
            self.assertEqual(profile.toolchain.maven_bin, "/opt/mvn/bin/mvn")
            self.assertEqual(profile.toolchain.java_bin, "/usr/bin/java")
            self.assertEqual(profile.toolchain.pnpm_bin, "/usr/local/bin/pnpm")
            self.assertEqual(profile.git_policy.forbidden_operations, ["git branch -D"])
            self.assertEqual(profile.services[0].name, "mysql")
            self.assertEqual(profile.services[0].database, "ruoyi-vue-pro")
            self.assertEqual(secrets.git_username, "demo")
            self.assertEqual(secrets.git_password, "git-password")


if __name__ == "__main__":
    unittest.main()
