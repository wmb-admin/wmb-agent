from __future__ import annotations

import hashlib
import json
import re
import subprocess
from typing import Dict, List, Optional, Sequence, Set

from .config import Settings
from .models import AgentExecutionStep, ChatRequest

WORKFLOW_PAGE_KEYWORDS = ["新增页面", "新页面", "页面改造", "页面优化", "页面重构", "前端页面", "管理页", "后台页面"]
WORKFLOW_PAGE_KEYWORDS_LOWER = [item.lower() for item in WORKFLOW_PAGE_KEYWORDS]
GENERAL_KEYWORDS = [
    "启动",
    "联调",
    "发布",
    "测试",
    "异常",
    "接口",
    "页面",
    "数据库",
    "权限",
    "菜单",
    "配置",
    "网关",
    "服务",
]
TABLE_NAME_PATTERNS = [
    re.compile(r"(?i)\b(?:from|join|into|update|table|alter\s+table|create\s+table)\s+([a-zA-Z_][a-zA-Z0-9_]{2,64})"),
    re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]{2,64})\s*表"),
]


def _dedupe_keep_order(values: Sequence[str]) -> List[str]:
    """按原顺序去重，过滤空值。"""
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _task_is_page_change(task_text: str) -> bool:
    """判断任务是否属于“页面改动类”需求。"""
    lowered = task_text.lower()
    if any(keyword in lowered for keyword in WORKFLOW_PAGE_KEYWORDS_LOWER):
        return True
    return "页面" in task_text and ("新增" in task_text or "增加" in task_text or "改造" in task_text or "重构" in task_text)


def extract_table_names(text: str, limit: int = 12) -> List[str]:
    """从任务与输出文本中提取可能涉及的表名。"""
    if not text:
        return []
    candidates: List[str] = []
    for pattern in TABLE_NAME_PATTERNS:
        candidates.extend(match.group(1) for match in pattern.finditer(text))
    filtered = [item for item in candidates if "_" in item or item.lower().startswith(("sys", "crm", "bpm", "mall", "member"))]
    if not filtered:
        filtered = [item for item in candidates if len(item) >= 5]
    return _dedupe_keep_order(filtered)[:limit]


def extract_keywords(text: str, limit: int = 24) -> List[str]:
    """提取关键词用于召回排序。"""
    if not text:
        return []
    words: List[str] = []
    lowered = text.lower()
    for keyword in GENERAL_KEYWORDS:
        if keyword in text or keyword.lower() in lowered:
            words.append(keyword)
    words.extend(token for token in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,32}", text.lower()) if len(token) >= 4)
    return _dedupe_keep_order(words)[:limit]


def build_page_change_checklist(repos: Sequence[str], tables: Sequence[str]) -> List[str]:
    """生成页面改动场景下的跨层检查清单。"""
    base = [
        "前端：补页面、路由、菜单入口和 API 调用映射。",
        "后端：补 Controller/Service/DTO，并确认接口签名与前端字段一致。",
        "权限：补菜单与权限编码，确保角色可见。",
        "数据：补配置项与初始化数据，明确回滚方案。",
        "联调：至少验证新增页面访问、保存、查询三条主链路。",
    ]
    if "backend" not in repos:
        base.append("当前任务未显式选择 backend 仓库，提交前仍需确认后端依赖是否已同步。")
    if "frontend" not in repos:
        base.append("当前任务未显式选择 frontend 仓库，提交前仍需确认页面入口与调用方。")
    if tables:
        base.append("涉及表：" + ", ".join(tables[:6]))
    return base


class ProjectMemoryService:
    """项目级记忆服务（非对话历史），用于沉淀可复用执行经验。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = bool(settings.memory_enabled)
        self.available = False
        self.last_error = ""
        if self.enabled:
            self.available = self.ensure_ready()

    def meta(self) -> Dict[str, object]:
        """返回记忆模块状态，供 API/CLI 诊断使用。"""
        return {
            "enabled": self.enabled,
            "available": self.available,
            "mysql_host": self.settings.memory_mysql_host,
            "mysql_port": self.settings.memory_mysql_port,
            "mysql_database": self.settings.memory_mysql_database,
            "recall_limit": self.settings.memory_recall_limit,
            "fetch_limit": self.settings.memory_fetch_limit,
            "last_error": self.last_error,
        }

    def ensure_ready(self) -> bool:
        """初始化独立 memory 库和表结构。"""
        if not self.enabled:
            return False
        try:
            self._run_sql(
                f"CREATE DATABASE IF NOT EXISTS `{self.settings.memory_mysql_database}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
                database=None,
            )
            self._run_sql(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    item_key VARCHAR(191) NOT NULL UNIQUE,
                    memory_type VARCHAR(32) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    content TEXT NOT NULL,
                    tags_json JSON NOT NULL,
                    entities_json JSON NOT NULL,
                    checklist_json JSON NOT NULL,
                    confidence DECIMAL(5,2) NOT NULL DEFAULT 0.50,
                    priority INT NOT NULL DEFAULT 0,
                    success_count INT NOT NULL DEFAULT 1,
                    source_task_id VARCHAR(64) NOT NULL,
                    workflow VARCHAR(64) DEFAULT '',
                    repos_json JSON NOT NULL,
                    active TINYINT(1) NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_memory_items_updated_at (updated_at),
                    INDEX idx_memory_items_type_active (memory_type, active)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                """,
                database=self.settings.memory_mysql_database,
            )
            self._run_sql(
                """
                CREATE TABLE IF NOT EXISTS memory_hits (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    task_id VARCHAR(64) NOT NULL,
                    memory_id BIGINT NOT NULL,
                    used_by_agent VARCHAR(64) NOT NULL DEFAULT 'runtime',
                    accepted TINYINT(1) NOT NULL DEFAULT 1,
                    outcome VARCHAR(32) NOT NULL DEFAULT 'unknown',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_memory_hits_task (task_id),
                    INDEX idx_memory_hits_memory (memory_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                """,
                database=self.settings.memory_mysql_database,
            )
            self.last_error = ""
            return True
        except Exception as exc:  # pragma: no cover - external dependency
            self.last_error = str(exc)
            return False

    def recall(
        self,
        task: str,
        workflow: Optional[str] = None,
        repos: Optional[Sequence[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """召回与当前任务最相关的记忆卡片。"""
        if not self.enabled:
            return []
        if not self.available and not self.ensure_ready():
            return []

        # Pull a bounded recent window first, then rank in-process.
        # This avoids full-table scans while preserving relevance sorting flexibility.
        fetch_limit = max(80, min(500, int(self.settings.memory_fetch_limit)))
        query = (
            "SELECT JSON_OBJECT("
            "'id', id,"
            "'memory_type', memory_type,"
            "'title', title,"
            "'content', content,"
            "'tags_json', tags_json,"
            "'entities_json', entities_json,"
            "'checklist_json', checklist_json,"
            "'confidence', confidence,"
            "'priority', priority,"
            "'success_count', success_count,"
            "'workflow', workflow,"
            "'repos_json', repos_json,"
            "'updated_at', DATE_FORMAT(updated_at, '%Y-%m-%dT%H:%i:%s')"
            ") FROM memory_items WHERE active = 1 ORDER BY updated_at DESC LIMIT "
            + str(fetch_limit)
            + ";"
        )
        try:
            rows = self._run_sql(query, database=self.settings.memory_mysql_database, expect_output=True)
        except Exception as exc:  # pragma: no cover - external dependency
            self.last_error = str(exc)
            self.available = False
            return []

        items: List[Dict[str, object]] = []
        for row in rows:
            try:
                payload = json.loads(row)
            except json.JSONDecodeError:
                continue
            items.append(
                {
                    "id": int(payload.get("id", 0) or 0),
                    "memory_type": str(payload.get("memory_type", "")),
                    "title": str(payload.get("title", "")),
                    "content": str(payload.get("content", "")),
                    "tags": self._as_list(payload.get("tags_json")),
                    "entities": self._as_dict(payload.get("entities_json")),
                    "checklist": self._as_list(payload.get("checklist_json")),
                    "confidence": float(payload.get("confidence", 0) or 0),
                    "priority": int(payload.get("priority", 0) or 0),
                    "success_count": int(payload.get("success_count", 0) or 0),
                    "workflow": str(payload.get("workflow", "")),
                    "repos": self._as_list(payload.get("repos_json")),
                    "updated_at": str(payload.get("updated_at", "")),
                }
            )

        repo_list = list(dict.fromkeys([item for item in (repos or []) if item]))
        ranked = self._rank_items(task=task, workflow=workflow or "", repos=repo_list, items=items)
        top_k = max(1, int(limit or self.settings.memory_recall_limit))
        return ranked[:top_k]

    def persist_from_task(
        self,
        task_id: str,
        request: ChatRequest,
        steps: Sequence[AgentExecutionStep],
        final_content: str,
        final_status: str,
    ) -> int:
        """任务成功后抽取可复用经验并入库。"""
        if not self.enabled:
            return 0
        if final_status != "completed":
            return 0
        if not self.available and not self.ensure_ready():
            return 0

        cards = self._build_memory_cards(task_id=task_id, request=request, steps=steps, final_content=final_content)
        if not cards:
            return 0

        stored = 0
        for card in cards:
            try:
                self._upsert_item(card)
                stored += 1
            except Exception as exc:  # pragma: no cover - external dependency
                self.last_error = str(exc)
                self.available = False
                break
        return stored

    def _build_memory_cards(
        self,
        task_id: str,
        request: ChatRequest,
        steps: Sequence[AgentExecutionStep],
        final_content: str,
    ) -> List[Dict[str, object]]:
        """根据任务上下文构建候选记忆卡片。"""
        task_text = request.task.strip()
        if not task_text:
            return []

        workflow = request.workflow or ""
        repos = list(dict.fromkeys(request.repos))
        combined_output = "\n".join([final_content] + [step.output for step in steps if step.output]).strip()
        table_names = extract_table_names(combined_output + "\n" + task_text)
        tags = extract_keywords(task_text + " " + workflow)

        cards: List[Dict[str, object]] = []
        # Promote high-value cross-layer workflow memory:
        # page changes usually require backend/data/permission linkage.
        if _task_is_page_change(task_text):
            checklist = build_page_change_checklist(repos=repos, tables=table_names)
            content = (
                "该类需求通常不仅包含页面代码，还需要联动后端接口、菜单权限与数据库配置。\n"
                "优先按清单逐项检查，避免只改前端导致联调回退。"
            )
            cards.append(
                self._build_card(
                    memory_type="workflow",
                    title="页面改动联动清单（前后端+配置）",
                    content=content,
                    tags=_dedupe_keep_order(tags + ["页面", "联调", "配置", "数据库"]),
                    entities={"tables": table_names, "repos": repos},
                    checklist=checklist,
                    confidence=0.92,
                    priority=5,
                    source_task_id=task_id,
                    workflow=workflow,
                    repos=repos,
                )
            )

        if combined_output:
            step_titles = [step.title for step in steps if step.title][:6]
            summary = [
                f"任务：{task_text[:120]}",
                f"workflow：{workflow or 'manual'}",
                "执行步骤：" + (" -> ".join(step_titles) if step_titles else "无"),
            ]
            if table_names:
                summary.append("关联表：" + ", ".join(table_names[:8]))
            content = "\n".join(summary)
            cards.append(
                self._build_card(
                    memory_type="task_pattern",
                    title=f"任务经验：{task_text[:48]}",
                    content=content,
                    tags=tags,
                    entities={"tables": table_names, "repos": repos},
                    checklist=[],
                    confidence=0.68,
                    priority=2,
                    source_task_id=task_id,
                    workflow=workflow,
                    repos=repos,
                )
            )

        return cards

    def _build_card(
        self,
        memory_type: str,
        title: str,
        content: str,
        tags: Sequence[str],
        entities: Dict[str, object],
        checklist: Sequence[str],
        confidence: float,
        priority: int,
        source_task_id: str,
        workflow: str,
        repos: Sequence[str],
    ) -> Dict[str, object]:
        """构建单条 memory item，包含稳定 item_key。"""
        identity = {
            "memory_type": memory_type,
            "title": title[:120],
            "workflow": workflow,
            "repos": list(repos),
            "tables": entities.get("tables", []),
        }
        item_key = hashlib.sha1(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:40]
        return {
            "item_key": item_key,
            "memory_type": memory_type,
            "title": title[:240],
            "content": content[:8000],
            "tags": list(tags),
            "entities": entities,
            "checklist": list(checklist),
            "confidence": max(0.1, min(0.99, float(confidence))),
            "priority": int(priority),
            "source_task_id": source_task_id,
            "workflow": workflow,
            "repos": list(repos),
        }

    def _rank_items(
        self,
        task: str,
        workflow: str,
        repos: Sequence[str],
        items: Sequence[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        """按关键词、workflow、repo 命中率综合排序。"""
        query_keywords = set(extract_keywords(task + " " + workflow, limit=40))
        repo_set = set(repos)
        ranked: List[Dict[str, object]] = []
        for item in items:
            score = 0.0
            title = str(item.get("title", ""))
            content = str(item.get("content", ""))
            tags = set(self._as_list(item.get("tags")))
            item_repos = set(self._as_list(item.get("repos")))

            for keyword in query_keywords:
                if keyword in title:
                    score += 3.0
                if keyword in content:
                    score += 1.4
                if keyword in tags:
                    score += 2.2
            if workflow and str(item.get("workflow", "")) == workflow:
                score += 3.0
            score += len(repo_set.intersection(item_repos)) * 1.8
            score += float(item.get("priority", 0) or 0) * 0.8
            score += float(item.get("confidence", 0.5) or 0.5) * 3.0
            score += min(float(item.get("success_count", 1) or 1), 10.0) * 0.2

            if score <= 0:
                continue

            ranked_item = dict(item)
            ranked_item["score"] = round(score, 3)
            ranked.append(ranked_item)

        ranked.sort(key=lambda row: (float(row.get("score", 0)), row.get("updated_at", "")), reverse=True)
        return ranked

    def _upsert_item(self, item: Dict[str, object]) -> None:
        # item_key is a semantic fingerprint; ON DUPLICATE allows cumulative learning
        # without duplicating near-identical memories.
        sql = (
            "INSERT INTO memory_items ("
            "item_key, memory_type, title, content, tags_json, entities_json, checklist_json, "
            "confidence, priority, success_count, source_task_id, workflow, repos_json, active"
            ") VALUES ("
            f"{self._quote(item['item_key'])},"
            f"{self._quote(item['memory_type'])},"
            f"{self._quote(item['title'])},"
            f"{self._quote(item['content'])},"
            f"{self._quote(json.dumps(item['tags'], ensure_ascii=False))},"
            f"{self._quote(json.dumps(item['entities'], ensure_ascii=False))},"
            f"{self._quote(json.dumps(item['checklist'], ensure_ascii=False))},"
            f"{float(item['confidence']):.2f},"
            f"{int(item['priority'])},"
            "1,"
            f"{self._quote(item['source_task_id'])},"
            f"{self._quote(item['workflow'])},"
            f"{self._quote(json.dumps(item['repos'], ensure_ascii=False))},"
            "1"
            ") ON DUPLICATE KEY UPDATE "
            "title=VALUES(title),"
            "content=VALUES(content),"
            "tags_json=VALUES(tags_json),"
            "entities_json=VALUES(entities_json),"
            "checklist_json=VALUES(checklist_json),"
            "confidence=VALUES(confidence),"
            "priority=VALUES(priority),"
            "workflow=VALUES(workflow),"
            "repos_json=VALUES(repos_json),"
            "source_task_id=VALUES(source_task_id),"
            "success_count=memory_items.success_count + 1,"
            "active=1,"
            "updated_at=CURRENT_TIMESTAMP;"
        )
        self._run_sql(sql, database=self.settings.memory_mysql_database)

    def _run_sql(self, sql: str, database: Optional[str] = None, expect_output: bool = False) -> List[str]:
        """调用 mysql CLI 执行 SQL，避免引入额外驱动依赖。"""
        cmd = [
            self.settings.memory_mysql_bin,
            f"-h{self.settings.memory_mysql_host}",
            f"-P{int(self.settings.memory_mysql_port)}",
            f"-u{self.settings.memory_mysql_user}",
            f"-p{self.settings.memory_mysql_password}",
            "--default-character-set=utf8mb4",
        ]
        if database:
            cmd.append(f"--database={database}")
        cmd.extend(["-Nse", sql])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        stderr = self._sanitize_mysql_error(result.stderr)
        if result.returncode != 0:
            raise RuntimeError(stderr or "mysql command failed")
        if not expect_output:
            return []
        output = (result.stdout or "").strip()
        if not output:
            return []
        return [line for line in output.splitlines() if line.strip()]

    def _sanitize_mysql_error(self, stderr: str) -> str:
        """清理噪声错误行，保留有效诊断信息。"""
        lines = []
        for line in (stderr or "").splitlines():
            if "Using a password on the command line interface can be insecure." in line:
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _quote(self, value: object) -> str:
        """最小化 SQL 字符串转义。"""
        raw = str(value if value is not None else "")
        escaped = raw.replace("\\", "\\\\").replace("'", "\\'")
        return "'" + escaped + "'"

    def _as_list(self, value: object) -> List[str]:
        """把 JSON 字段安全转换成字符串列表。"""
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, list):
                        return [str(item) for item in parsed if str(item).strip()]
                except json.JSONDecodeError:
                    return []
        return []

    def _as_dict(self, value: object) -> Dict[str, object]:
        """把 JSON 字段安全转换成字典。"""
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    return {}
        return {}
