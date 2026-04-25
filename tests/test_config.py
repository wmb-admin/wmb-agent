from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from beauty_saas_agent.config import Settings


class ConfigTestCase(unittest.TestCase):
    def test_model_aliases_are_loaded_from_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "MODEL_PROVIDER=ollama",
                        "MODEL_BASE_URL=http://127.0.0.1:11434",
                        "MODEL_NAME=deepseek-coder-v2:16b",
                        "MODEL_API_KEY=",
                        "TASK_STORAGE_DIR=.data/tasks",
                        "TASK_SQLITE_PATH=.data/tasks/task_runs.sqlite3",
                    ]
                ),
                encoding="utf-8",
            )

            settings = Settings.from_env(env_path)

            self.assertEqual(settings.model_provider, "ollama")
            self.assertEqual(settings.model_base_url, "http://127.0.0.1:11434")
            self.assertEqual(settings.model_name, "deepseek-coder-v2:16b")


if __name__ == "__main__":
    unittest.main()
