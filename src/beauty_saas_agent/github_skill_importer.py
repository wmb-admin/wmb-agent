from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from .config import Settings
from .models import SkillPlugin
from .plugin_skill_loader import load_plugin_skill_definitions
from .skill_plugin_registry import SkillPluginRegistry


def parse_github_source(
    repo: str = "",
    ref: str = "main",
    paths: Optional[List[str]] = None,
    url: str = "",
) -> Tuple[str, str, List[str], str]:
    """解析 GitHub 仓库来源（repo/ref/path 或 URL）。"""
    cleaned_repo = repo.strip()
    cleaned_ref = ref.strip() or "main"
    cleaned_paths = [path.strip().strip("/") for path in (paths or []) if path.strip()]
    cleaned_url = url.strip()

    if cleaned_url:
        marker = "github.com/"
        if marker not in cleaned_url:
            raise ValueError(f"Unsupported GitHub URL: {cleaned_url}")
        suffix = cleaned_url.split(marker, 1)[1]
        parts = [part for part in suffix.split("/") if part]
        if len(parts) < 4:
            raise ValueError(f"Unsupported GitHub URL: {cleaned_url}")
        cleaned_repo = "/".join(parts[:2])
        route = parts[2]
        if route not in {"tree", "blob"}:
            raise ValueError(f"Unsupported GitHub URL route: {cleaned_url}")
        cleaned_ref = parts[3]
        remaining_path = "/".join(parts[4:])
        cleaned_paths = [remaining_path] if remaining_path else []

    if not cleaned_repo or "/" not in cleaned_repo:
        raise ValueError("GitHub repo must use owner/repo format.")
    if not cleaned_paths:
        raise ValueError("At least one GitHub path is required.")

    source_url = cleaned_url or f"https://github.com/{cleaned_repo}/tree/{cleaned_ref}/{cleaned_paths[0]}"
    return cleaned_repo, cleaned_ref, cleaned_paths, source_url


class GitHubSkillImporter:
    """GitHub 技能导入器：稀疏克隆 -> 拷贝路径 -> 生成 manifest -> 注册插件。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.registry = SkillPluginRegistry(settings)

    def import_plugin(
        self,
        name: str,
        repo: str = "",
        ref: str = "main",
        paths: Optional[List[str]] = None,
        url: str = "",
        owner_agent: str = "",
        notes: Optional[List[str]] = None,
    ) -> SkillPlugin:
        """导入并注册 GitHub 技能插件。"""
        resolved_repo, resolved_ref, resolved_paths, source_url = parse_github_source(
            repo=repo,
            ref=ref,
            paths=paths,
            url=url,
        )

        existing_names = {plugin.name for plugin in self.registry.list_plugins()}
        if name in existing_names:
            raise ValueError(f"Skill plugin already exists: {name}")

        import_root = self._resolve_import_root()
        import_root.mkdir(parents=True, exist_ok=True)
        plugin_root = import_root / name
        if plugin_root.exists():
            raise ValueError(f"Import target already exists: {plugin_root}")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                checkout_root = Path(temp_dir) / "repo"
                self._clone_sparse(
                    repo=resolved_repo,
                    ref=resolved_ref,
                    checkout_root=checkout_root,
                    paths=resolved_paths,
                )
                # 把目标路径抽取到独立插件目录，避免仓库无关文件进入运行时。
                plugin_root.mkdir(parents=False)
                self._copy_paths(
                    checkout_root=checkout_root,
                    plugin_root=plugin_root,
                    paths=resolved_paths,
                )
                manifest_path = self._write_manifest(
                    plugin_root=plugin_root,
                    plugin_name=name,
                    repo=resolved_repo,
                    ref=resolved_ref,
                    source_url=source_url,
                    owner_agent=owner_agent,
                    paths=resolved_paths,
                )

            plugin_notes = notes or []
            plugin_notes = [
                *plugin_notes,
                f"Imported from GitHub: {resolved_repo}@{resolved_ref}",
            ]
            return self.registry.register(
                name=name,
                source_dir=str(plugin_root),
                kind="github",
                manifest_path=str(manifest_path),
                notes=plugin_notes,
                owner_agent=owner_agent,
                repo=resolved_repo,
                ref=resolved_ref,
                source_url=source_url,
                import_paths=resolved_paths,
            )
        except Exception:
            if plugin_root.exists():
                shutil.rmtree(plugin_root)
            raise

    def _resolve_import_root(self) -> Path:
        """解析技能导入根目录。"""
        root = Path(self.settings.skill_import_root).expanduser()
        if root.is_absolute():
            return root
        return Path.cwd() / root

    def _clone_sparse(
        self,
        repo: str,
        ref: str,
        checkout_root: Path,
        paths: List[str],
    ) -> None:
        """使用 sparse checkout 仅拉取需要的目录，降低导入开销。"""
        repo_url = f"https://github.com/{repo}.git"
        self._run_git(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                "--branch",
                ref,
                repo_url,
                str(checkout_root),
            ]
        )
        self._run_git(
            [
                "git",
                "-C",
                str(checkout_root),
                "sparse-checkout",
                "set",
                "--no-cone",
                *paths,
            ]
        )

    def _copy_paths(self, checkout_root: Path, plugin_root: Path, paths: List[str]) -> None:
        """把拉取到的目标路径复制到插件目录。"""
        for raw_path in paths:
            source_path = checkout_root / raw_path
            if not source_path.exists():
                raise ValueError(f"GitHub path not found in checkout: {raw_path}")
            target_path = plugin_root / source_path.name
            if target_path.exists():
                raise ValueError(f"Conflicting imported path: {target_path.name}")
            if source_path.is_dir():
                shutil.copytree(source_path, target_path)
            else:
                shutil.copy2(source_path, target_path)

    def _write_manifest(
        self,
        plugin_root: Path,
        plugin_name: str,
        repo: str,
        ref: str,
        source_url: str,
        owner_agent: str,
        paths: List[str],
    ) -> Path:
        """写入导入后 manifest，固化来源信息与技能快照。"""
        plugin = SkillPlugin(
            plugin_id="",
            name=plugin_name,
            kind="github",
            source_dir=str(plugin_root),
            owner_agent=owner_agent,
            repo=repo,
            ref=ref,
            source_url=source_url,
            import_paths=paths,
        )
        skills = load_plugin_skill_definitions(plugin)
        manifest_path = plugin_root / "plugin-manifest.json"
        payload = {
            "plugin_name": plugin_name,
            "source": {
                "repo": repo,
                "ref": ref,
                "url": source_url,
                "paths": paths,
                "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
            "skills": [
                {
                    "name": item.name,
                    "title": item.title,
                    "group": item.group,
                    "owner_agent": item.owner_agent,
                    "content": item.content,
                }
                for item in skills.values()
            ],
        }
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest_path

    def _run_git(self, args: List[str]) -> None:
        """执行 git 命令并在失败时抛出清晰错误。"""
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git command failed")
