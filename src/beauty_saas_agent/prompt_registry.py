from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import Settings
from .docx_loader import load_docx_text
from .models import PromptRegistryEntry
from .prompt_parser import parse_prompt_definition


class PromptRegistry:
    """Prompt 注册中心，支持多版本注册与激活切换。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = Path(settings.prompt_registry_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_default_registry()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _read(self) -> Dict[str, object]:
        """读取注册表 JSON。"""
        if not self.path.exists():
            return {"entries": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: Dict[str, object]) -> None:
        """写入注册表 JSON。"""
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _derive_title(self, source_path: str) -> str:
        """根据源文件推断标题（docx 优先解析真实标题）。"""
        path = Path(source_path)
        try:
            if path.suffix.lower() == ".docx":
                text = load_docx_text(path)
                return parse_prompt_definition(text).title
            if path.exists():
                return path.stem
        except Exception:
            return path.stem
        return path.stem

    def _ensure_default_registry(self) -> None:
        """确保默认 prompt 已自动注册。"""
        payload = self._read()
        entries = payload.get("entries", [])
        default_path = str(Path(self.settings.prompt_docx_path))
        if any(entry.get("source_path") == default_path for entry in entries):
            return

        entry = PromptRegistryEntry(
            prompt_id=uuid.uuid4().hex,
            label="default-docx",
            source_path=default_path,
            title=self._derive_title(default_path),
            registered_at=self._now(),
            is_active=True,
            notes=["自动注册的默认 Prompt 文档。"],
        )
        payload["entries"] = [asdict(entry), *entries]
        self._write(payload)

    def list_entries(self) -> List[PromptRegistryEntry]:
        """列出所有 prompt 条目。"""
        payload = self._read()
        return [
            PromptRegistryEntry(
                prompt_id=str(item.get("prompt_id", "")),
                label=str(item.get("label", "")),
                source_path=str(item.get("source_path", "")),
                title=str(item.get("title", "")),
                registered_at=str(item.get("registered_at", "")),
                is_active=bool(item.get("is_active", False)),
                notes=[str(note) for note in item.get("notes", [])],
            )
            for item in payload.get("entries", [])
        ]

    def get_active_entry(self) -> PromptRegistryEntry:
        """获取当前激活 prompt。"""
        entries = self.list_entries()
        for entry in entries:
            if entry.is_active:
                return entry
        if entries:
            return entries[0]
        self._ensure_default_registry()
        return self.list_entries()[0]

    def register(self, source_path: str, label: Optional[str] = None, notes: Optional[List[str]] = None) -> PromptRegistryEntry:
        """注册新的 prompt 源文件；若已存在则直接返回旧条目。"""
        path = str(Path(source_path))
        payload = self._read()
        entries = payload.get("entries", [])
        for item in entries:
            if item.get("source_path") == path:
                return PromptRegistryEntry(
                    prompt_id=str(item.get("prompt_id", "")),
                    label=str(item.get("label", "")),
                    source_path=str(item.get("source_path", "")),
                    title=str(item.get("title", "")),
                    registered_at=str(item.get("registered_at", "")),
                    is_active=bool(item.get("is_active", False)),
                    notes=[str(note) for note in item.get("notes", [])],
                )

        entry = PromptRegistryEntry(
            prompt_id=uuid.uuid4().hex,
            label=label or Path(path).stem,
            source_path=path,
            title=self._derive_title(path),
            registered_at=self._now(),
            is_active=False,
            notes=notes or [],
        )
        entries.append(asdict(entry))
        payload["entries"] = entries
        self._write(payload)
        return entry

    def activate(self, prompt_id: str) -> PromptRegistryEntry:
        """激活指定 prompt，其他条目自动置为非激活。"""
        payload = self._read()
        found = None
        for item in payload.get("entries", []):
            item["is_active"] = item.get("prompt_id") == prompt_id
            if item["is_active"]:
                found = item
        if found is None:
            raise ValueError(f"Prompt not found: {prompt_id}")
        self._write(payload)
        return PromptRegistryEntry(
            prompt_id=str(found.get("prompt_id", "")),
            label=str(found.get("label", "")),
            source_path=str(found.get("source_path", "")),
            title=str(found.get("title", "")),
            registered_at=str(found.get("registered_at", "")),
            is_active=True,
            notes=[str(note) for note in found.get("notes", [])],
        )

    def meta(self) -> Dict[str, object]:
        """返回注册中心元信息。"""
        entries = self.list_entries()
        active = self.get_active_entry()
        return {
            "registry_path": str(self.path),
            "active_prompt_id": active.prompt_id,
            "active_prompt_path": active.source_path,
            "items": [asdict(entry) for entry in entries],
        }
