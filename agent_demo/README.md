# agent_demo

A teaching/demo implementation of **Anthropic-style skills** wired to the OpenAI Chat Completions API (GPT) or Anthropic Messages API (Claude). The agent decides when to activate a skill, lazy-loads its files via a `read_skill` tool, and runs code inside a network-isolated Docker sandbox via `execute_code`.

The key idea on display is **progressive disclosure**: only skill *frontmatter* is loaded into the system prompt up front; the body and supporting files are fetched on demand. That keeps the context window small while many skills remain available.

![](/agent_demo/_images/custom-skills-impl.png)

## Quick start

```bash
pip install -r requirements.txt      # from the repo root
# Add your API key to a .env file in the repo root:
#   ANTHROPIC_API_KEY=sk-ant-...   (Claude — recommended)
#   OPENAI_API_KEY=sk-proj-...     (GPT)
# The Docker daemon must be running (image pinned to python@sha256:…,
# auto-pulled on first use; the container runs with --network=none).
python -m agent_demo.app_claude   # Claude (recommended)
python -m agent_demo.app          # GPT
```

Type a request at the `➡️:` prompt; `exit` to quit. Models are hard-coded in `app_claude.py` (`claude-sonnet-4-6`) and `app.py` (`gpt-5.2`).

## How the agent runs

`agent_demo/agent.py` :: `Agent.chat_completion` is a small recursive loop:

1. Send `messages` + tool schemas to the OpenAI Chat Completions endpoint.
2. If the response has `tool_calls`, dispatch each through `_dispatch_tool_calls`:
   - look the tool up by name and call `tool.execute(tool_call_id, args)`,
   - append one `role=tool` message per call with the result content.
3. Recurse with the appended messages until `finish_reason != "tool_calls"`.
4. Return the final assistant message.

Tool errors are caught inside `BaseTool.execute` and surface as a tool-role message that begins with `ERROR during tool call execution:` — the model sees and can react to them rather than crashing the loop.

## Skills

A skill is a self-contained folder under `agent_demo/_skills/<skill-name>/`:

```
unit-converter/
  SKILL.md              # YAML frontmatter + Markdown body
  scripts/convert.py    # optional code
  references/...        # optional supporting docs
```

`models/skill.load_skills(skills_dir)` walks `_skills/`, parses each `SKILL.md`'s frontmatter, and validates strictly:

- `name` must be `[a-z0-9-]`, ≤64 chars, match the directory name (no leading/trailing or consecutive hyphens);
- `description` ≤1024 chars;
- `compatibility` ≤500 chars;
- invalid skills are **skipped with a warning, not raised**.

`prompt_utils.build_system_prompt` then serializes the validated frontmatter into an `<available_skills>` XML block (`_build_available_skills_xml`) and embeds it in the system prompt along with a short "how to use skills" protocol. **Body content is not loaded up front** — the model must call `read_skill` to fetch it. That is the core token-saving design.

## Tools

Every tool subclasses `tools/base.BaseTool` and implements `_execute` (async) plus `name` / `description` / `parameters` properties. `BaseTool.schema` derives the OpenAI function-tool JSON shape from those automatically.

### `read_skill` — `tools/skills/read_skill_tool.py`

Reads any file under `_skills/` by a path relative to the skills root, e.g. `path="/unit-converter/SKILL.md"` or `path="/unit-converter/scripts/convert.py"`. The agent uses this to pull SKILL bodies, scripts, and references on demand.

### `execute_code` — `tools/container/docker_code_interpreter_tool.py`

Runs Python or bash inside a sandboxed Docker container with no network access.

**Parameters**

| name       | type   | required | meaning                                                                                      |
|------------|--------|----------|----------------------------------------------------------------------------------------------|
| `code`     | string | yes      | source to execute (multi-line ok)                                                            |
| `language` | string | no       | `"python"` (default) or `"bash"`                                                             |
| `skill`    | string | no       | name of the active skill (e.g. `"unit-converter"`). Routes the call to that skill's dedicated container. Unknown values are silently ignored. Always pass this. |

**Container lifecycle**

- **One container per skill**, started lazily on first use and kept alive for the current user turn.
- **No reset on skill switch** — switching skills routes to a different container in the pool; both stay warm.
- **Turn-boundary wipe** — `app.main` calls `reset_all()` after every assistant reply, destroying all containers. Prevents secrets from leaking into subsequent turns.
- **Subagent isolation** — each `DockerCodeInterpreterTool` instance owns its own `_sessions` pool; a subagent that creates a new instance gets an empty pool with no shared state.
- On per-call timeout (default 30s) or container crash, that skill's container is removed from the pool; the next call restarts it.
- `tool.close()` (called from `app.main`'s `finally`) calls `reset_all()` to drain the pool on exit.

**Sandbox flags** (set in `_start_session`):

- `--network=none` — no inbound or outbound networking; `pip install`, HTTP, DNS all fail.
- `--cap-drop=ALL`, `--security-opt=no-new-privileges` — minimal Linux capabilities, no setuid escalation.
- `--read-only` rootfs plus a `tmpfs` at `/tmp` (writable scratch with size cap).
- `--memory`, `--cpus`, `--pids-limit` — resource caps, fork-bomb protection.
- `-v <runner>:/runner.py:ro` — the in-container kernel.
- `-v <skills_dir>:/skills:ro` — **the skills directory is bind-mounted read-only**, so executed code can read any skill file directly (e.g. `open("/skills/unit-converter/scripts/convert.py")`).

**State semantics**

- **Python state (variables, imports) persists across all calls within the same turn** — the runner keeps one shared globals dict per container; state is wiped between turns by `reset_all()`.
- **Bash invocations are stateless** — each runs in a fresh `bash -c` subshell.

**Python is Jupyter-style**: a trailing bare expression is auto-displayed via `repr()` (when its value is not `None`), so the model does not need to wrap every result in `print(...)`.

### In-container runner — `tools/container/_runner.py`

A tiny loop that runs inside the sandbox. Reads one JSON request per line on stdin, dispatches to either:

- **Python** — AST splits off any trailing expression, the rest is `exec`'d in a persistent globals dict, and the trailing expression is `eval`'d and auto-displayed via `repr()`;
- **bash** — `subprocess.run(["bash", "-c", code])`, stateless;

then writes a single JSON response line on stdout. Catches `BaseException` so user `sys.exit()` etc. don't kill the kernel.

Host ↔ runner protocol:

```
host   → runner : {"code": "<source>", "language": "python" | "bash"}
runner → host   : {"success": bool, "output": [str, ...], "result": null,
                   "error": null|str, "traceback": [str, ...], "files": []}
```

Known limitation: background threads in user code that print after `exec()` returns can corrupt the framing — keep skill scripts synchronous.

## Layout

```
agent_demo/
  app.py                                # entry point (GPT): REPL, wiring
  app_claude.py                         # entry point (Claude): REPL, wiring
  agent.py                              # recursive tool-using chat loop (OpenAI Responses API)
  agent_claude.py                       # recursive tool-using chat loop (Anthropic Messages API)
  prompt_utils.py                       # system prompt + <available_skills> XML
  models/
    skill.py                            # SkillMetadata + load_skills (validation)
    message.py  role.py  conversation.py
  tools/
    base.py                             # BaseTool + schema derivation
    skills/read_skill_tool.py           # read_skill
    container/
      docker_code_interpreter_tool.py   # execute_code (host side)
      _runner.py                        # in-container kernel
      _response.py                      # pydantic response shape
  _skills/
    unit-converter/                     # canonical example skill
```

## Conventions

- **Async-first.** Tools, the agent loop, and message dispatch are all `async`. New tools subclass `BaseTool` and implement `_execute`.
- **Messages** are dataclasses (`models/message.py`) serialized via `to_dict()` — keep that in sync with the OpenAI Chat Completions message shape (`role`, `content`, `tool_call_id`, `name`, `tool_calls`).
- **Internal imports** use the `agent_demo.*` prefix.

## Adding a new skill

1. Create `agent_demo/_skills/<name>/SKILL.md` with frontmatter (`name` must equal `<name>`, plus a `description` of what the skill does and when to use it).
2. Add any `scripts/` or `references/` files the skill needs.
3. Restart the agent — `load_skills` picks the new folder up automatically. From inside `execute_code`, the same files are visible at `/skills/<name>/...`.

See `_skills/unit-converter/` for a worked example: SKILL.md describes the function contract, `references/examples.md` documents NL→argument mapping and the full unit-alias table, and `scripts/convert.py` is the implementation.
