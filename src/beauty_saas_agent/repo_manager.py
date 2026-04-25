from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import Settings
from .models import ExecutionCommandResult
from .workspace_profile import RepositoryProfile, WorkspaceProfile, WorkspaceSecrets, load_workspace_profile, load_workspace_secrets


class RepoManager:
    """仓库与进程管理器：统一处理 repo 状态、命令执行和后台进程生命周期。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.profile: WorkspaceProfile = load_workspace_profile(settings)
        self.secrets: WorkspaceSecrets = load_workspace_secrets(settings)
        data_root = Path(settings.task_storage_dir).expanduser().resolve().parent
        self.process_dir = data_root / "processes"
        self.process_dir.mkdir(parents=True, exist_ok=True)
        self.process_log_dir = self.process_dir / "logs"
        self.process_log_dir.mkdir(parents=True, exist_ok=True)
        self.process_registry_path = self.process_dir / "runtime-processes.json"

    def reload(self) -> None:
        """热重载 workspace profile 和 secrets。"""
        self.profile = load_workspace_profile(self.settings)
        self.secrets = load_workspace_secrets(self.settings)

    def meta(self) -> Dict[str, object]:
        """返回仓库/工具链/进程元信息。"""
        return {
            "profile_path": self.settings.workspace_profile_path,
            "secrets_path": self.settings.workspace_secrets_path,
            "toolchain": self.profile.toolchain.__dict__,
            "git_policy": self.profile.git_policy.__dict__,
            "repos": [repo.__dict__ for repo in self.profile.repos],
            "services": [service.__dict__ for service in self.profile.services],
            "notes": self.profile.notes,
            "has_git_credentials": bool(self.secrets.git_username and self.secrets.git_password),
            "running_process_count": len(self.list_running_processes()),
        }

    def list_repos(self) -> List[Dict[str, object]]:
        """列出所有配置仓库及本地存在性状态。"""
        items = []
        for repo in self.profile.repos:
            local_path = Path(repo.local_path)
            items.append(
                {
                    "name": repo.name,
                    "kind": repo.kind,
                    "branch": repo.branch,
                    "remote_url": repo.remote_url,
                    "local_path": repo.local_path,
                    "exists": local_path.exists(),
                    "has_git_dir": (local_path / ".git").exists(),
                }
            )
        return items

    def repo_status(self, name: Optional[str] = None) -> List[Dict[str, object]]:
        """查询一个或全部仓库状态。"""
        repos = self._select_repos(name)
        return self._repo_status_for_repos(repos)

    def repo_status_for_names(self, names: List[str]) -> List[Dict[str, object]]:
        repos = self._select_repos_by_names(names)
        return self._repo_status_for_repos(repos)

    def _repo_status_for_repos(self, repos: List[RepositoryProfile]) -> List[Dict[str, object]]:
        statuses = []
        for repo in repos:
            local_path = Path(repo.local_path)
            status = {
                "name": repo.name,
                "branch": repo.branch,
                "local_path": repo.local_path,
                "exists": local_path.exists(),
                "current_branch": "",
                "git_status": "",
            }
            if (local_path / ".git").exists():
                status["current_branch"] = self._run_git(["branch", "--show-current"], cwd=local_path).strip()
                status["git_status"] = self._run_git(["status", "--short"], cwd=local_path).strip()
            statuses.append(status)
        return statuses

    def sync_repos(self, name: Optional[str] = None) -> List[Dict[str, object]]:
        """拉取/同步仓库到目标分支。"""
        repos = self._select_repos(name)
        results = []
        for repo in repos:
            results.append(self._sync_repo(repo))
        return results

    def _select_repos(self, name: Optional[str]) -> List[RepositoryProfile]:
        """按名称筛选仓库；为空时返回全部。"""
        if not name:
            return list(self.profile.repos)
        for repo in self.profile.repos:
            if repo.name == name:
                return [repo]
        raise ValueError(f"Repository not found: {name}")

    def get_repo(self, name: str) -> RepositoryProfile:
        """获取单个仓库配置。"""
        return self._select_repos(name)[0]

    def find_repo_by_path(self, file_path: str | Path) -> Optional[RepositoryProfile]:
        """按文件路径反查归属仓库（优先最长前缀匹配）。"""
        candidate = Path(file_path).expanduser().resolve()
        matches: List[tuple[int, RepositoryProfile]] = []
        for repo in self.profile.repos:
            repo_root = Path(repo.local_path).expanduser().resolve()
            try:
                candidate.relative_to(repo_root)
            except ValueError:
                continue
            matches.append((len(str(repo_root)), repo))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    def read_file_diff(self, file_path: str | Path, context_lines: int = 3) -> Dict[str, object]:
        """读取单文件 git diff，供前端详情查看。"""
        candidate = Path(file_path).expanduser().resolve()
        repo = self.find_repo_by_path(candidate)
        if repo is None:
            return {
                "path": str(candidate),
                "in_repo": False,
                "repo_name": "",
                "repo_path": "",
                "relative_path": "",
                "diff": "",
            }

        repo_root = Path(repo.local_path).expanduser().resolve()
        relative_path = str(candidate.relative_to(repo_root))
        diff_output = self._run_git(
            ["diff", f"--unified={context_lines}", "--", relative_path],
            cwd=repo_root,
        ).strip()
        return {
            "path": str(candidate),
            "in_repo": True,
            "repo_name": repo.name,
            "repo_path": str(repo_root),
            "relative_path": relative_path,
            "diff": diff_output,
        }

    def _select_repos_by_names(self, names: List[str]) -> List[RepositoryProfile]:
        """按名称列表筛选仓库，并去重。"""
        selected: List[RepositoryProfile] = []
        seen = set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            selected.extend(self._select_repos(name))
        return selected

    def resolve_execution_repo_names(self, agent_ids: List[str], requested_repos: List[str]) -> List[str]:
        """根据显式仓库或 agent 能力推断执行仓库。"""
        if requested_repos:
            self._select_repos_by_names(requested_repos)
            return list(dict.fromkeys(requested_repos))

        names: List[str] = []
        for repo in self.profile.repos:
            if repo.kind in agent_ids:
                names.append(repo.name)
                continue
            if "ops" in agent_ids and repo.kind in {"backend", "frontend"}:
                names.append(repo.name)
        if not names:
            names = [repo.name for repo in self.profile.repos]
        return list(dict.fromkeys(names))

    def execute_repo_commands(
        self,
        repo_names: List[str],
        phases: List[str],
        timeout_seconds: int = 1800,
        cancel_event: Optional[threading.Event] = None,
    ) -> List[ExecutionCommandResult]:
        """按仓库和阶段执行命令，失败即中断该阶段后续命令。"""
        def _is_cancelled() -> bool:
            return bool(cancel_event is not None and cancel_event.is_set())

        # 阶段1：根据 repo_names 解析目标仓库集合。
        repos = self._select_repos_by_names(repo_names)
        results: List[ExecutionCommandResult] = []
        # 阶段2：按“仓库 -> 阶段 -> 命令”顺序执行。
        for repo in repos:
            if _is_cancelled():
                return results
            for phase in phases:
                if _is_cancelled():
                    return results
                commands = self._commands_for_phase(repo, phase)
                if not commands:
                    results.append(
                        ExecutionCommandResult(
                            repo_name=repo.name,
                            phase=phase,
                            command="",
                            status="skipped",
                            reason=f"No {phase} commands configured.",
                        )
                    )
                    continue
                for command in commands:
                    # start 阶段若是长驻命令（如 dev server），转后台执行。
                    if phase == "start" and self._should_run_in_background(command):
                        result = self._run_background_shell_command(
                            repo_name=repo.name,
                            phase=phase,
                            command=command,
                            cwd=Path(repo.local_path),
                        )
                    else:
                        result = self._run_shell_command(
                            repo_name=repo.name,
                            phase=phase,
                            command=command,
                            cwd=Path(repo.local_path),
                            timeout_seconds=timeout_seconds,
                            cancel_event=cancel_event,
                        )
                    results.append(result)
                    if result.status == "failed" or _is_cancelled():
                        # 单阶段内失败即停止继续执行该阶段后续命令，避免噪声。
                        break
        return results

    def _commands_for_phase(self, repo: RepositoryProfile, phase: str) -> List[str]:
        """按阶段返回仓库预置命令列表。"""
        if phase == "build":
            return list(repo.build_commands)
        if phase == "test":
            return list(repo.test_commands)
        if phase == "start":
            return list(repo.start_commands)
        raise ValueError(f"Unsupported execution phase: {phase}")

    @contextmanager
    def _git_auth_env(self):
        """构造临时 Git 鉴权环境（通过 GIT_ASKPASS）。"""
        env = os.environ.copy()
        script_path = None
        if self.secrets.git_username or self.secrets.git_password:
            script_file = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
            script_file.write(
                "#!/bin/sh\n"
                'case "$1" in\n'
                '  *sername*) printf "%s" "$GIT_USERNAME" ;;\n'
                '  *assword*) printf "%s" "$GIT_PASSWORD" ;;\n'
                '  *) printf "" ;;\n'
                "esac\n"
            )
            script_file.flush()
            script_file.close()
            script_path = script_file.name
            os.chmod(script_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            env["GIT_ASKPASS"] = script_path
            env["GIT_TERMINAL_PROMPT"] = "0"
            env["GIT_USERNAME"] = self.secrets.git_username
            env["GIT_PASSWORD"] = self.secrets.git_password
        try:
            yield env
        finally:
            if script_path:
                try:
                    Path(script_path).unlink()
                except FileNotFoundError:
                    pass

    def _sync_repo(self, repo: RepositoryProfile) -> Dict[str, object]:
        """同步单仓库：不存在则 clone，存在则 fetch/checkout/pull。"""
        local_path = Path(repo.local_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        with self._git_auth_env() as env:
            if not (local_path / ".git").exists():
                clone_output = self._run_git(
                    ["clone", "--branch", repo.branch, repo.remote_url, str(local_path)],
                    cwd=local_path.parent,
                    env=env,
                )
                return {
                    "name": repo.name,
                    "action": "clone",
                    "branch": repo.branch,
                    "local_path": repo.local_path,
                    "output": clone_output.strip(),
                }

            fetch_output = self._run_git(["fetch", "origin", repo.branch], cwd=local_path, env=env)
            checkout_output = self._run_git(["checkout", repo.branch], cwd=local_path, env=env)
            pull_output = self._run_git(["pull", "--ff-only", "origin", repo.branch], cwd=local_path, env=env)
            return {
                "name": repo.name,
                "action": "sync",
                "branch": repo.branch,
                "local_path": repo.local_path,
                "output": "\n".join(
                    part for part in [fetch_output.strip(), checkout_output.strip(), pull_output.strip()] if part
                ),
            }

    def _run_git(self, args: List[str], cwd: Path, env: Optional[Dict[str, str]] = None) -> str:
        """执行 git 命令并返回 stdout。"""
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=env or os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
        return result.stdout

    def _run_shell_command(
        self,
        repo_name: str,
        phase: str,
        command: str,
        cwd: Path,
        timeout_seconds: int,
        cancel_event: Optional[threading.Event] = None,
    ) -> ExecutionCommandResult:
        """前台执行命令并返回结构化结果。"""
        def _is_cancelled() -> bool:
            return bool(cancel_event is not None and cancel_event.is_set())

        started = self._now()
        if _is_cancelled():
            finished = self._now()
            return ExecutionCommandResult(
                repo_name=repo_name,
                phase=phase,
                command=command,
                status="failed",
                exit_code=None,
                stdout="",
                stderr="",
                started_at=started,
                finished_at=finished,
                duration_ms=self._duration_ms(started, finished),
                reason="Command canceled by user.",
            )
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=True,
                executable=os.environ.get("SHELL", "/bin/sh"),
                start_new_session=True,
            )
            stdout = ""
            stderr = ""
            deadline = time.monotonic() + max(1, timeout_seconds)
            while True:
                if _is_cancelled():
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except OSError:
                        pass
                    try:
                        out, err = process.communicate(timeout=3)
                        stdout = out or ""
                        stderr = err or ""
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except OSError:
                            pass
                        out, err = process.communicate()
                        stdout = out or ""
                        stderr = err or ""
                    finished = self._now()
                    return ExecutionCommandResult(
                        repo_name=repo_name,
                        phase=phase,
                        command=command,
                        status="failed",
                        exit_code=process.returncode,
                        stdout=stdout,
                        stderr=stderr,
                        started_at=started,
                        finished_at=finished,
                        duration_ms=self._duration_ms(started, finished),
                        reason="Command canceled by user.",
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except OSError:
                        pass
                    try:
                        out, err = process.communicate(timeout=3)
                        stdout = out or ""
                        stderr = err or ""
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except OSError:
                            pass
                        out, err = process.communicate()
                        stdout = out or ""
                        stderr = err or ""
                    finished = self._now()
                    return ExecutionCommandResult(
                        repo_name=repo_name,
                        phase=phase,
                        command=command,
                        status="failed",
                        exit_code=None,
                        stdout=stdout,
                        stderr=stderr,
                        started_at=started,
                        finished_at=finished,
                        duration_ms=self._duration_ms(started, finished),
                        reason=f"Command timed out after {timeout_seconds} seconds.",
                    )
                try:
                    out, err = process.communicate(timeout=min(0.4, max(0.05, remaining)))
                    stdout = out or ""
                    stderr = err or ""
                    break
                except subprocess.TimeoutExpired:
                    continue
            finished = self._now()
            return ExecutionCommandResult(
                repo_name=repo_name,
                phase=phase,
                command=command,
                status="completed" if process.returncode == 0 else "failed",
                exit_code=process.returncode,
                stdout=stdout,
                stderr=stderr,
                started_at=started,
                finished_at=finished,
                duration_ms=self._duration_ms(started, finished),
            )
        except subprocess.TimeoutExpired as exc:
            finished = self._now()
            return ExecutionCommandResult(
                repo_name=repo_name,
                phase=phase,
                command=command,
                status="failed",
                exit_code=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                started_at=started,
                finished_at=finished,
                duration_ms=self._duration_ms(started, finished),
                reason=f"Command timed out after {timeout_seconds} seconds.",
            )

    def _run_background_shell_command(
        self,
        repo_name: str,
        phase: str,
        command: str,
        cwd: Path,
        warmup_seconds: int = 3,
    ) -> ExecutionCommandResult:
        """后台拉起长生命周期服务（如 dev server/spring-boot）。"""
        # 阶段1：先判断相同命令是否已有存活进程，避免重复启动。
        started = self._now()
        existing = self._find_existing_background_process(repo_name=repo_name, command=command, cwd=cwd)
        if existing:
            finished = self._now()
            return ExecutionCommandResult(
                repo_name=repo_name,
                phase=phase,
                command=command,
                status="completed",
                exit_code=None,
                stdout="",
                stderr="",
                started_at=started,
                finished_at=finished,
                duration_ms=self._duration_ms(started, finished),
                reason=(
                    f"Background process already running (pid={existing['pid']}). "
                    f"log={existing.get('log_path', '')}"
                ),
            )

        # 阶段2：启动新进程并绑定日志文件。
        log_name = f"{repo_name}-{phase}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
        log_path = self.process_log_dir / log_name
        with log_path.open("a", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=os.environ.copy(),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                shell=True,
                executable=os.environ.get("SHELL", "/bin/sh"),
                start_new_session=True,
                text=True,
            )

        # 阶段3：预热检测。若进程短时间退出，直接返回失败并附带日志尾部。
        time.sleep(max(1, warmup_seconds))
        poll_code = process.poll()
        finished = self._now()
        if poll_code is not None:
            # 预热窗口内退出通常意味着配置/依赖/端口等硬错误。
            return ExecutionCommandResult(
                repo_name=repo_name,
                phase=phase,
                command=command,
                status="failed",
                exit_code=poll_code,
                stdout=self._read_log_tail(log_path),
                stderr="",
                started_at=started,
                finished_at=finished,
                duration_ms=self._duration_ms(started, finished),
                reason=f"Background process exited during warmup. log={log_path}",
            )

        # 阶段4：注册后台进程信息，便于后续查询和停止。
        self._register_background_process(
            repo_name=repo_name,
            phase=phase,
            command=command,
            cwd=cwd,
            pid=process.pid,
            log_path=log_path,
            started_at=started,
        )
        return ExecutionCommandResult(
            repo_name=repo_name,
            phase=phase,
            command=command,
            status="completed",
            exit_code=None,
            stdout="",
            stderr="",
            started_at=started,
            finished_at=finished,
            duration_ms=self._duration_ms(started, finished),
            reason=f"Background process started (pid={process.pid}). log={log_path}",
        )

    def _should_run_in_background(self, command: str) -> bool:
        """判断命令是否应以后台模式启动。"""
        lowered = command.lower()
        if "spring-boot" in lowered and ":run" in lowered:
            return True
        long_running_markers = [
            "spring-boot:run",
            "spring-boot-maven-plugin",
            "org.springframework.boot:spring-boot-maven-plugin",
            " java -jar",
            "java -jar",
            "pnpm dev",
            "npm run dev",
            "npm start",
            "vite",
            "webpack serve",
            "uvicorn",
            "gunicorn",
            "python -m http.server",
            "serve ",
        ]
        return any(marker in lowered for marker in long_running_markers)

    def _read_process_registry(self) -> Dict[str, object]:
        """读取进程注册表；损坏时兜底空列表。"""
        if not self.process_registry_path.exists():
            return {"processes": []}
        try:
            return json.loads(self.process_registry_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"processes": []}

    def _write_process_registry(self, payload: Dict[str, object]) -> None:
        """写入进程注册表。"""
        self.process_registry_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _is_process_alive(self, pid: int) -> bool:
        """检查进程是否存活。"""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _cleanup_process_registry(self) -> List[Dict[str, object]]:
        """清理注册表中的僵尸进程记录，仅保留存活项。"""
        payload = self._read_process_registry()
        active = [
            item
            for item in payload.get("processes", [])
            if int(item.get("pid", 0) or 0) > 0 and self._is_process_alive(int(item.get("pid", 0)))
        ]
        payload["processes"] = active
        self._write_process_registry(payload)
        return active

    def list_running_processes(self) -> List[Dict[str, object]]:
        """返回当前存活后台进程。"""
        return self._cleanup_process_registry()

    def stop_running_processes(
        self,
        repo_name: Optional[str] = None,
        repo_names: Optional[List[str]] = None,
        phase: Optional[str] = None,
    ) -> List[Dict[str, object]]:
        """停止后台进程，支持按仓库或阶段过滤。"""
        # 阶段1：读取当前存活进程并标准化过滤条件。
        active_processes = self._cleanup_process_registry()
        normalized_repo_names = {name for name in (repo_names or []) if isinstance(name, str) and name}
        if repo_name:
            normalized_repo_names.add(repo_name)

        stopped_items: List[Dict[str, object]] = []
        remaining_items: List[Dict[str, object]] = []

        # 阶段2：逐个判断是否需要停止，并记录停止结果。
        for item in active_processes:
            item_repo_name = str(item.get("repo_name", ""))
            item_phase = str(item.get("phase", ""))
            should_stop = True
            if normalized_repo_names and item_repo_name not in normalized_repo_names:
                should_stop = False
            if phase and item_phase != phase:
                should_stop = False

            if not should_stop:
                remaining_items.append(item)
                continue

            pid = int(item.get("pid", 0) or 0)
            termination = self._terminate_process(pid)
            stop_record = dict(item)
            stop_record.update(
                {
                    "stop_status": termination.get("status", "failed"),
                    "stop_signal": termination.get("signal", ""),
                    "stop_reason": termination.get("reason", ""),
                    "stop_alive": bool(termination.get("alive", True)),
                }
            )
            stopped_items.append(stop_record)

            if bool(termination.get("alive", True)):
                remaining_items.append(item)

        # 阶段3：回写剩余存活进程。
        self._write_process_registry({"processes": remaining_items})
        return stopped_items

    def _terminate_process(self, pid: int, grace_seconds: float = 3.0) -> Dict[str, object]:
        """优先 SIGTERM，再兜底 SIGKILL，返回详细停止结果。"""
        if pid <= 0:
            return {
                "status": "failed",
                "signal": "",
                "alive": False,
                "reason": f"Invalid pid: {pid}",
            }
        if not self._is_process_alive(pid):
            return {
                "status": "not_running",
                "signal": "",
                "alive": False,
                "reason": "Process already exited.",
            }

        # 阶段1：尝试优先优雅停止（先进程组，再单进程兜底）。
        signal_sent = ""
        term_error = ""
        try:
            os.killpg(pid, signal.SIGTERM)
            signal_sent = "SIGTERM(group)"
        except ProcessLookupError:
            return {
                "status": "not_running",
                "signal": "SIGTERM(group)",
                "alive": False,
                "reason": "Process already exited.",
            }
        except OSError as exc:
            term_error = str(exc)
            try:
                os.kill(pid, signal.SIGTERM)
                signal_sent = "SIGTERM"
                term_error = ""
            except ProcessLookupError:
                return {
                    "status": "not_running",
                    "signal": "SIGTERM",
                    "alive": False,
                    "reason": "Process already exited.",
                }
            except OSError as inner_exc:
                return {
                    "status": "failed",
                    "signal": "SIGTERM",
                    "alive": self._is_process_alive(pid),
                    "reason": f"Failed to send SIGTERM: {inner_exc}",
                }

        # 阶段2：等待优雅退出窗口。
        deadline = time.monotonic() + max(0.0, grace_seconds)
        while time.monotonic() < deadline:
            if not self._is_process_alive(pid):
                return {
                    "status": "stopped",
                    "signal": signal_sent,
                    "alive": False,
                    "reason": "",
                }
            time.sleep(0.1)

        # 阶段3：超时后强制杀死（先进程组，再单进程兜底）。
        kill_signal = "SIGKILL(group)"
        kill_error = ""
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return {
                "status": "stopped",
                "signal": f"{signal_sent}->SIGKILL(group)",
                "alive": False,
                "reason": "",
            }
        except OSError as exc:
            kill_error = str(exc)
            kill_signal = "SIGKILL"
            try:
                os.kill(pid, signal.SIGKILL)
                kill_error = ""
            except ProcessLookupError:
                return {
                    "status": "stopped",
                    "signal": f"{signal_sent}->SIGKILL",
                    "alive": False,
                    "reason": "",
                }
            except OSError as inner_exc:
                return {
                    "status": "failed",
                    "signal": f"{signal_sent}->SIGKILL",
                    "alive": self._is_process_alive(pid),
                    "reason": f"Failed to send SIGKILL: {inner_exc}",
                }

        # 阶段4：汇总最终结果。
        time.sleep(0.2)
        alive = self._is_process_alive(pid)
        reason = ""
        if term_error or kill_error:
            reason = "; ".join([item for item in [term_error, kill_error] if item])
        if alive:
            reason = reason or "Process is still alive after SIGKILL."
        return {
            "status": "failed" if alive else "stopped",
            "signal": f"{signal_sent}->{kill_signal}",
            "alive": alive,
            "reason": reason,
        }

    def _find_existing_background_process(self, repo_name: str, command: str, cwd: Path) -> Optional[Dict[str, object]]:
        """查找已登记且仍存活的同源后台进程。"""
        for item in self._cleanup_process_registry():
            if (
                item.get("repo_name") == repo_name
                and item.get("command") == command
                and item.get("cwd") == str(cwd)
            ):
                return item
        return None

    def _register_background_process(
        self,
        repo_name: str,
        phase: str,
        command: str,
        cwd: Path,
        pid: int,
        log_path: Path,
        started_at: str,
    ) -> None:
        """把新拉起的后台进程写入注册表。"""
        # 先做一次清理，避免把僵尸进程继续写回注册表。
        processes = self._cleanup_process_registry()
        processes.append(
            {
                "repo_name": repo_name,
                "phase": phase,
                "command": command,
                "cwd": str(cwd),
                "pid": pid,
                "log_path": str(log_path),
                "started_at": started_at,
            }
        )
        self._write_process_registry({"processes": processes})

    def _read_log_tail(self, log_path: Path, limit: int = 2000) -> str:
        """读取日志尾部，避免一次性返回过大日志。"""
        if not log_path.exists():
            return ""
        content = log_path.read_text(encoding="utf-8", errors="ignore")
        if len(content) <= limit:
            return content
        return content[-limit:]

    def _now(self) -> str:
        """返回 UTC ISO 时间戳。"""
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _duration_ms(self, started: str, finished: str) -> int:
        """计算毫秒级耗时。"""
        started_at = datetime.fromisoformat(started)
        finished_at = datetime.fromisoformat(finished)
        return int((finished_at - started_at).total_seconds() * 1000)
