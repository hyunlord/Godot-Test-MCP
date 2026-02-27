"""Inject and cleanup test harness GDScript in target Godot project."""

from __future__ import annotations

import shutil
from pathlib import Path


# Harness destination inside target project
HARNESS_DIR = "addons/godot_test_mcp"
HARNESS_FILENAME = "test_harness.gd"
AUTOLOAD_NAME = "GodotTestMcpHarness"
AUTOLOAD_LINE = f'{AUTOLOAD_NAME}="*res://{HARNESS_DIR}/{HARNESS_FILENAME}"'

# Marker comment so we can identify our injection
MARKER = "# godot-test-mcp-injected"


class HarnessInjector:
    """Manages injection and cleanup of test harness in a Godot project."""

    def __init__(self, project_path: str) -> None:
        self._project = Path(project_path)
        self._godot_file = self._project / "project.godot"
        self._harness_dir = self._project / HARNESS_DIR
        self._harness_file = self._harness_dir / HARNESS_FILENAME
        self._backup: str | None = None  # Original project.godot content

    def inject(self) -> None:
        """Copy harness GDScript and register autoload in project.godot.

        Safe to call multiple times — cleans up first if already injected.
        """
        self.cleanup()  # Ensure clean state

        # 1. Copy harness GDScript from package data
        self._harness_dir.mkdir(parents=True, exist_ok=True)
        harness_source = Path(__file__).parent / "harness" / HARNESS_FILENAME
        shutil.copy2(harness_source, self._harness_file)

        # 2. Modify project.godot to add autoload
        if not self._godot_file.exists():
            raise FileNotFoundError(
                f"project.godot not found at {self._godot_file}"
            )

        self._backup = self._godot_file.read_text(encoding="utf-8")
        content = self._backup

        if "[autoload]" in content:
            lines = content.split("\n")
            autoload_idx = -1
            last_autoload_line = -1
            for i, line in enumerate(lines):
                if line.strip() == "[autoload]":
                    autoload_idx = i
                if autoload_idx >= 0 and i > autoload_idx:
                    if line.strip().startswith("[") and line.strip() != "[autoload]":
                        break
                    if "=" in line and not line.strip().startswith("#"):
                        last_autoload_line = i

            insert_at = (
                (last_autoload_line + 1)
                if last_autoload_line >= 0
                else (autoload_idx + 1)
            )
            lines.insert(insert_at, f"{AUTOLOAD_LINE}  {MARKER}")
            content = "\n".join(lines)
        else:
            content += f"\n[autoload]\n\n{AUTOLOAD_LINE}  {MARKER}\n"

        self._godot_file.write_text(content, encoding="utf-8")

    def cleanup(self) -> None:
        """Remove injected harness and restore project.godot.

        Safe to call even if nothing was injected.
        """
        # 1. Remove harness files
        if self._harness_file.exists():
            self._harness_file.unlink()
        if self._harness_dir.exists():
            try:
                self._harness_dir.rmdir()  # Only removes if empty
            except OSError:
                pass  # Directory not empty — user put files there, leave it

        # 2. Restore project.godot
        if self._backup is not None:
            self._godot_file.write_text(self._backup, encoding="utf-8")
            self._backup = None
        elif self._godot_file.exists():
            # No backup — maybe crashed last time. Remove our marker line.
            content = self._godot_file.read_text(encoding="utf-8")
            lines = content.split("\n")
            cleaned = [ln for ln in lines if MARKER not in ln]
            if len(cleaned) != len(lines):
                self._godot_file.write_text(
                    "\n".join(cleaned), encoding="utf-8"
                )

    @property
    def is_injected(self) -> bool:
        """Return True if harness file exists in target project."""
        return self._harness_file.exists()
