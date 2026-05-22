"""Docker-sandboxed code interpreter tool.

One container per skill is started lazily on first use and kept alive for the
duration of the user session (pool model). Python state persists within a
skill's container across all tool calls in the same turn; bash invocations are
stateless. At the end of each user turn the host calls reset_all() to wipe
every container, preventing secrets from leaking into subsequent turns.

The skills directory is bind-mounted read-only at `/skills` so skill scripts
and references are reachable without copying them into the request payload.
"""
import asyncio
import json
import secrets
import time
from pathlib import Path
from typing import Any, Optional

from agent_demo.tools.base import BaseTool
from agent_demo.tools.container._response import _ExecutionResult

_RUNNER_FILENAME = "_runner.py"
_CONTAINER_RUNNER_PATH = "/runner.py"
_CONTAINER_SKILLS_PATH = "/skills"
_DEFAULT_SKILL_KEY = "__no_skill__"


class _Session:
    """Wraps the running container subprocess and serializes calls into it."""

    def __init__(self, proc: asyncio.subprocess.Process, name: str):
        self._proc = proc
        self._name = name
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
    """One sandboxed Docker container per skill, pooled for the session lifetime.

    Containers are started lazily on first use and kept alive across turns so
    re-using a skill pays no restart cost. Call reset_all() at the end of each
    user turn to wipe all containers and prevent secrets from leaking between
    turns. The pool is fully torn down by close().
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
        known_skills: Optional[frozenset[str]] = None,
    ):
        self._skills_dir = skills_dir.resolve()
        self._image = image
        self._memory_limit = memory_limit
        self._cpu_limit = cpu_limit
        self._pids_limit = pids_limit
        self._tmpfs_size = tmpfs_size
        self._execution_timeout = execution_timeout
        self._docker_cmd = docker_cmd
        self._known_skills = known_skills

        self._runner_path = (Path(__file__).parent / _RUNNER_FILENAME).resolve()
        if not self._runner_path.is_file():
            raise FileNotFoundError(f"runner script not found: {self._runner_path}")

        self._sessions: dict[str, _Session] = {}
        self._session_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "execute_code"

    @property
    def description(self) -> str:
        return (
            "Execute code in a sandboxed Docker container with no network access. "
            "Use `language` to pick the interpreter: `python` (default) or `bash`. "
            "Each skill gets its own persistent container — Python state (variables, imports) "
            "is preserved across all calls within the same skill and the same turn. "
            "Bash invocations are stateless. The skills directory is mounted read-only at "
            "`/skills`, so skill scripts and references can be loaded directly — e.g. "
            "`exec(open('/skills/<skill-name>/scripts/<file>.py').read())` in Python, "
            "or `cat /skills/<skill-name>/...` in bash. Python uses REPL-style display: "
            "the value of a trailing expression is auto-printed via repr(). "
            "Always pass `skill` with the active skill's name so the correct sandbox is used."
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
                "skill": {
                    "type": "string",
                    "description": (
                        "Name of the skill currently executing this code (e.g. 'unit-converter'). "
                        "The sandbox resets automatically when this value changes, keeping each "
                        "skill's interpreter state isolated from others. Always pass this."
                    ),
                },
            },
            "required": ["code"],
        }

    async def _execute(self, arguments: dict[str, Any]) -> str:
        code = arguments.get("code", "") or ""
        language = (arguments.get("language") or "python").lower()
        skill = arguments.get("skill") or None

        if skill and self._known_skills and skill not in self._known_skills:
            print(f"⚠️ 🐳 execute_code: unknown skill {skill!r} rejected (not in known skills), ignoring skill parameter")
            skill = None

        key = skill or _DEFAULT_SKILL_KEY
        session = await self._get_or_start_session(key)
        try:
            t0 = time.perf_counter()
            payload = await session.execute(code, language, self._execution_timeout)
            print(f"⏱️ 🐳 execute_code ({language}): {(time.perf_counter() - t0) * 1000:.0f} ms")
        except RuntimeError as exc:
            await self._reset_session(key)
            return _ExecutionResult(success=False, error=str(exc)).model_dump_json()

        return _ExecutionResult(**payload).model_dump_json()

    async def _get_or_start_session(self, key: str) -> _Session:
        async with self._session_lock:
            session = self._sessions.get(key)
            if session and session.alive:
                print(f"🐳 resuming DOCKER({session._name}, pid={session._proc.pid})")
            else:
                session = await self._start_session()
                self._sessions[key] = session
            return session

    async def _reset_session(self, key: str) -> None:
        async with self._session_lock:
            session = self._sessions.pop(key, None)
        if session is not None:
            await session.close()

    async def reset_all(self) -> None:
        """Wipe all skill containers. Call after each user turn to prevent
        secrets accumulated during the turn from leaking into the next one."""
        async with self._session_lock:
            sessions = list(self._sessions.items())
            self._sessions.clear()
        if sessions:
            t0 = time.perf_counter()
            for _, session in sessions:
                await session.close()
            print(f"🧹 🐳 reset_all: wiped {len(sessions)} container(s) in {(time.perf_counter() - t0) * 1000:.0f} ms")

    async def _start_session(self) -> _Session:
        container_name = f"agent_demo-runner-{secrets.token_hex(8)}"
        print(f"🐳 starting a new DOCKER({container_name})...")
        t0 = time.perf_counter()
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
        print(f"⏱️ 🐳 container start: {(time.perf_counter() - t0) * 1000:.0f} ms")
        return _Session(proc, container_name)

    async def close(self) -> None:
        await self.reset_all()
