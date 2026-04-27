from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import Settings
from .models import SkillPlugin
from .plugin_skill_loader import load_plugin_skill_definitions


class SkillPluginRegistry:
    """技能插件注册中心，负责持久化插件元数据与技能索引。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = Path(settings.skill_plugin_registry_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_default_registry()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _read(self) -> Dict[str, object]:
        """读取注册表 JSON。"""
        if not self.path.exists():
            return {"plugins": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, payload: Dict[str, object]) -> None:
        """写入注册表 JSON。"""
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _scan_skills(self, plugin: SkillPlugin) -> List[str]:
        """扫描插件目录，返回当前可用技能名。"""
        return sorted(load_plugin_skill_definitions(plugin).keys())

    def _ensure_default_registry(self) -> None:
        """首次启动时写入默认插件条目。"""
        payload = self._read()
        plugins = payload.get("plugins", [])
        defaults = [
            {
                "name": "generated-skills",
                "kind": "local-directory",
                "source_dir": "skills/generated",
                "manifest_path": "",
                "enabled": True,
                "notes": ["从 docx 直接拆分出的原始 Skill 文件。"],
            },
            {
                "name": "standardized-skills",
                "kind": "local-directory",
                "source_dir": "skills/standardized",
                "manifest_path": "",
                "enabled": True,
                "notes": ["带输入、输出、约束和交接对象的标准化 Skill。"],
            },
        ]

        known_names = {item.get("name") for item in plugins}
        changed = False
        for default in defaults:
            if default["name"] in known_names:
                continue
            plugin = SkillPlugin(
                plugin_id=uuid.uuid4().hex,
                name=default["name"],
                kind=default["kind"],
                source_dir=default["source_dir"],
                manifest_path=default["manifest_path"],
                enabled=default["enabled"],
                registered_at=self._now(),
                notes=default["notes"],
                skills=[],
            )
            plugin.skills = self._scan_skills(plugin)
            plugins.append(asdict(plugin))
            changed = True
        if changed:
            payload["plugins"] = plugins
            self._write(payload)

    def list_plugins(self) -> List[SkillPlugin]:
        """列出全部插件，并实时刷新技能列表。"""
        payload = self._read()
        items = []
        for item in payload.get("plugins", []):
            source_dir = str(item.get("source_dir", ""))
            plugin = SkillPlugin(
                plugin_id=str(item.get("plugin_id", "")),
                name=str(item.get("name", "")),
                kind=str(item.get("kind", "")),
                source_dir=source_dir,
                manifest_path=str(item.get("manifest_path", "")),
                enabled=bool(item.get("enabled", True)),
                registered_at=str(item.get("registered_at", "")),
                notes=[str(note) for note in item.get("notes", [])],
                skills=[str(skill) for skill in item.get("skills", [])],
                owner_agent=str(item.get("owner_agent", "")),
                repo=str(item.get("repo", "")),
                ref=str(item.get("ref", "")),
                source_url=str(item.get("source_url", "")),
                import_paths=[str(path) for path in item.get("import_paths", [])],
            )
            plugin.skills = self._scan_skills(plugin) or plugin.skills
            items.append(plugin)
        return items

    def list_active_plugins(self) -> List[SkillPlugin]:
        """返回运行时真正参与技能合并的插件列表（含策略过滤）。"""
        plugins = self.list_plugins()
        mode = (self.settings.skill_runtime_mode or "curated").strip().lower()
        if mode not in {"all", "curated"}:
            mode = "curated"

        allowlist = {name.strip() for name in self.settings.skill_plugin_allowlist if name.strip()}
        blocklist = {name.strip() for name in self.settings.skill_plugin_blocklist if name.strip()}

        active: List[SkillPlugin] = []
        for plugin in plugins:
            if not plugin.enabled:
                continue
            if plugin.name in blocklist:
                continue
            if mode == "curated" and allowlist and plugin.name not in allowlist:
                continue
            active.append(plugin)
        return active

    def register(
        self,
        name: str,
        source_dir: str,
        kind: str = "local-directory",
        manifest_path: str = "",
        notes: Optional[List[str]] = None,
        owner_agent: str = "",
        repo: str = "",
        ref: str = "",
        source_url: str = "",
        import_paths: Optional[List[str]] = None,
    ) -> SkillPlugin:
        """注册新插件。"""
        payload = self._read()
        plugins = payload.get("plugins", [])
        for item in plugins:
            if item.get("name") == name:
                raise ValueError(f"Skill plugin already exists: {name}")

        plugin = SkillPlugin(
            plugin_id=uuid.uuid4().hex,
            name=name,
            kind=kind,
            source_dir=str(Path(source_dir)),
            manifest_path=manifest_path,
            enabled=True,
            registered_at=self._now(),
            notes=notes or [],
            skills=[],
            owner_agent=owner_agent,
            repo=repo,
            ref=ref,
            source_url=source_url,
            import_paths=import_paths or [],
        )
        plugin.skills = self._scan_skills(plugin)
        plugins.append(asdict(plugin))
        payload["plugins"] = plugins
        self._write(payload)
        return plugin

    def meta(self) -> Dict[str, object]:
        """返回注册中心元信息。"""
        plugins = self.list_plugins()
        active_plugins = self.list_active_plugins()
        return {
            "registry_path": str(self.path),
            "runtime_policy": {
                "mode": (self.settings.skill_runtime_mode or "curated").strip().lower(),
                "allowlist": list(self.settings.skill_plugin_allowlist),
                "blocklist": list(self.settings.skill_plugin_blocklist),
                "active_plugin_names": [plugin.name for plugin in active_plugins],
            },
            "items": [asdict(plugin) for plugin in plugins],
        }
