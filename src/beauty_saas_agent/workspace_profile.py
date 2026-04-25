from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .config import Settings


@dataclass
class RepositoryProfile:
    """单仓库配置。"""
    name: str
    kind: str
    remote_url: str
    branch: str
    local_path: str
    build_system: str = ""
    docs_hint: List[str] = field(default_factory=list)
    build_commands: List[str] = field(default_factory=list)
    test_commands: List[str] = field(default_factory=list)
    start_commands: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class ToolchainProfile:
    """本地工具链配置。"""
    maven_home: str = ""
    maven_bin: str = ""
    maven_local_repo: str = ""
    maven_settings_xml: str = ""
    java_home: str = ""
    java_bin: str = ""
    node_home: str = ""
    node_bin: str = ""
    pnpm_bin: str = ""
    package_manager: str = ""


@dataclass
class GitPolicy:
    """Git 操作约束配置。"""
    allow_branch_delete: bool = False
    allow_force_push: bool = False
    allow_reset_hard: bool = False
    protected_branches: List[str] = field(default_factory=list)
    forbidden_operations: List[str] = field(default_factory=list)
    allowed_sync_operations: List[str] = field(default_factory=list)


@dataclass
class ServiceProfile:
    """外部依赖服务配置。"""
    name: str
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    database: str = ""
    notes: List[str] = field(default_factory=list)


@dataclass
class WorkspaceProfile:
    """工作区总配置。"""
    repos: List[RepositoryProfile] = field(default_factory=list)
    toolchain: ToolchainProfile = field(default_factory=ToolchainProfile)
    git_policy: GitPolicy = field(default_factory=GitPolicy)
    services: List[ServiceProfile] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class WorkspaceSecrets:
    """敏感信息配置（与 profile 分离）。"""
    git_username: str = ""
    git_password: str = ""


def _read_json(path: Path) -> Dict[str, object]:
    """读取 JSON 文件，不存在返回空对象。"""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _repo_from_dict(data: Dict[str, object]) -> RepositoryProfile:
    """把字典转换成 RepositoryProfile。"""
    return RepositoryProfile(
        name=str(data.get("name", "")),
        kind=str(data.get("kind", "")),
        remote_url=str(data.get("remote_url", "")),
        branch=str(data.get("branch", "")),
        local_path=str(data.get("local_path", "")),
        build_system=str(data.get("build_system", "")),
        docs_hint=[str(item) for item in data.get("docs_hint", [])],
        build_commands=[str(item) for item in data.get("build_commands", [])],
        test_commands=[str(item) for item in data.get("test_commands", [])],
        start_commands=[str(item) for item in data.get("start_commands", [])],
        notes=[str(item) for item in data.get("notes", [])],
    )


def load_workspace_profile(settings: Settings) -> WorkspaceProfile:
    """加载工作区 profile。"""
    raw = _read_json(Path(settings.workspace_profile_path))
    repos = [_repo_from_dict(item) for item in raw.get("repos", [])]

    toolchain_raw = raw.get("toolchain", {})
    toolchain = ToolchainProfile(
        maven_home=str(toolchain_raw.get("maven_home", "")),
        maven_bin=str(toolchain_raw.get("maven_bin", "")),
        maven_local_repo=str(toolchain_raw.get("maven_local_repo", "")),
        maven_settings_xml=str(toolchain_raw.get("maven_settings_xml", "")),
        java_home=str(toolchain_raw.get("java_home", "")),
        java_bin=str(toolchain_raw.get("java_bin", "")),
        node_home=str(toolchain_raw.get("node_home", "")),
        node_bin=str(toolchain_raw.get("node_bin", "")),
        pnpm_bin=str(toolchain_raw.get("pnpm_bin", "")),
        package_manager=str(toolchain_raw.get("package_manager", "")),
    )

    policy_raw = raw.get("git_policy", {})
    git_policy = GitPolicy(
        allow_branch_delete=bool(policy_raw.get("allow_branch_delete", False)),
        allow_force_push=bool(policy_raw.get("allow_force_push", False)),
        allow_reset_hard=bool(policy_raw.get("allow_reset_hard", False)),
        protected_branches=[str(item) for item in policy_raw.get("protected_branches", [])],
        forbidden_operations=[str(item) for item in policy_raw.get("forbidden_operations", [])],
        allowed_sync_operations=[str(item) for item in policy_raw.get("allowed_sync_operations", [])],
    )

    services = [
        ServiceProfile(
            name=str(item.get("name", "")),
            host=str(item.get("host", "")),
            port=int(item.get("port", 0)),
            username=str(item.get("username", "")),
            password=str(item.get("password", "")),
            database=str(item.get("database", "")),
            notes=[str(note) for note in item.get("notes", [])],
        )
        for item in raw.get("services", [])
    ]

    return WorkspaceProfile(
        repos=repos,
        toolchain=toolchain,
        git_policy=git_policy,
        services=services,
        notes=[str(item) for item in raw.get("notes", [])],
    )


def load_workspace_secrets(settings: Settings) -> WorkspaceSecrets:
    """加载工作区 secrets。"""
    raw = _read_json(Path(settings.workspace_secrets_path))
    git_auth = raw.get("git_auth", {})
    return WorkspaceSecrets(
        git_username=str(git_auth.get("username", "")),
        git_password=str(git_auth.get("password", "")),
    )
