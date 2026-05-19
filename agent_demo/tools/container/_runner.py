"""In-container Python + bash kernel.

Runs inside the sandboxed Docker container. Reads JSON-line code requests from
stdin, executes them, and writes JSON-line results back to stdout.

Protocol (one JSON object per line in each direction):
    host -> runner: {"code": "<source>", "language": "python" | "bash"}
    runner -> host: {"success": bool, "output": [str, ...], "result": null,
                     "error": null|str, "traceback": [str, ...], "files": []}

Python execution is Jupyter-style: a persistent globals dict is reused across
requests, and if the last statement is a bare expression, its value (when not
None) is auto-displayed via repr() — matching standard REPL behavior so the
model does not have to wrap every result in print().

Bash execution is stateless: each request runs in a fresh `bash -c` subshell.

The runner only writes a single JSON line per request to stdout. Diagnostics
go to stderr so they cannot corrupt the response stream.
"""
import ast
import contextlib
import io
import json
import subprocess
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
    }


def _run_python(code: str, globs: dict) -> dict:
    result = _empty_result()
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()

    try:
        tree = ast.parse(code, mode="exec")
        last_expr = None
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            last_expr = tree.body.pop()

        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            if tree.body:
                exec(compile(tree, "<session>", "exec"), globs)
            if last_expr is not None:
                value = eval(
                    compile(ast.Expression(body=last_expr.value), "<session>", "eval"),
                    globs,
                )
                if value is not None:
                    print(repr(value))
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
    return result


def _run_bash(code: str) -> dict:
    result = _empty_result()
    try:
        proc = subprocess.run(
            ["bash", "-c", code],
            capture_output=True,
            text=True,
        )
        if proc.stdout:
            result["output"].append(proc.stdout)
        if proc.stderr:
            result["output"].append(proc.stderr)
        if proc.returncode != 0:
            result["success"] = False
            result["error"] = f"bash exited with status {proc.returncode}"
    except BaseException as exc:
        result["success"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc().splitlines()
    return result


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
        language = (request.get("language") or "python").lower()

        if language == "python":
            _emit(_run_python(code, globs))
        elif language == "bash":
            _emit(_run_bash(code))
        else:
            _emit({
                **_empty_result(),
                "success": False,
                "error": f"unsupported language: {language!r} (supported: python, bash)",
            })


if __name__ == "__main__":
    main()
