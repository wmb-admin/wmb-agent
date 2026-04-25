from __future__ import annotations

import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from beauty_saas_agent.agent_planner import build_execution_plan
from beauty_saas_agent.config import Settings
from beauty_saas_agent.models import ChatRequest
from beauty_saas_agent.task_store import TaskStore


class TaskStoreTestCase(unittest.TestCase):
    def test_task_store_persists_and_loads_task_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                prompt_docx_path="prompt.docx",
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
            store = TaskStore(settings)
            request = ChatRequest(
                task="设计会员充值流程",
                version="v1.0.0",
                workflow="backend_only",
                skills=["BackendCodeWriteSkill"],
            )
            plan = build_execution_plan(
                workflow="backend_only",
                requested_agents=[],
                resolved_skills=["BackendCodeWriteSkill"],
                explicit_skills=["BackendCodeWriteSkill"],
            )

            state = store.start_task(request, plan, ["BackendCodeWriteSkill"])
            state["status"] = "completed"
            state["plan"] = asdict(plan)
            state["response"] = {
                "task_id": state["task_id"],
                "status": "completed",
                "content": "ok",
            }
            store.save_state(state)

            tasks = store.list_tasks(limit=10)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task_id, state["task_id"])
            self.assertEqual(tasks[0].status, "completed")
            summary = store.dashboard_summary()
            self.assertEqual(summary["completed_tasks"], 1)
            self.assertEqual(summary["blocked_tasks"], 0)
            self.assertEqual(summary["canceled_tasks"], 0)

            detail = store.get_task(state["task_id"])
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["task_id"], state["task_id"])
            self.assertEqual(detail["response"]["content"], "ok")

    def test_list_events_supports_incremental_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                prompt_docx_path="prompt.docx",
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
            store = TaskStore(settings)
            request = ChatRequest(
                task="事件增量拉取测试",
                version="v1.0.0",
                workflow="backend_only",
            )
            plan = build_execution_plan(
                workflow="backend_only",
                requested_agents=[],
                resolved_skills=["BackendCodeWriteSkill"],
                explicit_skills=[],
            )
            state = store.start_task(request, plan, [])
            first = store.append_event(state["task_id"], "task_started", {"stage": 1})
            second = store.append_event(state["task_id"], "agent_step_started", {"stage": 2})
            third = store.append_event(state["task_id"], "agent_step_delta", {"stage": 3})

            all_events = store.list_events(state["task_id"])
            self.assertEqual([item.event_type for item in all_events], ["task_started", "agent_step_started", "agent_step_delta"])
            self.assertTrue(first.event_id < second.event_id < third.event_id)

            tail_events = store.list_events(state["task_id"], after_event_id=second.event_id)
            self.assertEqual(len(tail_events), 1)
            self.assertEqual(tail_events[0].event_id, third.event_id)
            self.assertEqual(tail_events[0].payload["stage"], 3)

    def test_housekeeping_prunes_expired_tasks_and_archives_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                prompt_docx_path="prompt.docx",
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
                task_auto_cleanup=False,
            )
            store = TaskStore(settings)
            request = ChatRequest(
                task="过期任务清理",
                version="v1.0.0",
                workflow="backend_only",
            )
            plan = build_execution_plan(
                workflow="backend_only",
                requested_agents=[],
                resolved_skills=["BackendCodeWriteSkill"],
                explicit_skills=[],
            )
            state = store.start_task(request, plan, [])
            old_timestamp = "2000-01-01T00:00:00+00:00"
            state["created_at"] = old_timestamp
            state["updated_at"] = old_timestamp
            state["status"] = "completed"
            store.save_state(state, touch_updated_at=False)
            store.append_event(state["task_id"], "task_started", {"stage": "old"})
            with store._connect() as connection:
                connection.execute(
                    "UPDATE task_events SET created_at = ? WHERE task_id = ?",
                    (old_timestamp, state["task_id"]),
                )

            result = store.housekeeping(
                task_retention_days=1,
                event_retention_days=1,
                max_runs=2000,
                archive_pruned=True,
            )

            self.assertEqual(result["pruned_task_runs"], 1)
            self.assertIsNone(store.get_task(state["task_id"]))
            archive_dir = Path(settings.task_storage_dir) / "archive" / "snapshots"
            archived = list(archive_dir.glob(f"{state['task_id']}-*.json"))
            self.assertTrue(archived)

    def test_housekeeping_prunes_overflow_tasks_by_max_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                prompt_docx_path="prompt.docx",
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
                task_auto_cleanup=False,
            )
            store = TaskStore(settings)
            request = ChatRequest(task="max runs 清理", version="v1.0.0", workflow="backend_only")
            plan = build_execution_plan(
                workflow="backend_only",
                requested_agents=[],
                resolved_skills=["BackendCodeWriteSkill"],
                explicit_skills=[],
            )

            older = store.start_task(request, plan, [])
            older["updated_at"] = "2024-01-01T00:00:00+00:00"
            store.save_state(older, touch_updated_at=False)

            newer = store.start_task(request, plan, [])
            newer["updated_at"] = "2026-01-01T00:00:00+00:00"
            store.save_state(newer, touch_updated_at=False)

            result = store.housekeeping(
                task_retention_days=0,
                event_retention_days=0,
                max_runs=1,
                archive_pruned=False,
            )

            self.assertEqual(result["pruned_task_runs"], 1)
            tasks = store.list_tasks(limit=10)
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task_id, newer["task_id"])


if __name__ == "__main__":
    unittest.main()
