"""In-container Python kernel.

Runs inside the sandboxed Docker container. Reads JSON-line code requests from
stdin, executes them in a persistent globals namespace, and writes JSON-line
results back to stdout. State (variables, imports) persists across requests
within a single container lifetime.

Protocol (one JSON object per line in each direction):
    host -> runner: {"code": "<python source>"}
    runner -> host: {"success": bool, "output": [str, ...], "result": null,
                     "error": null|str, "traceback": [str, ...],
                     "files": [], "session_info": null}

The runner only writes a single JSON line per request to stdout. Diagnostics
go to stderr so they cannot corrupt the response stream.

Limitation: background threads/tasks spawned by user code that print after
exec() returns will write to the real stdout and break framing. The skills
in this repo are synchronous, so this is acceptable for the demo.
"""
import contextlib
import io
import json
import sys
import traceback


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _empty_result() -> dict:
    return {
        "success": True,
        "output": [],
        "result": None,
        "error": None,
        "traceback": [],
        "files": [],
        "session_info": None,
    }


def main() -> None:
    globs: dict = {"__name__": "__main__"}

    while True:
        line = sys.stdin.readline()
        if not line:
            return

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _emit({**_empty_result(), "success": False, "error": f"protocol error: {exc}"})
            continue

        code = request.get("code", "") or ""
        result = _empty_result()
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            compiled = compile(code, "<session>", "exec")
            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exec(compiled, globs)
        except BaseException as exc:
            result["success"] = False
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["traceback"] = traceback.format_exc().splitlines()

        stdout_value = stdout_buf.getvalue()
        stderr_value = stderr_buf.getvalue()
        if stdout_value:
            result["output"].append(stdout_value)
        if stderr_value:
            result["output"].append(stderr_value)

        _emit(result)


if __name__ == "__main__":
    main()
