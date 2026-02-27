# godot-test-mcp

MCP server for automated Godot 4 game testing.
Launch games, capture errors, verify changes — all from Claude Code or any MCP client.

## Features (Phase 1)

- **Launch & Stop**: Run Godot projects in headless or windowed mode
- **Error Capture**: Parse and categorize GDScript errors, parse errors, resource failures
- **One-Shot Verify**: `godot_run_and_check` — launch, run N seconds, report PASS/FAIL
- **Headless Import**: Quick parse-check without running the game

## Quick Start

1. **Clone:**
   ```bash
   git clone https://github.com/hyunlord/godot-test-mcp.git
   ```

2. **Install:**
   ```bash
   cd godot-test-mcp
   pip install -e .
   ```

3. **Add to your Godot project's `.mcp.json`:**
   ```json
   {
     "mcpServers": {
       "godot-test": {
         "command": "python3",
         "args": ["/path/to/godot-test-mcp/src/server.py"],
         "env": {
           "GODOT_PROJECT_PATH": ".",
           "GODOT_PATH": ""
         }
       }
     }
   }
   ```

4. **In Claude Code:**
   ```
   godot_run_and_check(seconds=15)
   ```

## Tools

| Tool | Description |
|------|-------------|
| `godot_launch` | Start Godot (headless/windowed/editor) |
| `godot_stop` | Stop running Godot process |
| `godot_get_errors` | Get parsed errors/warnings |
| `godot_get_output` | Get raw stdout/stderr |
| `godot_run_and_check` | Launch → run N sec → collect errors → PASS/FAIL |
| `godot_headless_import` | Quick --headless --quit parse check |
| `godot_get_status` | Check if Godot is running/stopped/crashed |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GODOT_PATH` | Path to Godot executable (auto-detected if empty) |
| `GODOT_PROJECT_PATH` | Path to Godot project root (auto-detected if empty) |

### Godot Auto-Detection

If `GODOT_PATH` is not set, the server searches in order:
1. macOS: `/Applications/Godot.app/Contents/MacOS/Godot`, `~/Applications/...`
2. Linux: `/usr/bin/godot`, snap/flatpak paths
3. Windows: `C:\Godot\Godot.exe`, `%LOCALAPPDATA%\Godot\...`
4. `PATH` lookup via `which godot`

### Project Auto-Detection

If `GODOT_PROJECT_PATH` is not set, the server searches for `project.godot` starting from the current directory and walking up to 5 parent directories.

## Roadmap

- **Phase 1**: Launch + error capture (current)
- **Phase 2**: Tick control + entity state query (WebSocket)
- **Phase 3**: Cheat commands + assertions
- **Phase 4**: Rust/GPU profiling
- **Phase 5**: CI/CD integration

## License

MIT
