from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Settings
from .models import ChatRequest, ExecutionPlan, TaskEvent, TaskSummary


class TaskStore:
    """任务持久化层：快照文件 + SQLite 索引/事件流。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        # 阶段1：初始化文件目录（任务目录 + 快照目录）。
        self.storage_dir = Path(settings.task_storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir = self.storage_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.archive_snapshot_dir = self.storage_dir / "archive" / "snapshots"
        self.archive_snapshot_dir.mkdir(parents=True, exist_ok=True)
        # 阶段2：初始化 SQLite 存储路径并建表。
        self.sqlite_path = Path(settings.task_sqlite_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.last_housekeeping: Dict[str, object] = {}
        if settings.task_auto_cleanup:
            try:
                self.last_housekeeping = self.housekeeping()
            except Exception as exc:  # pragma: no cover - 防御分支，避免启动时被清理异常阻断。
                self.last_housekeeping = {
                    "error": str(exc),
                    "auto": True,
                }

    def _connect(self) -> sqlite3.Connection:
        """获取 sqlite 连接，并启用字典式 row 访问。"""
        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        """初始化任务主表与事件表。"""
        with self._connect() as connection:
            # task_runs：任务主索引，便于列表检索和状态查询。
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_runs (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    workflow TEXT,
                    version TEXT NOT NULL,
                    task_text TEXT NOT NULL,
                    used_agents_json TEXT NOT NULL,
                    used_skills_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    snapshot_path TEXT NOT NULL,
                    error_message TEXT NOT NULL DEFAULT '',
                    request_json TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    response_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            # task_events：事件流，支撑实时进度展示与回放。
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_task_runs_updated_at ON task_runs(updated_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_task_events_created_at ON task_events(created_at)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_task_events_task_id ON task_events(task_id)")

    def _now(self) -> str:
        """返回 UTC ISO 时间戳。"""
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def start_task(
        self,
        request: ChatRequest,
        plan: ExecutionPlan,
        used_skills: List[str],
    ) -> Dict[str, Any]:
        """创建任务初始状态并落盘。"""
        # 阶段1：生成任务 ID、时间戳和快照路径。
        timestamp = self._now()
        task_id = uuid.uuid4().hex
        snapshot_path = self.snapshot_dir / f"{task_id}.json"
        # 阶段2：组织内存态任务结构。
        state = {
            "task_id": task_id,
            "status": "planned",
            "created_at": timestamp,
            "updated_at": timestamp,
            "workflow": request.workflow,
            "version": request.version,
            "task": request.task,
            "used_agents": plan.agents,
            "used_skills": used_skills,
            "error_message": "",
            "request": asdict(request),
            "plan": asdict(plan),
            "response": {},
            "snapshot_path": str(snapshot_path),
        }
        # 阶段3：首帧持久化（快照 + sqlite 索引）。
        self.save_state(state)
        return state

    def append_event(self, task_id: str, event_type: str, payload: Optional[Dict[str, object]] = None) -> TaskEvent:
        """写入一条任务事件。"""
        timestamp = self._now()
        serialized_payload = json.dumps(payload or {}, ensure_ascii=False)
        # 事件单独入库，便于 SSE 增量拉取。
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO task_events (
                    task_id,
                    event_type,
                    created_at,
                    payload_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    task_id,
                    event_type,
                    timestamp,
                    serialized_payload,
                ),
            )
            event_id = int(cursor.lastrowid or 0)
        return TaskEvent(
            task_id=task_id,
            event_type=event_type,
            created_at=timestamp,
            payload=payload or {},
            event_id=event_id,
        )

    def save_state(self, state: Dict[str, Any], touch_updated_at: bool = True) -> None:
        """保存任务快照，并同步更新 sqlite 索引表。"""
        # 阶段1：按需更新时间戳。
        if touch_updated_at:
            state["updated_at"] = self._now()
        # 阶段2：落盘完整快照（可用于详情与恢复）。
        snapshot_path = Path(state["snapshot_path"])
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 阶段3：写入/更新 sqlite 索引（列表查询走这里，详情读快照）。
        response_payload = state.get("response") or {}
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_runs (
                    task_id,
                    status,
                    workflow,
                    version,
                    task_text,
                    used_agents_json,
                    used_skills_json,
                    created_at,
                    updated_at,
                    snapshot_path,
                    error_message,
                    request_json,
                    plan_json,
                    response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    workflow=excluded.workflow,
                    version=excluded.version,
                    task_text=excluded.task_text,
                    used_agents_json=excluded.used_agents_json,
                    used_skills_json=excluded.used_skills_json,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at,
                    snapshot_path=excluded.snapshot_path,
                    error_message=excluded.error_message,
                    request_json=excluded.request_json,
                    plan_json=excluded.plan_json,
                    response_json=excluded.response_json
                """,
                (
                    state["task_id"],
                    state["status"],
                    state.get("workflow"),
                    state["version"],
                    state["task"],
                    json.dumps(state.get("used_agents", []), ensure_ascii=False),
                    json.dumps(state.get("used_skills", []), ensure_ascii=False),
                    state["created_at"],
                    state["updated_at"],
                    state["snapshot_path"],
                    state.get("error_message", ""),
                    json.dumps(state.get("request", {}), ensure_ascii=False),
                    json.dumps(state.get("plan", {}), ensure_ascii=False),
                    json.dumps(response_payload, ensure_ascii=False),
                ),
            )

    def list_tasks(self, limit: int = 20) -> List[TaskSummary]:
        """按时间倒序列出任务摘要。"""
        normalized_limit = max(1, int(limit))
        # 阶段1：查询主索引表。
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    task_id,
                    status,
                    workflow,
                    version,
                    task_text,
                    created_at,
                    updated_at,
                    used_agents_json,
                    used_skills_json,
                    error_message
                FROM task_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (normalized_limit,),
            ).fetchall()

        # 阶段2：反序列化为 TaskSummary 列表。
        return [
            TaskSummary(
                task_id=row["task_id"],
                status=row["status"],
                workflow=row["workflow"],
                version=row["version"],
                task=row["task_text"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                used_agents=json.loads(row["used_agents_json"]),
                used_skills=json.loads(row["used_skills_json"]),
                error_message=row["error_message"],
            )
            for row in rows
        ]

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """读取单任务完整状态（含事件）。"""
        # 阶段1：通过主索引定位快照文件路径。
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot_path
                FROM task_runs
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()

        if row is None:
            return None

        # 阶段2：读取快照正文，不存在则视为无效任务。
        snapshot_path = Path(row["snapshot_path"])
        if not snapshot_path.exists():
            return None

        # 阶段3：拼接事件流返回给详情页。
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        payload["events"] = [asdict(event) for event in self.list_events(task_id)]
        return payload

    def get_task_status(self, task_id: str) -> Optional[str]:
        """查询任务状态。"""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT status
                FROM task_runs
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row["status"])

    def list_events(
        self,
        task_id: str,
        after_event_id: int = 0,
        limit: Optional[int] = None,
    ) -> List[TaskEvent]:
        """按事件 ID 顺序读取任务事件。"""
        # 阶段1：构建分页条件。
        params: List[int | str] = [task_id, max(0, after_event_id)]
        limit_sql = ""
        if limit is not None:
            limit_sql = " LIMIT ?"
            params.append(max(1, int(limit)))
        # 阶段2：拉取事件行。
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, task_id, event_type, created_at, payload_json
                FROM task_events
                WHERE task_id = ? AND id > ?
                ORDER BY id ASC
                """
                + limit_sql,
                tuple(params),
            ).fetchall()
        # 阶段3：反序列化为 TaskEvent 列表。
        return [
            TaskEvent(
                task_id=row["task_id"],
                event_type=row["event_type"],
                created_at=row["created_at"],
                payload=json.loads(row["payload_json"]),
                event_id=int(row["id"] or 0),
            )
            for row in rows
        ]

    def dashboard_summary(self) -> Dict[str, object]:
        """返回首页仪表盘概览统计。"""
        # 仪表盘聚合统计：任务总量、状态分布、事件总量。
        with self._connect() as connection:
            total_tasks = connection.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0]
            completed_tasks = connection.execute(
                "SELECT COUNT(*) FROM task_runs WHERE status = 'completed'"
            ).fetchone()[0]
            blocked_tasks = connection.execute(
                "SELECT COUNT(*) FROM task_runs WHERE status = 'blocked'"
            ).fetchone()[0]
            failed_tasks = connection.execute(
                "SELECT COUNT(*) FROM task_runs WHERE status = 'failed'"
            ).fetchone()[0]
            canceled_tasks = connection.execute(
                "SELECT COUNT(*) FROM task_runs WHERE status = 'canceled'"
            ).fetchone()[0]
            total_events = connection.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "blocked_tasks": blocked_tasks,
            "failed_tasks": failed_tasks,
            "canceled_tasks": canceled_tasks,
            "total_events": total_events,
        }

    def housekeeping(
        self,
        task_retention_days: Optional[int] = None,
        event_retention_days: Optional[int] = None,
        max_runs: Optional[int] = None,
        archive_pruned: Optional[bool] = None,
    ) -> Dict[str, object]:
        """执行任务数据留存治理：过期清理、数量上限清理、快照归档。"""
        retention_days = (
            int(task_retention_days)
            if task_retention_days is not None
            else int(self.settings.task_retention_days)
        )
        retention_events_days = (
            int(event_retention_days)
            if event_retention_days is not None
            else int(self.settings.task_event_retention_days)
        )
        max_task_runs = int(max_runs) if max_runs is not None else int(self.settings.task_max_runs)
        should_archive = bool(self.settings.task_archive_pruned if archive_pruned is None else archive_pruned)

        prune_targets: Dict[str, Dict[str, str]] = {}
        deleted_events = 0

        with self._connect() as connection:
            if retention_days > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
                rows = connection.execute(
                    """
                    SELECT task_id, snapshot_path
                    FROM task_runs
                    WHERE updated_at < ?
                    """,
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    prune_targets[str(row["task_id"])] = {
                        "snapshot_path": str(row["snapshot_path"]),
                        "reason": "expired",
                    }

            if max_task_runs > 0:
                rows = connection.execute(
                    """
                    SELECT task_id, snapshot_path
                    FROM task_runs
                    ORDER BY updated_at DESC, task_id DESC
                    LIMIT -1 OFFSET ?
                    """,
                    (max_task_runs,),
                ).fetchall()
                for row in rows:
                    task_id = str(row["task_id"])
                    if task_id in prune_targets:
                        continue
                    prune_targets[task_id] = {
                        "snapshot_path": str(row["snapshot_path"]),
                        "reason": "overflow",
                    }

            if prune_targets:
                task_ids = list(prune_targets.keys())
                connection.executemany(
                    "DELETE FROM task_events WHERE task_id = ?",
                    [(task_id,) for task_id in task_ids],
                )
                connection.executemany(
                    "DELETE FROM task_runs WHERE task_id = ?",
                    [(task_id,) for task_id in task_ids],
                )

            if retention_events_days > 0:
                event_cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=retention_events_days)
                ).isoformat(timespec="seconds")
                cursor = connection.execute(
                    """
                    DELETE FROM task_events
                    WHERE created_at < ?
                    """,
                    (event_cutoff,),
                )
                deleted_events = int(cursor.rowcount if cursor.rowcount is not None else 0)

            active_snapshot_rows = connection.execute(
                """
                SELECT snapshot_path
                FROM task_runs
                """
            ).fetchall()

        archived_count = 0
        deleted_snapshots = 0
        for task_id, item in prune_targets.items():
            snapshot_path = Path(item["snapshot_path"])
            reason = item["reason"]
            if not snapshot_path.exists():
                continue
            if should_archive:
                if self._archive_snapshot(snapshot_path, task_id=task_id, reason=reason):
                    archived_count += 1
                continue
            snapshot_path.unlink(missing_ok=True)
            deleted_snapshots += 1

        active_snapshots = {str(Path(row["snapshot_path"])) for row in active_snapshot_rows}
        for snapshot_path in self.snapshot_dir.glob("*.json"):
            if str(snapshot_path) in active_snapshots:
                continue
            if should_archive:
                task_id = snapshot_path.stem
                if self._archive_snapshot(snapshot_path, task_id=task_id, reason="orphan"):
                    archived_count += 1
                continue
            snapshot_path.unlink(missing_ok=True)
            deleted_snapshots += 1

        result = {
            "pruned_task_runs": len(prune_targets),
            "deleted_old_events": deleted_events,
            "archived_snapshots": archived_count,
            "deleted_snapshots": deleted_snapshots,
            "task_retention_days": retention_days,
            "event_retention_days": retention_events_days,
            "max_runs": max_task_runs,
            "archive_pruned": should_archive,
        }
        self.last_housekeeping = result
        return result

    def _archive_snapshot(self, snapshot_path: Path, task_id: str, reason: str) -> bool:
        """把即将删除的快照迁移到归档目录，保留追溯能力。"""
        if not snapshot_path.exists():
            return False
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_reason = (reason or "pruned").replace(" ", "_")
        target = self.archive_snapshot_dir / f"{task_id}-{safe_reason}-{timestamp}.json"
        if target.exists():
            target = self.archive_snapshot_dir / f"{task_id}-{safe_reason}-{timestamp}-{uuid.uuid4().hex[:8]}.json"
        try:
            shutil.move(str(snapshot_path), str(target))
            return True
        except OSError:
            return False
