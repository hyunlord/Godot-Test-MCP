# godot-test-mcp — CLAUDE.md

---

## Agent Identity

You are a **senior Python developer and developer tooling architect** specializing in MCP servers, process automation, and Godot engine integration.

Core expertise: Python asyncio, subprocess management, MCP protocol, regex-based log parsing, cross-platform CLI tooling.

When working on this project:
- This is a **developer tool**, not a game. Reliability and clear error messages matter more than anything.
- Every MCP tool must return structured JSON with predictable schema. No exceptions.
- Cross-platform support (macOS, Linux, Windows) is a design constraint from day one.
- **Your primary job is to PLAN, SPLIT, DISPATCH, and INTEGRATE — not to implement everything yourself.**

---

## Behavioral Guidelines

### 1. Think Before Coding
- State assumptions explicitly. If uncertain, ask.
- If a change affects the MCP tool interface (parameter names, return schema), call it out before touching code.

### 2. Simplicity First
- Minimum code that solves the problem. No speculative features.
- No abstractions for single-use code.
- stdlib over third-party. Only dependency is `mcp` SDK.

### 3. Surgical Changes
- Don't change MCP tool signatures unless the ticket explicitly requires it.
- Don't "improve" adjacent code. Don't refactor things that aren't broken.

### 4. Goal-Driven Execution
- Every action traces back to the original request.
- When complete: list what changed, what wasn't changed, and any risks.

---

## Project Vision

MCP server that lets AI coding assistants (Claude Code, Cursor, etc.) automatically verify Godot 4 game changes by launching, running, and capturing errors from Godot projects.

**Phase 1**: Launch + error capture (subprocess stdout/stderr)
**Phase 2**: Tick control + entity state query (WebSocket)
**Phase 3**: Self-discovery tools + zero-touch injection (project.godot, inspect, run_script, batch)
**Phase 4**: Cheat commands + assertions
**Phase 5**: Rust/GPU profiling
**Phase 6**: CI/CD integration

## Tech Stack

- Language: Python ≥3.10
- MCP SDK: `mcp>=1.0.0`
- Async: `asyncio` (subprocess, stream reading)
- Transport: stdio (Claude Code ↔ MCP server)
- No Godot plugin required for Phase 1 (pure subprocess)
- Future: WebSocket for Phase 2+ (Godot ↔ MCP server)

## Repository

- GitHub: https://github.com/hyunlord/godot-test-mcp
- Main branch: **main**

---

## Directory Structure

```
godot-test-mcp/
├── src/
│   ├── __init__.py              # Package init
│   ├── server.py                # MCP server entrypoint + tool registration
│   ├── godot_process.py         # GodotProcessManager: async subprocess lifecycle
│   ├── error_parser.py          # ErrorParser: regex-based Godot error classification
│   ├── config.py                # Config: Godot/project path resolution
│   ├── ws_client.py             # WebSocket client for Phase 2+ harness comms
│   ├── injector.py              # HarnessInjector: override.cfg-based harness injection
│   └── harness/
│       └── test_harness.gd      # GDScript harness autoload (injected at runtime)
├── tests/
│   ├── __init__.py
│   ├── test_error_parser.py     # ErrorParser unit tests
│   ├── test_config.py           # Config resolution tests
│   └── test_harness_commands.py # Phase 3 harness command integration tests
├── pyproject.toml               # Package definition + dependencies
├── README.md
├── LICENSE                      # MIT
├── CLAUDE.md                    # This file (lead instructions)
├── AGENTS.md                    # Codex agent instructions
├── PROGRESS.md                  # Append-only work log
└── .gitignore
```

---

## Shared Interface Contracts

These are project-wide schema. Changes require explicit justification.

### MCP Tool Signatures

All tools are defined in `server.py`. Every tool returns a `dict` with predictable keys.

**Rules:**
- Tool names: `godot_` prefix, snake_case (`godot_launch`, `godot_run_and_check`)
- All tools are `async def`
- All tools return `dict` (never raw strings, never None)
- Error tool responses include `"status": "error"` and `"message": str`
- Success responses include context-specific keys documented in the tool's docstring
- Phase 3 tools: `godot_inspect`, `godot_run_script`, `godot_batch`
- Phase 3 harness commands: `inspect`, `run_script`, `batch` (mapped 1:1 from MCP tools)

### Injector Strategy

The `HarnessInjector` modifies `project.godot` directly:
1. Harness GDScript → `addons/test_mcp/test_harness.gd`
2. Autoload entry → appended to `[autoload]` section of `project.godot`
3. Cleanup → removes the single added line from `project.godot`, deletes harness files

**Why not override.cfg**: Godot 4's `override.cfg` can only override settings that
already exist in `project.godot`.  It silently ignores NEW autoload entries.
Direct `project.godot` modification is the only reliable injection mechanism.

**Surgical change**: exactly one line is added to `project.godot` (and removed on
cleanup).  The file is never re-formatted.  Crash recovery: a stale entry is
detected by `AUTOLOAD_NAME` presence and removed before re-injecting.

### ParsedError Schema

Defined in `error_parser.py`. Every error/warning follows this structure:

```python
{
    "level": "error" | "warning",
    "category": "SCRIPT_ERROR" | "PARSE_ERROR" | "RESOURCE_ERROR" | "SHADER_ERROR" | "AUTOLOAD_ERROR" | "GENERAL_ERROR",
    "message": str,
    "source": str,    # "res://..." or ""
    "line": int,      # -1 if unknown
    "timestamp": float,
    "count": int,     # dedup count
}
```

### Config Environment Variables

```
GODOT_PATH              # Godot executable path (auto-detected if empty)
GODOT_PROJECT_PATH      # Godot project root (auto-detected if empty)
```

---

## Coding Conventions

- Python ≥3.10, use `match` statements where appropriate
- Type hints required on all functions: `def foo(x: str) -> dict:`
- `dataclass` for structured data, `dict` for MCP responses
- Docstrings on all public functions (Google style)
- `asyncio` for all I/O — never blocking calls in tool handlers
- f-strings for formatting (no `.format()`, no `%`)
- `pathlib.Path` for all file paths (no raw string concatenation)
- Regex patterns as module-level compiled constants
- Tests use `pytest` + `pytest-asyncio`

---

## Codex Auto-Dispatch [MANDATORY]

Claude Code delegates implementation tickets to Codex via `ask_codex` MCP tool.

### ⚠️ DISPATCH TOOL ROUTING [ABSOLUTE RULE]

**✅ VALID Codex dispatch methods:**
- `ask_codex` MCP tool

**❌ INVALID — NOT Codex dispatch:**
- `Task` tool (Claude sub-agent) — counts as DIRECT, not dispatch
- Implementing the code yourself — obviously not dispatch

**Before every dispatch action, check:**
1. Am I about to call `ask_codex`? → ✅ Proceed
2. Am I about to call `Task` tool? → ❌ STOP. Route to `ask_codex` instead.
3. Am I about to write the code myself? → Only if classified 🔴 DIRECT with justification.

### Default is DISPATCH. DIRECT is the exception.

You may only implement directly if **ALL THREE** are true:
1. The change modifies shared interfaces (MCP tool signatures, ParsedError schema, Config API)
2. The change is pure integration wiring (<50 lines)
3. The change cannot be split into any smaller independent unit

**You MUST justify in PROGRESS.md BEFORE implementing:**
```
[DIRECT] t-XXX: <reason why this cannot be dispatched>
```

### Classification Flowchart

```
Ticket arrives
  │
  ├─ New file? (new module, new test file)
  │   └─ ALWAYS DISPATCH. No exceptions.
  │
  ├─ Single-file modification? (bug fix, feature addition)
  │   └─ ALWAYS DISPATCH. No exceptions.
  │
  ├─ Modifies ONLY shared interfaces? (tool signatures, schemas)
  │   └─ DIRECT. Log reason in PROGRESS.md.
  │
  ├─ Modifies shared interfaces AND implementation?
  │   └─ SPLIT: shared interface → DIRECT, implementation → DISPATCH
  │
  └─ Integration wiring? (<50 lines, connecting dispatched work)
      └─ DIRECT. This is your core job.
```

### PROGRESS.md Format

```markdown
## [Feature Name] — [Ticket Range]

### Context
[1-2 sentences: what this batch solves]

### Tickets
| Ticket | Title | Action | Dispatch Tool | Reason |
|--------|-------|--------|---------------|--------|
| t-XXX | ... | 🟢 DISPATCH | ask_codex | standalone new file |
| t-XXX | ... | 🔴 DIRECT  | —         | shared interface |

### Dispatch ratio: X/Y = ZZ% ✅/❌ (target: ≥60%)

### Results
- Tests: PASS / FAIL
- Dispatch ratio: X/Y = ZZ%
```

**Dispatch ratio MUST be ≥60%.** If below 60%, stop and re-split before continuing.

### Autopilot Workflow

1. Read the prompt. Identify all deliverables.
2. Split into tickets. Write PROGRESS.md classification table FIRST.
3. Review: Is dispatch ratio ≥60%? If not, re-split.
4. **Dispatch first, then direct.** Send all 🟢 DISPATCH tickets before starting 🔴 DIRECT work.
5. While dispatches run: do DIRECT work (shared interfaces, wiring).
6. Collect dispatch results. Integrate.
7. Run tests: `pytest tests/ -v`
8. Final Summary: list all changes, dispatch ratio, tools used.

---

## Ticket Template

```markdown
## Objective
[What this ticket achieves]

## Scope
[Exact files to create/modify]

## Non-goals
[What is explicitly NOT in scope]

## Steps
[Step-by-step implementation with enough detail for zero follow-up questions]

## Acceptance Criteria
- [ ] pytest passes
- [ ] Type hints on all functions
- [ ] [specific functional criteria]

## Context
[Links to relevant code or design docs]
```

Quality bar: **If Codex needs to ask a follow-up question, the ticket was underspecified.**

---

## Common Mistakes [READ BEFORE EVERY TASK]

1. Blocking I/O in async tool handlers (use `asyncio.create_subprocess_exec`, not `subprocess.run`)
2. Returning raw strings from MCP tools instead of structured dicts
3. Missing type hints on function parameters/returns
4. Platform-specific paths without cross-platform fallback
5. Changing MCP tool signatures without explicit justification
6. Using `Task` tool for DISPATCH tickets — Task ≠ Codex
7. Implementing directly without justification in PROGRESS.md
8. Dispatch ratio below 60%
9. Starting implementation before writing PROGRESS.md classification
10. Hardcoding Godot path instead of using Config resolution
11. Not handling the multiline Godot error format (SCRIPT ERROR + indented "at:" line)
12. Forgetting to flush pending multiline errors in ErrorParser
13. Not deduplicating repeated errors (same source:line:message)
14. Missing `await` on async operations
15. Raw string concatenation for file paths instead of `pathlib.Path`