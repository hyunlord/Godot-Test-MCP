# PROGRESS.md — Append-only Work Log

## Phase 3: Self-Discovery Tools + Zero-Touch Injection — 2026-02-28

### Context
Add 3 new MCP tools (godot_inspect, godot_run_script, godot_batch) for autonomous game exploration, improve all tool descriptions, and enhance WS connection resilience.

### Tickets
| Ticket | Title | Action | Dispatch Tool | Reason |
|--------|-------|--------|---------------|--------|
| t-301 | Harness: inspect + inspect_object commands | 🟢 DISPATCH | Task(executor) | standalone GDScript additions |
| t-302 | Harness: run_script command + blocklist | 🟢 DISPATCH | Task(executor) | standalone GDScript additions |
| t-303 | Harness: batch command | 🟢 DISPATCH | Task(executor) | standalone GDScript additions |
| t-304 | Harness: wire 3 commands into _dispatch() | 🟢 DISPATCH | Task(executor) | included with t-301..303 |
| t-305 | Server: 3 new MCP tools + handler functions | 🟢 DISPATCH | Task(executor) | tool defs + handlers |
| t-306 | Server: rewrite ALL tool descriptions | 🟢 DISPATCH | Task(executor) | included with t-305 |
| t-307 | WS client: two-phase connect fallback | ⚪ SKIP | — | already implemented in prior commit |
| t-308 | Tests: test_harness_commands.py | 🔴 DIRECT | — | integration wiring, schema validation |
| t-309 | CLAUDE.md: update architecture | 🟢 DISPATCH | Task(executor) | standalone doc update |

### Dispatch ratio: 6/8 = 75% ✅ (target: ≥60%)

### Results
- Tests: 82/82 PASS
- Dispatch ratio: 6/8 = 75%
- Files changed: 5 (4 modified, 1 created)

### Changes
| File | Lines | Description |
|------|-------|-------------|
| `src/harness/test_harness.gd` | +180 | `_cmd_inspect`, `_inspect_object`, `_cmd_run_script`, `_cmd_batch`, `_BLOCKED_PATTERNS`, dispatch wiring |
| `src/server.py` | +295/-35 | 3 new tool defs + handlers + dispatch routes, all descriptions rewritten with examples |
| `src/ws_client.py` | +26/-4 | Two-phase connect fallback (already existed, minor update) |
| `tests/test_harness_commands.py` | +165 (new) | Tool registration, description quality, handler routing, security blocklist, command structure |
| `CLAUDE.md` | +27 | Phase 3 in vision, directory structure, tool list, injector strategy |

### Not Changed
- `src/injector.py` — override.cfg approach already implemented in prior commit
- `tests/test_injector.py` — already covers override.cfg approach
- `pyproject.toml` — version already at 0.3.0

### Risks
- `godot_run_script` security blocklist is pattern-based, not a sandbox. Sufficient for dev tooling.
- `_inspect_object` depth is capped at 3 to prevent infinite recursion on deep scene trees.
- GDScript commands cannot be unit-tested from Python without Godot runtime; tests verify structure and routing.
