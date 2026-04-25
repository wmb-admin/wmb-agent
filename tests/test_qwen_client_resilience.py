from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from beauty_saas_agent.config import Settings
from beauty_saas_agent.models import ChatMessage
from beauty_saas_agent.qwen_client import ModelClient, ModelRequestError


def _build_settings() -> Settings:
    return Settings(
        prompt_docx_path="prompt.docx",
        model_provider="openai-compatible",
        model_base_url="http://127.0.0.1:8000/v1",
        model_name="qwen-v2",
        model_api_key="",
        agent_http_host="127.0.0.1",
        agent_http_port=8787,
        request_timeout=120,
        task_storage_dir=str(Path(".data/tasks")),
        task_sqlite_path=str(Path(".data/tasks/task_runs.sqlite3")),
        workspace_profile_path=str(Path(".agent/workspace-profile.local.json")),
        workspace_secrets_path=str(Path(".agent/workspace-secrets.local.json")),
        prompt_registry_path=str(Path(".agent/prompt-registry.local.json")),
        skill_plugin_registry_path=str(Path(".agent/skill-plugins.local.json")),
        skill_import_root=str(Path("skills/imported")),
        workflow_preset_path=str(Path(".agent/workflow-presets.local.json")),
        model_retry_attempts=1,
        model_retry_backoff_ms=0,
        model_retry_backoff_max_ms=0,
        model_circuit_fail_threshold=2,
        model_circuit_open_seconds=60,
    )


class QwenClientResilienceTestCase(unittest.TestCase):
    def test_chat_retries_once_then_succeeds(self) -> None:
        client = ModelClient(_build_settings())
        message = [ChatMessage(role="user", content="ping")]
        with patch.object(
            client,
            "_chat_with_openai_compatible",
            side_effect=[ModelRequestError("temporary", retryable=True), "OK"],
        ) as mocked:
            self.assertEqual(client.chat(message), "OK")
            self.assertEqual(mocked.call_count, 2)

    def test_circuit_breaker_opens_after_consecutive_failures(self) -> None:
        client = ModelClient(_build_settings())
        message = [ChatMessage(role="user", content="ping")]
        with patch.object(
            client,
            "_chat_with_openai_compatible",
            side_effect=ModelRequestError("down", retryable=False),
        ) as mocked:
            with self.assertRaises(RuntimeError):
                client.chat(message)
            with self.assertRaises(RuntimeError):
                client.chat(message)
            with self.assertRaises(RuntimeError) as ctx:
                client.chat(message)
            self.assertIn("circuit breaker is open", str(ctx.exception))
            self.assertEqual(mocked.call_count, 2)

    def test_stream_retries_when_failure_happens_before_first_chunk(self) -> None:
        client = ModelClient(_build_settings())
        message = [ChatMessage(role="user", content="stream")]
        state = {"count": 0}

        def stream_once(_messages: list[ChatMessage]):
            if state["count"] == 0:
                state["count"] += 1

                def failed():
                    raise ModelRequestError("temporary", retryable=True)
                    yield ""  # pragma: no cover

                return failed()

            def succeeded():
                yield "A"
                yield "B"

            return succeeded()

        with patch.object(client, "_chat_stream_with_openai_compatible", side_effect=stream_once) as mocked:
            chunks = list(client.chat_stream(message))
            self.assertEqual(chunks, ["A", "B"])
            self.assertEqual(mocked.call_count, 2)

    def test_stream_does_not_retry_after_partial_output(self) -> None:
        client = ModelClient(_build_settings())
        message = [ChatMessage(role="user", content="stream")]

        def partial_then_error(_messages: list[ChatMessage]):
            def stream():
                yield "partial"
                raise ModelRequestError("temporary", retryable=True)

            return stream()

        with patch.object(client, "_chat_stream_with_openai_compatible", side_effect=partial_then_error) as mocked:
            iterator = client.chat_stream(message)
            self.assertEqual(next(iterator), "partial")
            with self.assertRaises(RuntimeError):
                next(iterator)
            self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
