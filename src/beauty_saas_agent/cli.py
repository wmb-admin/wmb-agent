from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .config import Settings
from .github_skill_importer import GitHubSkillImporter
from .models import ChatMessage, ChatRequest
from .prompt_builder import PromptRuntime
from .skill_exporter import export_skills, export_standardized_skills


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="Beauty SaaS Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("skills", help="List all parsed skills.")
    subparsers.add_parser("agents", help="List all registered agents.")
    subparsers.add_parser("meta", help="Print runtime metadata.")
    subparsers.add_parser("prompt-list", help="List registered prompt versions.")
    prompt_register_parser = subparsers.add_parser("prompt-register", help="Register a prompt source file.")
    prompt_register_parser.add_argument("--path", required=True, help="Prompt source path, e.g. a .docx file.")
    prompt_register_parser.add_argument("--label", default=None, help="Optional prompt label.")
    prompt_activate_parser = subparsers.add_parser("prompt-activate", help="Activate one prompt version.")
    prompt_activate_parser.add_argument("--prompt-id", required=True, help="Prompt id to activate.")
    subparsers.add_parser("skill-plugins", help="List registered skill plugins.")
    plugin_register_parser = subparsers.add_parser("skill-plugin-register", help="Register a skill plugin directory.")
    plugin_register_parser.add_argument("--name", required=True, help="Plugin name.")
    plugin_register_parser.add_argument("--source-dir", required=True, help="Directory containing skill markdown files.")
    plugin_register_parser.add_argument(
        "--owner-agent",
        default="",
        help="Optional default owner agent: backend, frontend, ops or orchestrator.",
    )
    github_import_parser = subparsers.add_parser(
        "skill-plugin-import-github",
        help="Import skill files from a GitHub repo path and register them as a project plugin.",
    )
    github_import_parser.add_argument("--name", required=True, help="Plugin name.")
    github_import_parser.add_argument("--repo", default="", help="GitHub repo in owner/repo format.")
    github_import_parser.add_argument(
        "--path",
        nargs="*",
        default=[],
        help="One or more repo-relative paths to skill folders or markdown files.",
    )
    github_import_parser.add_argument("--ref", default="main", help="Git branch or tag. Default: main")
    github_import_parser.add_argument("--url", default="", help="GitHub tree/blob URL. Overrides --repo/--path.")
    github_import_parser.add_argument(
        "--owner-agent",
        default="",
        help="Optional default owner agent: backend, frontend, ops or orchestrator.",
    )
    subparsers.add_parser("repo-meta", help="Show configured repositories, toolchain and git policy.")
    repo_status_parser = subparsers.add_parser("repo-status", help="Show local repository status.")
    repo_status_parser.add_argument("--name", default=None, help="Repository name, e.g. backend or frontend.")
    repo_sync_parser = subparsers.add_parser("repo-sync", help="Clone or fast-forward sync repositories.")
    repo_sync_parser.add_argument("--name", default=None, help="Repository name, e.g. backend or frontend.")
    subparsers.add_parser("model-list", help="List models from the configured local model service.")
    model_check_parser = subparsers.add_parser("model-check", help="Check connectivity and run a small prompt.")
    model_check_parser.add_argument(
        "--prompt",
        default="Reply with OK only.",
        help="Prompt used for smoke test.",
    )
    memory_search_parser = subparsers.add_parser("memory-search", help="Search project memory items.")
    memory_search_parser.add_argument("--task", required=True, help="Task text used for memory retrieval.")
    memory_search_parser.add_argument("--workflow", default=None, help="Optional workflow filter hint.")
    memory_search_parser.add_argument("--repo", nargs="*", default=[], help="Optional repo names, e.g. backend frontend.")
    memory_search_parser.add_argument("--limit", type=int, default=6, help="Max memory items to return.")
    tasks_parser = subparsers.add_parser("tasks", help="List persisted task runs.")
    tasks_parser.add_argument("--limit", type=int, default=20, help="How many tasks to list.")
    task_show_parser = subparsers.add_parser("task-show", help="Show one persisted task run.")
    task_show_parser.add_argument("--task-id", required=True, help="Task id to show.")
    task_events_parser = subparsers.add_parser("task-events", help="Show task execution events.")
    task_events_parser.add_argument("--task-id", required=True, help="Task id to inspect.")
    subparsers.add_parser("dashboard-summary", help="Show dashboard summary data.")
    export_parser = subparsers.add_parser("export-skills", help="Export skills into markdown files.")
    export_parser.add_argument(
        "--output-dir",
        default="skills/generated",
        help="Directory for generated skill files.",
    )
    export_standard_parser = subparsers.add_parser(
        "export-standard-skills",
        help="Export standardized skills with inputs, outputs and constraints.",
    )
    export_standard_parser.add_argument(
        "--output-dir",
        default="skills/standardized",
        help="Directory for standardized skill files.",
    )

    run_parser = subparsers.add_parser("run", help="Run one prompt task.")
    run_parser.add_argument("--version", required=True, help="Current iteration version, e.g. v1.0.0")
    run_parser.add_argument("--task", required=True, help="Task for the agent.")
    run_parser.add_argument("--workflow", default=None, help="Workflow preset name.")
    run_parser.add_argument(
        "--skills",
        nargs="*",
        default=[],
        help="Additional skills to enable.",
    )
    run_parser.add_argument(
        "--agents",
        nargs="*",
        default=[],
        help="Explicit agent route, e.g. orchestrator backend frontend ops",
    )
    run_parser.add_argument(
        "--context",
        default="{}",
        help="A JSON object string, e.g. '{\"project\":\"ruoyi-vue3\"}'",
    )
    run_parser.add_argument(
        "--message",
        action="append",
        default=[],
        help="Extra conversation message in role:content format.",
    )
    run_parser.add_argument(
        "--execution-mode",
        default="off",
        choices=["off", "status", "build", "test", "validate", "start"],
        help="Workspace execution mode: inspect repo status or run start/build/test commands before agent reasoning.",
    )
    run_parser.add_argument(
        "--repo",
        nargs="*",
        default=[],
        help="Optional repo names for execution mode, e.g. backend frontend.",
    )
    return parser


def parse_conversation(raw_messages: list[str]) -> list[ChatMessage]:
    """解析 `role:content` 形式的多轮消息参数。"""
    messages = []
    for raw in raw_messages:
        role, separator, content = raw.partition(":")
        if not separator or not content.strip():
            raise ValueError(f"Invalid message format: {raw}")
        messages.append(ChatMessage(role=role.strip(), content=content.strip()))
    return messages


def main() -> int:
    """CLI 主入口。"""
    args = build_parser().parse_args()
    settings = Settings.from_env()
    runtime = PromptRuntime(settings)

    if args.command == "skills":
        print(json.dumps(runtime.meta()["skills"], ensure_ascii=False, indent=2))
        return 0

    if args.command == "agents":
        print(json.dumps(runtime.meta()["agents"], ensure_ascii=False, indent=2))
        return 0

    if args.command == "meta":
        print(json.dumps(runtime.meta(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "prompt-list":
        print(json.dumps(runtime.prompt_registry.meta(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "prompt-register":
        item = runtime.prompt_registry.register(source_path=args.path, label=args.label)
        runtime.reload()
        print(json.dumps(asdict(item), ensure_ascii=False, indent=2))
        return 0

    if args.command == "prompt-activate":
        item = runtime.prompt_registry.activate(args.prompt_id)
        runtime.reload()
        print(json.dumps(asdict(item), ensure_ascii=False, indent=2))
        return 0

    if args.command == "skill-plugins":
        print(json.dumps(runtime.skill_plugin_registry.meta(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "skill-plugin-register":
        plugin = runtime.skill_plugin_registry.register(
            name=args.name,
            source_dir=args.source_dir,
            owner_agent=args.owner_agent,
        )
        runtime.reload()
        print(json.dumps(asdict(plugin), ensure_ascii=False, indent=2))
        return 0

    if args.command == "skill-plugin-import-github":
        plugin = GitHubSkillImporter(settings).import_plugin(
            name=args.name,
            repo=args.repo,
            ref=args.ref,
            paths=args.path,
            url=args.url,
            owner_agent=args.owner_agent,
        )
        runtime.reload()
        print(json.dumps(asdict(plugin), ensure_ascii=False, indent=2))
        return 0

    if args.command == "repo-meta":
        print(json.dumps(runtime.repo_manager.meta(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "repo-status":
        print(json.dumps(runtime.repo_manager.repo_status(name=args.name), ensure_ascii=False, indent=2))
        return 0

    if args.command == "repo-sync":
        print(json.dumps(runtime.repo_manager.sync_repos(name=args.name), ensure_ascii=False, indent=2))
        return 0

    if args.command == "model-list":
        print(json.dumps(runtime.client.list_models(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "model-check":
        print(json.dumps(runtime.client.check_connection(prompt=args.prompt), ensure_ascii=False, indent=2))
        return 0

    if args.command == "memory-search":
        payload = {
            "meta": runtime.project_memory.meta(),
            "items": runtime.project_memory.recall(
                task=args.task,
                workflow=args.workflow,
                repos=args.repo,
                limit=args.limit,
            ),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "tasks":
        tasks = runtime.task_store.list_tasks(limit=args.limit)
        print(json.dumps([task.__dict__ for task in tasks], ensure_ascii=False, indent=2))
        return 0

    if args.command == "task-show":
        task = runtime.task_store.get_task(args.task_id)
        if task is None:
            print(json.dumps({"error": "Task not found"}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(task, ensure_ascii=False, indent=2))
        return 0

    if args.command == "task-events":
        print(
            json.dumps(
                [asdict(item) for item in runtime.task_store.list_events(args.task_id)],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "dashboard-summary":
        summary = runtime.task_store.dashboard_summary()
        summary["skill_plugin_count"] = len(runtime.skill_plugin_registry.list_plugins())
        summary["prompt_count"] = len(runtime.prompt_registry.list_entries())
        summary["repo_count"] = len(runtime.repo_manager.profile.repos)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "export-skills":
        written_files = export_skills(runtime.definition, Path(args.output_dir))
        printable = {name: str(path) for name, path in written_files.items()}
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        return 0

    if args.command == "export-standard-skills":
        written_files = export_standardized_skills(runtime.definition, Path(args.output_dir))
        printable = {name: str(path) for name, path in written_files.items()}
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        return 0

    if args.command == "run":
        context = json.loads(args.context)
        request = ChatRequest(
            task=args.task,
            version=args.version,
            workflow=args.workflow,
            skills=args.skills,
            agents=args.agents,
            context=context,
            conversation=parse_conversation(args.message),
            execution_mode=args.execution_mode,
            repos=args.repo,
        )
        response = runtime.run(request)
        print(response.content)
        return 0

    print(f"Unsupported command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
