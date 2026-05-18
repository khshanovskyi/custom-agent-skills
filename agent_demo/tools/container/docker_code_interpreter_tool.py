"""Docker-sandboxed Python code interpreter tool.

Each session maps to a long-running Docker container with no network access.
The container runs `_runner.py` (mounted read-only), which speaks a JSON-line
protocol over stdin/stdout. State persists within a session.
"""
import asyncio
import json
import secrets
from pathlib import Path
from typing import Any, Optional

from agent_demo.file_utils import get_file_content
from agent_demo.tools.base import BaseTool
from agent_demo.tools.container._response import _ExecutionResult

_RUNNER_FILENAME = "_runner.py"
_CONTAINER_RUNNER_PATH = "/runner.py"
_SESSION_INSTRUCTIONS = (
    "Reuse this session_id for subsequent calls in this conversation. "
    "Variables and imports persist within the session."
)


class _Session:
    """Wraps one long-running container subprocess and serializes calls into it."""

    def __init__(self, session_id: str, proc: asyncio.subprocess.Process):
        self.session_id = session_id
        self._proc = proc
        self._lock = asyncio.Lock()

    @property
    def alive(self) -> bool:
        return self._proc.returncode is None

    async def execute(self, code: str, timeout: float) -> dict:
        async with self._lock:
            if not self.alive:
                raise RuntimeError(f"session {self.session_id} container has exited")

            payload = (json.dumps({"code": code}) + "\n").encode("utf-8")
            try:
                self._proc.stdin.write(payload)
                await self._proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                stderr = await self._drain_stderr()
                raise RuntimeError(
                    f"failed to write to container stdin: {exc}. stderr: {stderr}"
                ) from exc

            try:
                line = await asyncio.wait_for(self._proc.stdout.readline(), timeout)
            except asyncio.TimeoutError:
                raise RuntimeError(
                    f"code execution exceeded {timeout:.0f}s timeout; session terminated"
                )

            if not line:
                stderr = await self._drain_stderr()
                raise RuntimeError(f"runner exited unexpectedly. stderr: {stderr}")

            return json.loads(line.decode("utf-8"))

    async def _drain_stderr(self) -> str:
        try:
            data = await asyncio.wait_for(self._proc.stderr.read(), 1.0)
        except asyncio.TimeoutError:
            return "<stderr read timed out>"
        return data.decode("utf-8", errors="replace")

    async def close(self) -> None:
        if self._proc.returncode is None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(self._proc.wait(), 5.0)
        except asyncio.TimeoutError:
            pass


class DockerCodeInterpreterTool(BaseTool):
    """Executes Python code in an isolated Docker container with no network access.

    Each `session_id` maps to one long-running container. State (variables,
    imports) persists within a session. The container is launched with
    `--network=none` and additional hardening flags.
    """

    def __init__(
        self,
        skills_dir: Path,
        image: str = "python:3.11-slim",
        memory_limit: str = "512m",
        cpu_limit: str = "1.0",
        pids_limit: int = 128,
        tmpfs_size: str = "64m",
        execution_timeout: float = 30.0,
        docker_cmd: str = "docker",
    ):
        self._skills_dir = skills_dir.resolve()
        self._image = image
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._pids_limit = pids_limit
        self._tmpfs_size = tmpfs_size
        self._execution_timeout = execution_timeout
        self._docker_cmd = docker_cmd

        self._runner_path = (Path(__file__).parent / _RUNNER_FILENAME).resolve()
        if not self._runner_path.is_file():
            raise FileNotFoundError(f"runner script not found: {self._runner_path}")

        self._sessions: dict[str, _Session] = {}

    @property
    def name(self) -> str:
        return "execute_code"

    @property
    def description(self) -> str:
        return (
            "Execute Python code in a sandboxed Docker container with no network access. "
            "Pass session_id=\"\" to start a new session; reuse the returned session_id "
            "for follow-up calls so variables and imports persist. Optional script_path "
            "(relative to the skills root) loads a script file from disk and prepends "
            "its contents to `code` before execution — use this on the first call of a "
            "session to load a skill's script without copying it into the request."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source to execute. May be multi-line.",
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Session identifier. Pass an empty string to start a new "
                        "session; reuse the value returned in session_info for "
                        "subsequent calls."
                    ),
                },
                "script_path": {
                    "type": "string",
                    "description": (
                        "Optional path relative to the skills root (e.g. "
                        "/unit-converter/scripts/convert.py). When set, the file's "
                        "contents are prepended to `code` before execution."
                    ),
                },
            },
            "required": ["code"],
        }

    async def _execute(self, arguments: dict[str, Any]) -> str:
        code = arguments.get("code", "") or ""
        session_id = arguments.get("session_id") or ""
        script_path = arguments.get("script_path")

        if script_path:
            full_path = (self._skills_dir / script_path.lstrip("/")).resolve()
            script_content = get_file_content(full_path)
            code = f"{script_content}\n\n{code}"

        new_session = not session_id
        if new_session:
            session_id = secrets.token_hex(8)
            self._sessions[session_id] = await self._start_session(session_id)

        session = self._sessions.get(session_id)
        if session is None:
            return _ExecutionResult(
                success=False,
                error=(
                    f"SessionExpiredError: Session {session_id} not found or has expired. "
                    "Start a new session by passing session_id=\"\"."
                ),
            ).model_dump_json()

        try:
            payload = await session.execute(code, self._execution_timeout)
        except RuntimeError as exc:
            self._sessions.pop(session_id, None)
            await session.close()
            return _ExecutionResult(success=False, error=str(exc)).model_dump_json()

        if new_session:
            payload["session_info"] = {
                "session_id": session_id,
                "instructions": _SESSION_INSTRUCTIONS,
            }

        return _ExecutionResult(**payload).model_dump_json()

    async def _start_session(self, session_id: str) -> _Session:
        cmd = [
            self._docker_cmd, "run", "-i", "--rm",
            "--name", f"agent_demo-runner-{session_id}",
            "--network=none",
            f"--memory={self._memory_limit}",
            f"--cpus={self._cpu_limit}",
            f"--pids-limit={self._pids_limit}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--read-only",
            f"--tmpfs=/tmp:size={self._tmpfs_size},mode=1777",
            "-e", "PYTHONDONTWRITEBYTECODE=1",
            "-e", "PYTHONIOENCODING=utf-8",
            "-v", f"{self._runner_path}:{_CONTAINER_RUNNER_PATH}:ro",
            self._image,
            "python", "-u", _CONTAINER_RUNNER_PATH,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return _Session(session_id, proc)

    async def close(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
