"""Inject and cleanup test harness GDScript in target Godot project.

Modifies project.godot directly to register the harness autoload.
override.cfg cannot add NEW autoload entries in Godot 4 — it only overrides
values for autoloads already declared in project.godot.  Direct modification
is therefore the only reliable injection mechanism.

Modification is surgical: exactly one line is appended inside the existing
[autoload] section (or a new section is created if none exists).  Cleanup
removes that exact line.  project.godot is never re-formatted or rewritten
beyond the single-line addition/removal.
"""

from __future__ import annotations

import shutil
from pathlib import Path


# Harness destination inside addons/ (visible to Godot's resource system)
HARNESS_DIR = "addons/test_mcp"
HARNESS_FILENAME = "test_harness.gd"
AUTOLOAD_NAME = "GodotTestMcpHarness"

# Full autoload entry written to project.godot — also serves as the
# crash-recovery marker (presence of AUTOLOAD_NAME is sufficient to detect
# a stale injection from a previous run).
_AUTOLOAD_ENTRY = f'{AUTOLOAD_NAME}="*res://{HARNESS_DIR}/{HARNESS_FILENAME}"'


class HarnessInjector:
    """Manages injection and cleanup of test harness in a Godot project.

    Strategy:
      1. Copy test_harness.gd to addons/test_mcp/
      2. Append one autoload line to project.godot's [autoload] section
         (creates the section if absent)
      3. On cleanup: remove that line from project.godot, delete harness files

    Crash recovery: a new HarnessInjector instance detects the stale entry
    via AUTOLOAD_NAME in project.godot and removes it on cleanup().
    """

    def __init__(self, project_path: str) -> None:
        self._project = Path(project_path)
        self._harness_dir = self._project / HARNESS_DIR
        self._harness_file = self._harness_dir / HARNESS_FILENAME
        self._project_godot = self._project / "project.godot"

    def inject(self) -> None:
        """Copy harness GDScript and register it as an autoload in project.godot.

        Safe to call multiple times — cleans up first if already injected.
        Handles crash recovery: stale entry from a previous crash is detected
        via AUTOLOAD_NAME and removed automatically before re-injecting.
        """
        self.cleanup()  # Ensure clean state / handle crash recovery

        # 1. Copy harness GDScript from package data
        self._harness_dir.mkdir(parents=True, exist_ok=True)
        harness_source = Path(__file__).parent / "harness" / HARNESS_FILENAME
        shutil.copy2(harness_source, self._harness_file)

        # 2. Register autoload in project.godot
        self._add_autoload_entry()

    def cleanup(self) -> None:
        """Remove harness autoload from project.godot and delete harness files.

        Safe to call even if nothing was injected.
        """
        # 1. Remove autoload entry from project.godot
        self._remove_autoload_entry()

        # 2. Remove harness files
        if self._harness_file.exists():
            self._harness_file.unlink()
        if self._harness_dir.exists():
            try:
                self._harness_dir.rmdir()  # Only removes if empty
            except OSError:
                pass  # Directory not empty — leave it

    @property
    def is_injected(self) -> bool:
        """Return True if harness file exists in target project."""
        return self._harness_file.exists()

    # ── Internal helpers ──────────────────────────────────────────────────

    def _add_autoload_entry(self) -> None:
        """Append harness autoload line to project.godot's [autoload] section.

        Inserts at the end of an existing [autoload] section, or creates a new
        section at the end of the file.  Skips silently if already present.
        """
        if not self._project_godot.exists():
            return

        content = self._project_godot.read_text(encoding="utf-8")

        # Idempotency / crash recovery: skip if already present
        if _AUTOLOAD_ENTRY in content:
            return

        lines = content.splitlines(keepends=True)
        result: list[str] = []
        in_autoload = False
        inserted = False

        for line in lines:
            stripped = line.strip()

            # Entering [autoload] section
            if stripped == "[autoload]":
                in_autoload = True
                result.append(line)
                continue

            # New section starts while inside [autoload] — insert before it
            if in_autoload and stripped.startswith("[") and stripped.endswith("]"):
                result.append(_AUTOLOAD_ENTRY + "\n")
                inserted = True
                in_autoload = False

            result.append(line)

        if not inserted:
            if in_autoload:
                # [autoload] was the last section (end of file)
                result.append(_AUTOLOAD_ENTRY + "\n")
            else:
                # No [autoload] section — append a new one
                if result and not result[-1].endswith("\n"):
                    result.append("\n")
                result.append(f"\n[autoload]\n\n{_AUTOLOAD_ENTRY}\n")

        self._project_godot.write_text("".join(result), encoding="utf-8")

    def _remove_autoload_entry(self) -> None:
        """Remove the harness autoload line from project.godot."""
        if not self._project_godot.exists():
            return

        content = self._project_godot.read_text(encoding="utf-8")
        if _AUTOLOAD_ENTRY not in content:
            return

        lines = content.splitlines(keepends=True)
        new_lines = [ln for ln in lines if ln.strip() != _AUTOLOAD_ENTRY]
        self._project_godot.write_text("".join(new_lines), encoding="utf-8")
