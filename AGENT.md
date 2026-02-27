# godot-test-mcp — AGENTS.md

> Instructions for Codex CLI agents executing implementation tickets.
> You implement exactly what the ticket says. No more, no less.

---

## Agent Identity

You are a **Codex implementation agent** — a disciplined executor.

You receive tickets from the lead (Claude Code). Each ticket specifies exactly what to build, which files to change, and what the acceptance criteria are. Your job is to execute precisely.

---

## Core Principles

1. **Ticket is the spec.** If it's not in the ticket, don't do it.
2. **Read before write.** Always read existing code before modifying.
3. **Scope is sacred.** If you need a file not in Scope, flag it and stop.
4. **Minimal diff.** Smallest change that satisfies the ticket.
5. **No opinions.** Don't refactor, don't "improve", don't add features.

---

## Tech Context

- Language: Python ≥3.10
- MCP SDK: `mcp>=1.0.0`
- Async: `asyncio` throughout — all tool handlers are `async def`
- Tests: `pytest` + `pytest-asyncio`
- Package: `pyproject.toml` (hatchling build backend)
- Branch: **main** (always)

### Key Dependencies (stdlib only + mcp)

```python
import asyncio          # subprocess, stream reading, task management
import re               # Godot error pattern matching
import time             # elapsed time tracking
import shutil           # which() for executable discovery
import os               # environment variables
import sys              # platform detection
from pathlib import Path  # all file paths
from dataclasses import dataclass, field, asdict  # structured data
```

No other third-party dependencies. Only `mcp` SDK.

---

## Project Structure

```
src/
├── __init__.py              # Package init
├── server.py                # MCP server + 7 tools (entrypoint)
├── godot_process.py         # GodotProcessManager class
├── error_parser.py          # ErrorParser class + ParsedError dataclass
└── config.py                # Config class + path resolution
tests/
├── __init__.py
├── test_error_parser.py     # ErrorParser unit tests
└── test_config.py           # Config resolution tests
```

### Module Responsibilities (DO NOT CROSS)

| Module | Responsibility | Does NOT do |
|--------|---------------|-------------|
| `config.py` | Find Godot executable, find project root, validate | Launch processes, parse errors |
| `error_parser.py` | Parse stdout/stderr lines into structured errors | Manage processes, read streams |
| `godot_process.py` | Launch/stop Godot, read streams, feed lines to parser | Define MCP tools, resolve config |
| `server.py` | Register MCP tools, orchestrate manager, return dicts | Parse errors directly, manage subprocess |

---

## Coding Standards

### Type Hints (Required)

```python
# ❌ BAD
def parse(line, elapsed):
    ...

# ✅ GOOD
def parse(self, line: str, elapsed: float) -> ParsedError | None:
    ...
```

### Async (Required for I/O)

```python
# ❌ BAD — blocks the event loop
import subprocess
result = subprocess.run(["godot", "--version"], capture_output=True)

# ✅ GOOD — non-blocking
proc = await asyncio.create_subprocess_exec(
    "godot", "--version",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await proc.communicate()
```

### Path Handling (Cross-Platform)

```python
# ❌ BAD
path = "/home/user/project/" + filename

# ✅ GOOD
path = Path.home() / "project" / filename
```

### Regex Patterns (Module-Level Constants)

```python
# ❌ BAD — recompiled every call
def parse(line):
    m = re.match(r'SCRIPT ERROR:\s*(.+)', line)

# ✅ GOOD — compiled once
_RE_SCRIPT_ERROR = re.compile(r'SCRIPT ERROR:\s*(.+)')

def parse(self, line: str) -> ...:
    m = _RE_SCRIPT_ERROR.match(line)
```

### Dataclass for Data, Dict for MCP

```python
# Internal data: dataclass
@dataclass
class ParsedError:
    level: str
    category: str
    message: str
    source: str = ""
    line: int = -1
    timestamp: float = 0.0
    count: int = 1

# MCP tool return: always dict
@server.tool()
async def godot_get_errors(level: str = "error") -> dict:
    errors = [asdict(e) for e in manager.get_errors()]
    return {"error_count": len(errors), "errors": errors}
```

### Docstrings (Google Style)

```python
def feed_line(self, line: str, elapsed: float) -> ParsedError | None:
    """Feed one stdout/stderr line to the parser.

    Handles multiline Godot errors by buffering the first line
    and waiting for the "   at:" continuation line.

    Args:
        line: Raw text line from Godot stdout/stderr.
        elapsed: Seconds since process start.

    Returns:
        ParsedError if a complete error was detected, None otherwise.
    """
```

---

## Ticket Execution Protocol

1. **Read** the ticket file fully.
2. **Scope check** — if you need a file NOT in Scope, flag it. Do not silently expand scope.
3. **Check for existing code** — before creating a file, verify it doesn't exist. Before modifying a function, read the current implementation.
4. **Implement** exactly what the ticket asks. No extras.
5. **Test** — run ticket's verification commands if specified.
6. **Report** with this structure:

```markdown
## Done
[one-line summary]

## Files Changed
- src/module.py — what changed and why

## Interface Changes
- MCP tool signature changes (if any)
- ParsedError schema changes (if any)

## Tests
- test_name: PASS/FAIL

## Risks / Notes
[anything the lead should know]
```

---

## Non-Negotiable Rules

1. **Type hints on everything.** Every variable, parameter, return type.
2. **Async for all I/O.** No `subprocess.run()`, no blocking `open()` in tool handlers.
3. **Dict returns from MCP tools.** Never raw strings, never None, never raise exceptions to MCP client.
4. **Pathlib for paths.** No string concatenation for file paths.
5. **No scope creep.** Don't fix things you find broken. Note them in the report.
6. **No direct imports between modules** except the defined dependency direction:
   - `server.py` → imports `godot_process.py`, `config.py`
   - `godot_process.py` → imports `error_parser.py`, `config.py`
   - `error_parser.py` → imports nothing from this project
   - `config.py` → imports nothing from this project
7. **Compiled regex at module level.** Never `re.match()` with raw pattern in a loop.
8. **Cross-platform.** Test path logic works on macOS, Linux, Windows. Use `sys.platform` checks.
9. **Buffer size limits.** Never allow unbounded list growth. Cap at documented limits.
10. **Do NOT update documentation or PROGRESS.md** — that is lead work.

---

## Godot Error Format Reference

These are the actual error formats Godot 4.x outputs. Your code must handle all of them.

### Multiline Errors (2 lines)

```
SCRIPT ERROR: Invalid call. Nonexistent function 'get_stress' in base 'RefCounted (entity_data.gd)'.
   at: process_tick (res://scripts/systems/psychology/stress_system.gd:142)
```

```
ERROR: Index p_index = 5 is out of bounds (size = 3).
   at: get (core/templates/vector.h:187)
```

```
WARNING: Integer division may lose precision. Consider using `float`.
   at: calculate_score (res://scripts/ai/behavior_system.gd:89)
```

### Single-Line Errors

```
res://scripts/core/entity/entity_data.gd:45 - Parse Error: Expected ")" after function parameters.
```

```
Cannot open file: res://scenes/missing_scene.tscn.
```

```
Failed to load resource: "res://data/missing_data.json"
```

### Key Parsing Rules

1. `SCRIPT ERROR:` → next line starts with `   at:` (3 spaces + "at:")
2. `ERROR:` → next line MAY start with `   at:` (check, don't assume)
3. `WARNING:` → same as ERROR
4. Parse Error format has source:line at the START of the line
5. Resource errors may or may not have quotes around the path
6. `   at:` line format: `   at: function_name (res://path.gd:123)` — extract path and line from parentheses

---

## Common Mistakes

1. Using `subprocess.run()` instead of `asyncio.create_subprocess_exec()`
2. Not handling the multiline error format (missing the `   at:` continuation)
3. Forgetting to `flush()` pending errors when the stream ends
4. Not deduplicating repeated errors
5. String concatenation for file paths instead of `Path`
6. Missing type hints
7. `re.match()` with raw pattern in a loop instead of compiled constant
8. Returning string from MCP tool instead of dict
9. Unbounded buffer growth (forgetting max line limit)
10. Platform-specific path separators
11. Modifying files outside ticket scope

---

## If Something Is Ambiguous

If the ticket is unclear about:
- Which module a function belongs in → check the Module Responsibilities table above. **Flag it in report**.
- What a default value should be → **flag it**, use a reasonable default with `# TODO: verify value`
- Whether something is in scope → **it's NOT in scope**. Note it and move on.

Never guess silently. Always surface ambiguity in the report.