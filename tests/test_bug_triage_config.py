from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from beauty_saas_agent.bug_triage_config import (
    load_bug_triage_config,
    reset_bug_triage_config,
    save_bug_triage_config,
)


class BugTriageConfigTestCase(unittest.TestCase):
    def test_load_bug_triage_config_creates_default_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bug-triage.json"

            payload, payload_path = load_bug_triage_config(path)

            self.assertEqual(payload_path, str(path))
            self.assertTrue(path.exists())
            self.assertTrue(payload.get("enabled"))
            self.assertIn("keyword_sets", payload)
            self.assertIn("task", payload["keyword_sets"])  # type: ignore[index]

    def test_save_bug_triage_config_normalizes_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bug-triage.json"
            load_bug_triage_config(path)

            payload, _ = save_bug_triage_config(
                path,
                {
                    "enabled": False,
                    "keyword_sets": {"task": ["缺陷工单"]},
                    "fallback_agents": ["ops", "unknown", "backend"],
                    "skill_map": {"backend": ["BackendCodeReadSkill"]},
                },
            )

            self.assertFalse(payload["enabled"])
            self.assertIn("缺陷工单", payload["keyword_sets"]["task"])  # type: ignore[index]
            self.assertEqual(payload["fallback_agents"], ["ops", "backend"])
            self.assertEqual(payload["skill_map"]["backend"], ["BackendCodeReadSkill"])  # type: ignore[index]

    def test_reset_bug_triage_config_restores_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bug-triage.json"
            save_bug_triage_config(path, {"enabled": False})

            payload, _ = reset_bug_triage_config(path)

            self.assertTrue(payload["enabled"])
            self.assertIn("task", payload["keyword_sets"])  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
