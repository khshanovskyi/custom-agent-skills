"""Docker-sandboxed code interpreter tool.

A single long-running container per tool instance is started lazily on first
use. Python state (variables, imports) persists across calls; bash invocations
are stateless. The skills directory is bind-mounted read-only at `/skills`
inside the sandbox, so skill scripts and references are reachable from
executed code without copying them into the request payload.
"""
import asyncio
import json
import secrets
from pathlib import Path
from typing import Any, Optional

from agent_demo.tools.base import BaseTool
from agent_demo.tools.container._response import _ExecutionResult

_RUNNER_FILENAME = "_runner.py"
_CONTAINER_RUNNER_PATH = "/runner.py"
_CONTAINER_SKILLS_PATH = "/skills"


class _Session:
    """Wraps the running container subprocess and serializes calls into it."""

    def __init__(self, proc: asyncio.subprocess.Process):
        self._proc = proc
        self._lock = asyncio.Lock()

    @property
    def alive(self) -> bool:
        return self._proc.returncode is None

    async def execute(self, code: str, language: str, timeout: float) -> dict:
        async with self._lock:
            if not self.alive:
                raise RuntimeError("sandbox container has exited")

            payload = (json.dumps({"code": code, "language": language}) + "\n").encode("utf-8")
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
                    f"code execution exceeded {timeout:.0f}s timeout; sandbox terminated"
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
    """Executes code in an isolated Docker container with no network access.

    A single container per tool instance is started on first use. Python state
    persists across calls; bash invocations are stateless. The skills
    directory is bind-mounted read-only at `/skills` so skill scripts and
    references are accessible from inside the sandbox.
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

        self._session: Optional[_Session] = None
        self._session_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "execute_code"

    @property
    def description(self) -> str:
        return (
            "Execute code in a sandboxed Docker container with no network access. "
            "Use `language` to pick the interpreter: `python` (default) or `bash`. "
            "Python state (variables, imports) persists across calls; bash invocations "
            "are stateless. The skills directory is mounted read-only at `/skills`, so "
            "skill scripts and references can be loaded directly — e.g. "
            "`exec(open('/skills/<skill-name>/scripts/<file>.py').read())` in Python, "
            "or `cat /skills/<skill-name>/...` in bash. Python uses REPL-style display: "
            "the value of a trailing expression is auto-printed via repr()."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Source to execute. May be multi-line.",
                },
                "language": {
                    "type": "string",
                    "enum": ["python", "bash"],
                    "description": (
                        "Interpreter for `code`. Defaults to `python` when omitted."
                    ),
                },
            },
            "required": ["code"],
        }

    async def _execute(self, arguments: dict[str, Any]) -> str:
        code = arguments.get("code", "") or ""
        language = (arguments.get("language") or "python").lower()

        session = await self._get_or_start_session()
        try:
            payload = await session.execute(code, language, self._execution_timeout)
        except RuntimeError as exc:
            await self._reset_session()
            return _ExecutionResult(success=False, error=str(exc)).model_dump_json()

        return _ExecutionResult(**payload).model_dump_json()

    async def _get_or_start_session(self) -> _Session:
        async with self._session_lock:
            session = self._session
            if session is None or not session.alive:
                session = await self._start_session()
                self._session = session
            return session

    async def _reset_session(self) -> None:
        async with self._session_lock:
            if self._session is not None:
                await self._session.close()
                self._session = None

    async def _start_session(self) -> _Session:
        container_name = f"agent_demo-runner-{secrets.token_hex(8)}"
        cmd = [
            self._docker_cmd, "run", "-i", "--rm",
            "--name", container_name,
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
            "-v", f"{self._skills_dir}:{_CONTAINER_SKILLS_PATH}:ro",
            self._image,
            "python", "-u", _CONTAINER_RUNNER_PATH,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return _Session(proc)

    async def close(self) -> None:
        await self._reset_session()
