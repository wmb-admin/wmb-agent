from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SkillDefinition:
    """原始 Prompt 解析得到的技能定义。"""
    name: str
    title: str
    group: str
    lines: List[str] = field(default_factory=list)
    owner_agent: str = ""
    source: str = "prompt"

    @property
    def content(self) -> str:
        return "\n".join(line for line in self.lines if line.strip()).strip()


@dataclass
class StandardSkillDefinition:
    """标准化技能定义（用于导出可复用模板）。"""
    name: str
    title: str
    group: str
    purpose: str
    when_to_use: List[str] = field(default_factory=list)
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    checklist: List[str] = field(default_factory=list)
    handoff_to: List[str] = field(default_factory=list)
    source_prompt: str = ""
    raw_prompt: str = ""


@dataclass
class AgentDefinition:
    """Agent 角色定义。"""
    name: str
    title: str
    mission: str
    responsibilities: List[str] = field(default_factory=list)
    owned_skills: List[str] = field(default_factory=list)
    allowed_handoffs: List[str] = field(default_factory=list)


@dataclass
class PromptDefinition:
    """完整 Prompt 结构化结果。"""
    title: str
    raw_text: str
    agent_goal: str
    version_policy: str
    execution_flow: List[str]
    constraints: List[str]
    skills: Dict[str, SkillDefinition]


@dataclass
class ChatMessage:
    """对话消息。"""
    role: str
    content: str


@dataclass
class ChatRequest:
    """任务请求输入。"""
    task: str
    version: str
    workflow: Optional[str] = None
    skills: List[str] = field(default_factory=list)
    agents: List[str] = field(default_factory=list)
    context: Dict[str, object] = field(default_factory=dict)
    conversation: List[ChatMessage] = field(default_factory=list)
    execution_mode: str = "off"
    repos: List[str] = field(default_factory=list)


@dataclass
class AgentExecutionStep:
    """执行计划中的单个 Agent 步骤。"""
    agent: str
    title: str
    skills: List[str] = field(default_factory=list)
    status: str = "planned"
    handoff_to: Optional[str] = None
    output: str = ""


@dataclass
class ExecutionPlan:
    """任务执行计划。"""
    workflow: Optional[str]
    agents: List[str] = field(default_factory=list)
    skill_map: Dict[str, List[str]] = field(default_factory=dict)
    steps: List[AgentExecutionStep] = field(default_factory=list)


@dataclass
class HandoffRecord:
    """Agent 交接记录。"""
    from_agent: str
    to_agent: str
    reason: str
    payload: str


@dataclass
class ExecutionCommandResult:
    """工作区命令执行结果。"""
    repo_name: str
    phase: str
    command: str
    status: str
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    reason: str = ""


@dataclass
class ExecutionLocation:
    """错误定位信息（文件/行列）。"""
    path: str
    label: str = ""
    line: int = 0
    column: int = 0
    exists: bool = False


@dataclass
class ExecutionRecommendation:
    """命令失败后的修复建议。"""
    repo_name: str
    phase: str
    title: str
    summary: str
    priority: str = "medium"
    suggested_commands: List[str] = field(default_factory=list)
    related_skills: List[str] = field(default_factory=list)
    evidence: str = ""
    failure_kind: str = "generic"
    primary_error: str = ""
    failed_targets: List[str] = field(default_factory=list)
    suggested_workflow: str = ""
    suggested_execution_mode: str = ""
    suggested_repos: List[str] = field(default_factory=list)
    recovery_steps: List[str] = field(default_factory=list)
    locations: List[ExecutionLocation] = field(default_factory=list)


@dataclass
class ExecutionGateResult:
    """质量门禁结果。"""
    gate_name: str
    status: str = "passed"
    summary: str = ""
    details: List[str] = field(default_factory=list)
    blocking: bool = False


@dataclass
class ChatResponse:
    """任务响应输出。"""
    task_id: str
    model: str
    content: str
    used_skills: List[str]
    workflow: Optional[str]
    version: str
    status: str = "completed"
    created_at: str = ""
    updated_at: str = ""
    used_agents: List[str] = field(default_factory=list)
    steps: List[AgentExecutionStep] = field(default_factory=list)
    handoffs: List[HandoffRecord] = field(default_factory=list)
    execution_mode: str = "off"
    repos: List[str] = field(default_factory=list)
    execution_results: List[ExecutionCommandResult] = field(default_factory=list)
    execution_recommendations: List[ExecutionRecommendation] = field(default_factory=list)
    gate_results: List[ExecutionGateResult] = field(default_factory=list)


@dataclass
class TaskSummary:
    """任务列表摘要。"""
    task_id: str
    status: str
    workflow: Optional[str]
    version: str
    task: str
    created_at: str
    updated_at: str
    used_agents: List[str] = field(default_factory=list)
    used_skills: List[str] = field(default_factory=list)
    error_message: str = ""


@dataclass
class TaskEvent:
    """任务事件流记录。"""
    task_id: str
    event_type: str
    created_at: str
    payload: Dict[str, object] = field(default_factory=dict)
    event_id: int = 0


@dataclass
class PromptRegistryEntry:
    """Prompt 注册中心条目。"""
    prompt_id: str
    label: str
    source_path: str
    title: str
    registered_at: str
    is_active: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class SkillPlugin:
    """技能插件注册条目。"""
    plugin_id: str
    name: str
    kind: str
    source_dir: str
    manifest_path: str = ""
    enabled: bool = True
    registered_at: str = ""
    notes: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    owner_agent: str = ""
    repo: str = ""
    ref: str = ""
    source_url: str = ""
    import_paths: List[str] = field(default_factory=list)
