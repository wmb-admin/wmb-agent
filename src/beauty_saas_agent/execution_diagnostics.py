from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .models import ExecutionLocation


TS_ERROR_RE = re.compile(r"(?P<location>[^\s][^:\n]*\.(?:ts|tsx|js|jsx))[:(](?P<line>\d+)[,:](?P<col>\d+).+?error\s+(?P<code>TS\d+):\s*(?P<message>.+)")
PYTEST_FAILED_RE = re.compile(r"^FAILED\s+(?P<target>\S+)", re.MULTILINE)
PYTEST_SHORT_RE = re.compile(r"=+\s+short test summary info\s+=+\n(?P<body>.+?)(?:\n\n|\Z)", re.DOTALL)
PYTEST_ERROR_LINE_RE = re.compile(r"^(E\s+.+|.+Error:\s+.+)$", re.MULTILINE)
MAVEN_CANNOT_FIND_RE = re.compile(r"cannot find symbol", re.IGNORECASE)
MAVEN_LOCATION_RE = re.compile(r"\[ERROR\]\s+(?P<path>[^:\n]+):\[(?P<line>\d+),(?P<col>\d+)\]\s+(?P<message>.+)")
MAVEN_TEST_FAILURE_RE = re.compile(r"There are test failures", re.IGNORECASE)
MAVEN_FAILED_TEST_RE = re.compile(r"Failed tests?:\s*(?P<body>.+?)(?:\n\[|\Z)", re.DOTALL | re.IGNORECASE)
SPRING_BOOT_MAIN_CLASS_RE = re.compile(r"unable to find a suitable main class", re.IGNORECASE)
MAVEN_ON_PROJECT_RE = re.compile(r"on project (?P<project>[\w.\-]+)", re.IGNORECASE)
PACKAGE_ERROR_RE = re.compile(
    r"(ERR_PNPM_[A-Z_]+|npm ERR![^\n]*|could not resolve dependencies|failed to collect dependencies|could not transfer artifact)",
    re.IGNORECASE,
)
TIMEOUT_RE = re.compile(r"(timed out|timeout)", re.IGNORECASE)
COMMAND_TIMEOUT_RE = re.compile(r"(command timed out after|timed out after \d+)", re.IGNORECASE)
GENERIC_ERROR_RE = re.compile(r"^(?P<line>(?:\[ERROR\]|ERROR:|Error:|error:).+)$", re.MULTILINE)
PY_TRACEBACK_LOCATION_RE = re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+)')


@dataclass
class ExecutionDiagnostic:
    """命令失败诊断结果，供提示词与前端展示统一消费。"""
    failure_kind: str = "generic"
    title: str = "工作区命令执行失败"
    summary: str = "建议先复核失败命令的输出，再按仓库当前命令重新定位问题。"
    primary_error: str = ""
    failed_targets: List[str] = field(default_factory=list)
    evidence_lines: List[str] = field(default_factory=list)
    locations: List[ExecutionLocation] = field(default_factory=list)

    @property
    def evidence_text(self) -> str:
        return "\n".join(line for line in self.evidence_lines if line.strip()).strip()


def analyze_command_output(command: str, stdout: str, stderr: str, reason: str = "") -> ExecutionDiagnostic:
    """基于命令输出识别失败类型，并给出结构化诊断。"""
    text = "\n".join(part for part in [stderr, stdout, reason] if part).strip()
    lower_text = f"{command}\n{text}".lower()

    has_command_timeout = bool(TIMEOUT_RE.search(reason or "")) or bool(COMMAND_TIMEOUT_RE.search(text))
    if has_command_timeout:
        return ExecutionDiagnostic(
            failure_kind="timeout",
            title="命令执行超时",
            summary="命令在预期时间内没有完成，优先检查依赖下载、测试卡住或服务连接等待。",
            primary_error=_timeout_primary_error(text=text, reason=reason),
            evidence_lines=_top_interesting_lines(text),
            locations=_extract_traceback_locations(text),
        )

    ts_match = TS_ERROR_RE.search(text)
    if ts_match:
        location = f"{ts_match.group('location')}:{ts_match.group('line')}:{ts_match.group('col')}"
        message = f"{ts_match.group('code')} {ts_match.group('message').strip()}"
        return ExecutionDiagnostic(
            failure_kind="typescript",
            title="TypeScript 类型检查失败",
            summary="前端或 Node 侧类型检查被阻断，优先修复首个 TS 错误位置并确认接口/类型签名一致。",
            primary_error=f"{location} {message}",
            failed_targets=[location],
            evidence_lines=[ts_match.group(0).strip(), *_top_interesting_lines(text, limit=3)],
            locations=[
                ExecutionLocation(
                    path=ts_match.group("location").strip(),
                    line=int(ts_match.group("line")),
                    column=int(ts_match.group("col")),
                    label=message,
                )
            ],
        )

    pytest_targets = PYTEST_FAILED_RE.findall(text)
    pytest_error = _first_match(PYTEST_ERROR_LINE_RE, text)
    if pytest_targets or "short test summary info" in lower_text:
        return ExecutionDiagnostic(
            failure_kind="pytest",
            title="测试执行失败",
            summary="测试阶段出现失败，建议先修复首个失败用例，再结合覆盖率和差异评审定位根因。",
            primary_error=pytest_error or _first_non_empty_line(text),
            failed_targets=pytest_targets[:5],
            evidence_lines=_pytest_evidence_lines(text),
            locations=_pytest_locations(pytest_targets, text),
        )

    maven_location = MAVEN_LOCATION_RE.search(text)
    if MAVEN_CANNOT_FIND_RE.search(text):
        return ExecutionDiagnostic(
            failure_kind="maven-compile",
            title="Maven 编译失败",
            summary="后端编译阶段失败，优先检查 Java 类型、方法签名、依赖和导入是否一致。",
            primary_error=_first_maven_error(text),
            evidence_lines=_maven_evidence_lines(text),
            locations=_maven_locations(maven_location, text),
        )

    if MAVEN_TEST_FAILURE_RE.search(text):
        failed_targets = _extract_maven_failed_tests(text)
        return ExecutionDiagnostic(
            failure_kind="maven-test",
            title="Maven 测试失败",
            summary="后端测试已阻断本次交付，建议先查看 Surefire/Failsafe 报告并修复首个失败测试。",
            primary_error=_first_maven_error(text),
            failed_targets=failed_targets[:5],
            evidence_lines=_maven_evidence_lines(text),
            locations=_extract_traceback_locations(text),
        )

    if SPRING_BOOT_MAIN_CLASS_RE.search(text):
        project_match = MAVEN_ON_PROJECT_RE.search(text)
        project_name = project_match.group("project").strip() if project_match else ""
        return ExecutionDiagnostic(
            failure_kind="spring-boot-main-class",
            title="Spring Boot 启动入口识别失败",
            summary="启动命令运行在聚合工程或错误模块上，未命中可启动主类。建议改为针对目标模块 pom 的 `-f .../pom.xml ...:run` 方式。",
            primary_error=_first_maven_error(text),
            failed_targets=[project_name] if project_name else [],
            evidence_lines=_maven_evidence_lines(text),
            locations=_extract_traceback_locations(text),
        )

    package_error = _first_match(PACKAGE_ERROR_RE, text)
    if package_error:
        return ExecutionDiagnostic(
            failure_kind="dependencies",
            title="依赖解析或包管理失败",
            summary="依赖安装或解析阶段失败，优先检查网络、私服、锁文件和包版本冲突。",
            primary_error=package_error,
            evidence_lines=_top_interesting_lines(text),
            locations=_extract_traceback_locations(text),
        )

    generic_error = _first_match(GENERIC_ERROR_RE, text)
    return ExecutionDiagnostic(
        failure_kind="generic",
        title="工作区命令执行失败",
        summary="建议先复核失败命令的输出，再按仓库当前命令重新定位问题。",
        primary_error=generic_error or _first_non_empty_line(text),
        evidence_lines=_top_interesting_lines(text),
        locations=_extract_traceback_locations(text),
    )


def _pytest_evidence_lines(text: str) -> List[str]:
    """抽取 pytest 的短摘要与首条错误，便于 UI 直接展示。"""
    short_summary = PYTEST_SHORT_RE.search(text)
    lines: List[str] = []
    if short_summary:
        lines.extend(
            line.strip()
            for line in short_summary.group("body").splitlines()
            if line.strip()
        )
    error_line = _first_match(PYTEST_ERROR_LINE_RE, text)
    if error_line and error_line not in lines:
        lines.append(error_line)
    return lines[:6] or _top_interesting_lines(text, limit=4)


def _maven_evidence_lines(text: str) -> List[str]:
    """抽取 Maven 常见关键报错行。"""
    lines = [
        line.strip()
        for line in text.splitlines()
        if "[ERROR]" in line or "cannot find symbol" in line.lower() or "There are test failures" in line
    ]
    return lines[:6] or _top_interesting_lines(text, limit=4)


def _first_maven_error(text: str) -> str:
    """定位第一条最关键 Maven 报错。"""
    for line in text.splitlines():
        stripped = line.strip()
        if "cannot find symbol" in stripped.lower():
            return stripped
    for line in text.splitlines():
        stripped = line.strip()
        if "error ts" in stripped.lower():
            return stripped
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[ERROR]"):
            return stripped
    return _first_non_empty_line(text)


def _extract_maven_failed_tests(text: str) -> List[str]:
    """从 Maven 测试输出中提取失败用例名。"""
    match = MAVEN_FAILED_TEST_RE.search(text)
    if not match:
        return []
    targets = []
    for line in match.group("body").splitlines():
        stripped = line.strip(" -\t")
        if stripped:
            targets.append(stripped)
    return targets


def _top_interesting_lines(text: str, limit: int = 5) -> List[str]:
    """返回最有信息量的错误行，作为兜底证据。"""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(token in stripped.lower() for token in ["error", "failed", "exception", "cannot", "timeout"]):
            lines.append(stripped)
    return lines[:limit] or [line.strip() for line in text.splitlines() if line.strip()][:limit]


def _timeout_primary_error(text: str, reason: str = "") -> str:
    """超时场景下优先返回最能说明卡点的错误行。"""
    if reason.strip():
        return reason.strip()
    interesting = _top_interesting_lines(text, limit=8)
    for line in interesting:
        lowered = line.lower()
        if "timed out" in lowered or "timeout" in lowered:
            return line
    for line in interesting:
        lowered = line.lower()
        if any(token in lowered for token in ["[error]", "error", "failed", "exception", "cannot"]):
            return line
    return _first_non_empty_line(text)


def _pytest_locations(targets: List[str], text: str) -> List[ExecutionLocation]:
    """把 pytest 失败目标转换成文件定位信息。"""
    locations: List[ExecutionLocation] = []
    for target in targets[:5]:
        path = target.split("::", 1)[0]
        locations.append(ExecutionLocation(path=path, label=target))
    locations.extend(_extract_traceback_locations(text))
    return _dedupe_locations(locations)


def _maven_locations(match: Optional[re.Match], text: str) -> List[ExecutionLocation]:
    """把 Maven 编译报错转换成文件定位信息。"""
    locations: List[ExecutionLocation] = []
    if match:
        locations.append(
            ExecutionLocation(
                path=match.group("path").strip(),
                line=int(match.group("line")),
                column=int(match.group("col")),
                label=match.group("message").strip(),
            )
        )
    locations.extend(_extract_traceback_locations(text))
    return _dedupe_locations(locations)


def _extract_traceback_locations(text: str) -> List[ExecutionLocation]:
    """从 Python traceback 中提取文件行号。"""
    locations = [
        ExecutionLocation(
            path=match.group("path").strip(),
            line=int(match.group("line")),
        )
        for match in PY_TRACEBACK_LOCATION_RE.finditer(text)
    ]
    return _dedupe_locations(locations)


def _dedupe_locations(locations: List[ExecutionLocation]) -> List[ExecutionLocation]:
    """对定位结果去重，减少前端重复展示。"""
    deduped: List[ExecutionLocation] = []
    seen = set()
    for item in locations:
        key = (item.path, item.line, item.column, item.label)
        if key in seen or not item.path:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _first_match(pattern: re.Pattern, text: str) -> str:
    """返回正则首个匹配文本。"""
    match = pattern.search(text)
    if not match:
        return ""
    if match.groupdict().get("line"):
        return match.group("line").strip()
    return match.group(0).strip()


def _first_non_empty_line(text: str) -> str:
    """兜底返回第一条非空文本。"""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""
