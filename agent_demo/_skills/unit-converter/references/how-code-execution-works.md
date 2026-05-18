# How `execute_code` Works

`execute_code` runs Python in an isolated Docker container with **no network access**. Each `session_id` maps to one long-running container; variables and imports persist within a session.

---

## Parameters

| Name          | Type   | Required | Purpose                                                                                                                                                                  |
|---------------|--------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `code`        | string | yes      | Python source to execute. Multi-line is fine.                                                                                                                            |
| `session_id`  | string | no       | Empty string (or omitted) starts a new session. Reuse the value returned in `session_info` for follow-up calls so state persists.                                        |
| `script_path` | string | no       | Path under the skills root (e.g. `/unit-converter/scripts/convert.py`). When set, the file is read on the host and **prepended** to `code` as `<file>\n\n<code>` before being sent to the container. Saves tokens — you don't need to copy the script into the request. |

---

## Session lifecycle

1. **Create** — first call with `session_id = ""` spawns a new container and returns a 16-hex-char id:

   ```json
   {
     "success": true,
     "output": ["..."],
     "session_info": {
       "session_id": "ab12cd34ef56...",
       "instructions": "Reuse this session_id for subsequent calls in this conversation. Variables and imports persist within the session."
     }
   }
   ```

2. **Reuse** — pass that id on every follow-up call in the same conversation. Imports and variables defined on previous calls are still in scope.

3. **End** — the container is torn down when the agent_demo process exits, on per-call timeout, or if the container dies. Sending a stale id returns a `SessionExpiredError`; silently restart from step 1.

---

## Response shape

```json
{
  "success": true,
  "output": ["stdout chunk\n", "stderr chunk\n"],
  "result": null,
  "error": null,
  "traceback": [],
  "files": [],
  "session_info": null
}
```

- `success` — `false` if user code raised.
- `output` — captured `stdout` then `stderr`, each as a single string.
- `error` — `"<ExceptionType>: <message>"` when `success=false`.
- `traceback` — formatted traceback lines when `success=false`.
- `session_info` — populated only on the call that **created** the session.
- `result` / `files` — reserved; currently always `null` / `[]`.

---

## Sandbox guarantees

The container is launched with:

- `--network=none` — no inbound or outbound networking. `pip install`, HTTP, DNS all fail.
- `--cap-drop=ALL`, `--security-opt=no-new-privileges` — minimal Linux capabilities, no setuid escalation.
- `--read-only` rootfs with a `tmpfs` at `/tmp` — file writes outside `/tmp` fail.
- `--memory`, `--cpus`, `--pids-limit` — resource caps, fork-bomb protection.
- `PYTHONDONTWRITEBYTECODE=1` — Python won't try to write `.pyc` files on the read-only fs.

Only the standard library and whatever's baked into the image (default: `python:3.11-slim`) is available. Adding packages requires building a custom image with them preinstalled.

---

## Error cases the model should expect

| Situation                  | Surface                                                                          | Recovery                                              |
|----------------------------|----------------------------------------------------------------------------------|-------------------------------------------------------|
| User code raises           | `success=false`, `error`, `traceback` populated; session stays alive             | Read the error, fix the code, retry in same session.  |
| Per-call timeout exceeded  | `success=false`, `error` mentions timeout; session is killed                     | Start a new session and reload the script.            |
| Stale `session_id`         | `success=false`, `error` starts with `SessionExpiredError:`                      | Silently restart from step 1 of the skill workflow.   |
| Container exits unexpectedly | `success=false`, `error` mentions container/runner exit; session is removed     | Start a new session.                                  |

---

## Protocol (informational)

The host and the in-container runner exchange one JSON object per line over stdin/stdout. The host writes `{"code": "..."}\n`; the runner `exec`s it against a persistent globals dict and writes the response object back. This is internal — skills only see the tool call and its response.
