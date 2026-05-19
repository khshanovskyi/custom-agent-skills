# How `execute_code` Works

`execute_code` runs code in an isolated Docker container with **no network access**. A single long-running container per agent process is started on first use; Python state (variables, imports) persists across calls. Bash invocations are stateless.

---

## Parameters

| Name       | Type   | Required | Purpose                                                                                                                   |
|------------|--------|----------|---------------------------------------------------------------------------------------------------------------------------|
| `code`     | string | yes      | Source to execute. May be multi-line.                                                                                     |
| `language` | string | no       | `"python"` (default) or `"bash"`. Python state persists across calls; each `bash` call runs in a fresh `bash -c` subshell. |

---

## The `/skills` mount

The skills directory is bind-mounted **read-only** at `/skills` inside the sandbox. Every file under the host skills root is reachable from `code` without copying it into the request:

```python
# Load a skill script directly from the mount.
exec(open("/skills/unit-converter/scripts/convert.py").read())
result, category = convert_units(100, "km", "miles")
result, category
```

```bash
# Same idea from bash.
ls /skills/unit-converter/
cat /skills/unit-converter/scripts/convert.py | head
```

---

## Python REPL semantics

Python execution is Jupyter-style: a trailing bare expression is auto-displayed via `repr()` (when its value is not `None`). You do **not** need to wrap every result in `print(...)`.

```python
1 + 2            # → "3" appears in output
x = [1, 2, 3]    # nothing displayed (assignment)
x                # → "[1, 2, 3]" appears in output
print("hello")   # → "hello" appears in output (print returns None, no double-display)
```

State carries over between calls in the same conversation, so a script loaded on one call can be invoked on the next:

```python
# Call 1
exec(open("/skills/unit-converter/scripts/convert.py").read())

# Call 2 (later)
convert_units(98.6, "fahrenheit", "celsius")
```

---

## Response shape

```json
{
  "success": true,
  "output": ["stdout chunk\n", "stderr chunk\n"],
  "result": null,
  "error": null,
  "traceback": [],
  "files": []
}
```

- `success` — `false` if user code raised (Python) or `bash` exited non-zero.
- `output` — captured stdout then stderr, each as a single string.
- `error` — `"<ExceptionType>: <message>"` (Python) or `"bash exited with status <n>"` when `success=false`.
- `traceback` — formatted Python traceback lines when `success=false`.
- `result` / `files` — reserved; currently always `null` / `[]`.

---

## Sandbox guarantees

The container is launched with:

- `--network=none` — no inbound or outbound networking. `pip install`, HTTP, DNS all fail.
- `--cap-drop=ALL`, `--security-opt=no-new-privileges` — minimal Linux capabilities, no setuid escalation.
- `--read-only` rootfs with a `tmpfs` at `/tmp` — file writes outside `/tmp` fail.
- `--memory`, `--cpus`, `--pids-limit` — resource caps, fork-bomb protection.
- `-v <skills_dir>:/skills:ro` — skills directory mounted read-only.
- `PYTHONDONTWRITEBYTECODE=1` — Python won't try to write `.pyc` files on the read-only fs.

Only the standard library and whatever is baked into the image (default: `python:3.11-slim`) is available. Adding packages requires building a custom image with them preinstalled.

---

## Error cases the model should expect

| Situation                    | Surface                                                              | Recovery                                                              |
|------------------------------|----------------------------------------------------------------------|-----------------------------------------------------------------------|
| User code raises             | `success=false`, `error`, `traceback` populated; sandbox stays alive | Read the error, fix the code, retry — state is unchanged.             |
| Per-call timeout exceeded    | `success=false`, `error` mentions timeout; sandbox is killed         | Retry — the next call starts a fresh container; reload any scripts.   |
| Container exits unexpectedly | `success=false`, `error` mentions container/runner exit              | Retry — the next call starts a fresh container; reload any scripts.   |

---

## Protocol (informational)

The host and the in-container runner exchange one JSON object per line over stdin/stdout:

- host → runner: `{"code": "...", "language": "python"|"bash"}`
- runner → host: the response object shown above

This is internal — skills only see the tool call and its response.
