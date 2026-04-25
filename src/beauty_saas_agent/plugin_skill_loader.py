from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .agent_registry import get_skill_owner
from .models import PromptDefinition, SkillDefinition, SkillPlugin


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
HEADING_RE = re.compile(r"^#\s+(.+?)\s*$")
CHINESE_META_RE = re.compile(r"^- (中文名称|所属分组|归属Agent):\s*(.+?)\s*$")
AGENT_HINT_RE = re.compile(r"^(owner_agent|agent|owner):\s*(.+?)\s*$", re.IGNORECASE)
MANIFEST_FILENAMES = (
    "plugin-manifest.json",
    "skill-manifest.standard.json",
    "skill-manifest.json",
)
README_FILENAMES = {"readme.md"}
AGENT_KEYWORDS = {
    "bug_inspector": [
        "bug",
        "debug",
        "inspection",
        "triage",
        "root cause",
        "rca",
        "sentry",
        "trace",
        "stack",
        "exception",
        "crash",
        "playwright-interactive",
        "控制台",
        "报错",
        "故障",
        "定位",
        "排查",
    ],
    "frontend": [
        "frontend",
        "ui",
        "vue",
        "react",
        "css",
        "browser",
        "playwright",
        "页面",
        "前端",
        "界面",
        "样式",
    ],
    "backend": [
        "backend",
        "api",
        "server",
        "service",
        "java",
        "spring",
        "controller",
        "后端",
        "接口",
        "服务",
    ],
    "ops": [
        "ops",
        "devops",
        "deploy",
        "monitor",
        "infra",
        "sql",
        "database",
        "db",
        "docker",
        "k8s",
        "运维",
        "监控",
        "数据库",
        "部署",
        "测试",
    ],
}


def merge_plugin_skills(definition: PromptDefinition, plugins: Iterable[SkillPlugin]) -> PromptDefinition:
    """把插件技能合并进当前 Prompt 技能集合。"""
    merged_skills = dict(definition.skills)
    for plugin in plugins:
        if not plugin.enabled:
            continue
        for skill_name, skill in load_plugin_skill_definitions(plugin).items():
            merged_skills[skill_name] = skill
    return PromptDefinition(
        title=definition.title,
        raw_text=definition.raw_text,
        agent_goal=definition.agent_goal,
        version_policy=definition.version_policy,
        execution_flow=definition.execution_flow,
        constraints=definition.constraints,
        skills=merged_skills,
    )


def load_plugin_skill_definitions(plugin: SkillPlugin) -> Dict[str, SkillDefinition]:
    """加载单个插件的技能定义（manifest + markdown）。"""
    source_dir = Path(plugin.source_dir)
    if not source_dir.exists():
        return {}

    skills: Dict[str, SkillDefinition] = {}
    manifest_path = _resolve_manifest_path(plugin.manifest_path, source_dir)
    if manifest_path is not None:
        skills.update(_load_manifest_skills(manifest_path, plugin))

    for path in _discover_skill_files(source_dir):
        skill = parse_skill_markdown(
            path,
            plugin_name=plugin.name,
            default_owner=plugin.owner_agent,
            default_group=_default_group(plugin.owner_agent, plugin.name),
        )
        if skill is None:
            continue
        skills.setdefault(skill.name, skill)
    return skills


def parse_skill_markdown(
    path: Path,
    plugin_name: str = "",
    default_owner: str = "",
    default_group: str = "外部插件Skill",
    metadata: Optional[Dict[str, object]] = None,
) -> Optional[SkillDefinition]:
    """解析单个技能 Markdown，提取名称、分组、归属与正文。"""
    raw_text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(raw_text)
    chinese_meta = _extract_chinese_meta(body)
    metadata = metadata or {}

    heading = _extract_heading(body)
    name = str(
        metadata.get("name")
        or frontmatter.get("name")
        or heading
        or (path.parent.name if path.name == "SKILL.md" else path.stem)
    ).strip()
    if not name:
        return None

    title = str(
        metadata.get("title")
        or chinese_meta.get("中文名称")
        or frontmatter.get("title")
        or frontmatter.get("name")
        or heading
        or name
    ).strip()
    owner_agent = _normalize_owner(
        str(
            metadata.get("owner_agent")
            or chinese_meta.get("归属Agent")
            or frontmatter.get("owner_agent")
            or frontmatter.get("agent")
            or default_owner
        ).strip()
    ) or infer_skill_owner(
        name=name,
        title=title,
        group=str(metadata.get("group") or chinese_meta.get("所属分组") or default_group),
        content=body,
        path=path,
    )
    group = str(
        metadata.get("group")
        or chinese_meta.get("所属分组")
        or _default_group(owner_agent, plugin_name)
        or default_group
    ).strip()

    content_lines = _extract_content_lines(body)
    if not content_lines and frontmatter.get("description"):
        content_lines = [str(frontmatter["description"])]

    return SkillDefinition(
        name=name,
        title=title,
        group=group,
        lines=content_lines,
        owner_agent=owner_agent,
        source=f"plugin:{plugin_name}" if plugin_name else "plugin",
    )


def infer_skill_owner(
    name: str,
    title: str,
    group: str,
    content: str,
    path: Path,
) -> str:
    """根据技能语义猜测归属 agent。"""
    builtin_owner = get_skill_owner(name)
    if builtin_owner:
        return builtin_owner

    haystack = " ".join([name, title, group, content, str(path)]).lower()
    for owner, keywords in AGENT_KEYWORDS.items():
        if any(keyword.lower() in haystack for keyword in keywords):
            return owner
    return ""


def _split_frontmatter(text: str) -> tuple[Dict[str, str], str]:
    """拆分 markdown frontmatter 与正文。"""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    meta: Dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[match.end():]


def _extract_heading(body: str) -> str:
    """提取一级标题作为候选技能名。"""
    for raw_line in body.splitlines():
        line = raw_line.strip()
        match = HEADING_RE.match(line)
        if match:
            return match.group(1).strip()
    return ""


def _extract_chinese_meta(body: str) -> Dict[str, str]:
    """提取中文元信息行（中文名称/所属分组/归属Agent）。"""
    meta: Dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = CHINESE_META_RE.match(line)
        if match:
            meta[match.group(1)] = match.group(2).strip()
            continue
        agent_hint = AGENT_HINT_RE.match(line)
        if agent_hint:
            meta["归属Agent"] = agent_hint.group(2).strip()
            continue
        if line.startswith("## "):
            break
    return meta


def _extract_content_lines(body: str) -> List[str]:
    """过滤标题和元信息，保留实际技能内容行。"""
    lines: List[str] = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if HEADING_RE.match(stripped):
            continue
        if CHINESE_META_RE.match(stripped) or AGENT_HINT_RE.match(stripped):
            continue
        lines.append(stripped)
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _resolve_manifest_path(manifest_path: str, source_dir: Path) -> Optional[Path]:
    """解析 manifest 路径；若未指定则尝试默认文件名。"""
    if manifest_path:
        path = Path(manifest_path)
        if not path.is_absolute():
            path = source_dir / path
        if path.exists():
            return path
    for filename in MANIFEST_FILENAMES:
        candidate = source_dir / filename
        if candidate.exists():
            return candidate
    return None


def _discover_skill_files(source_dir: Path) -> List[Path]:
    """发现插件目录下可解析的技能 markdown 文件。"""
    files: List[Path] = []
    seen = set()

    for path in source_dir.rglob("SKILL.md"):
        if path.is_file():
            files.append(path)
            seen.add(path.resolve())

    for path in source_dir.glob("*.md"):
        if not path.is_file():
            continue
        if path.name.lower() in README_FILENAMES or path.name == "SKILL.md":
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        files.append(path)
        seen.add(resolved)

    return sorted(files, key=lambda item: str(item))


def _load_manifest_payload(manifest_path: Path) -> Dict[str, object]:
    """读取 manifest JSON，格式错误时返回空对象避免阻断整链路。"""
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _load_manifest_skills(manifest_path: Path, plugin: SkillPlugin) -> Dict[str, SkillDefinition]:
    """从 manifest 中加载技能定义。"""
    payload = _load_manifest_payload(manifest_path)
    source_dir = Path(plugin.source_dir)
    skills_payload = payload.get("skills", {})
    loaded: Dict[str, SkillDefinition] = {}

    if isinstance(skills_payload, dict):
        for skill_name, raw_item in skills_payload.items():
            item = raw_item if isinstance(raw_item, dict) else {}
            skill = _skill_from_manifest_entry(
                skill_name=skill_name,
                item=item,
                source_dir=source_dir,
                plugin=plugin,
            )
            if skill is not None:
                loaded[skill.name] = skill
        return loaded

    if isinstance(skills_payload, list):
        for raw_item in skills_payload:
            if not isinstance(raw_item, dict):
                continue
            skill_name = str(raw_item.get("name", "")).strip()
            if not skill_name:
                continue
            skill = _skill_from_manifest_entry(
                skill_name=skill_name,
                item=raw_item,
                source_dir=source_dir,
                plugin=plugin,
            )
            if skill is not None:
                loaded[skill.name] = skill
    return loaded


def _skill_from_manifest_entry(
    skill_name: str,
    item: Dict[str, object],
    source_dir: Path,
    plugin: SkillPlugin,
) -> Optional[SkillDefinition]:
    """把 manifest 中单条技能配置转换成 SkillDefinition。"""
    relative_path = str(item.get("path", "")).strip()
    if relative_path:
        file_path = source_dir / relative_path
        if file_path.exists():
            return parse_skill_markdown(
                file_path,
                plugin_name=plugin.name,
                default_owner=str(item.get("owner_agent") or plugin.owner_agent),
                default_group=str(item.get("group") or _default_group(plugin.owner_agent, plugin.name)),
                metadata=item,
            )

    owner_agent = _normalize_owner(str(item.get("owner_agent") or plugin.owner_agent))
    owner_agent = owner_agent or infer_skill_owner(
        name=skill_name,
        title=str(item.get("title", skill_name)),
        group=str(item.get("group", "")),
        content=json.dumps(item, ensure_ascii=False),
        path=source_dir,
    )
    lines = _manifest_lines(item)
    return SkillDefinition(
        name=skill_name,
        title=str(item.get("title", skill_name)),
        group=str(item.get("group") or _default_group(owner_agent, plugin.name)),
        lines=lines,
        owner_agent=owner_agent,
        source=f"plugin:{plugin.name}",
    )


def _manifest_lines(item: Dict[str, object]) -> List[str]:
    """把结构化字段拼装成技能 markdown 内容。"""
    content = str(item.get("content", "")).strip()
    if content:
        return content.splitlines()

    sections: List[str] = []
    mapping = [
        ("描述", "description"),
        ("核心目标", "purpose"),
        ("触发时机", "when_to_use"),
        ("输入", "inputs"),
        ("输出", "outputs"),
        ("硬性约束", "constraints"),
        ("执行清单", "checklist"),
        ("原始 Prompt", "raw_prompt"),
    ]
    for label, key in mapping:
        value = item.get(key)
        if not value:
            continue
        sections.append(f"## {label}")
        if isinstance(value, list):
            sections.extend(f"- {entry}" for entry in value if str(entry).strip())
        else:
            sections.append(str(value).strip())
        sections.append("")
    while sections and not sections[-1].strip():
        sections.pop()
    return sections


def _normalize_owner(value: str) -> str:
    """规范化 owner 字段，只接受系统内置 agent 名。"""
    normalized = value.strip().lower()
    if normalized in {"backend", "frontend", "ops", "orchestrator", "bug_inspector"}:
        return normalized
    return ""


def _default_group(owner_agent: str, plugin_name: str) -> str:
    """按 owner 与插件名生成默认分组。"""
    owner = _normalize_owner(owner_agent)
    if owner == "bug_inspector":
        return "外部插件Skill/故障定位"
    if owner == "backend":
        return "外部插件Skill/后端"
    if owner == "frontend":
        return "外部插件Skill/前端"
    if owner == "ops":
        return "外部插件Skill/运维"
    if owner == "orchestrator":
        return "外部插件Skill/总控"
    if plugin_name:
        return f"外部插件Skill/{plugin_name}"
    return "外部插件Skill"
