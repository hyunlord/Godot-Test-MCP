"""Inject and cleanup test harness GDScript in target Godot project.

Uses override.cfg instead of modifying project.godot, ensuring zero
impact on the target project's configuration files.
"""

from __future__ import annotations

import shutil
from pathlib import Path


# Harness destination inside addons/ (visible to Godot's resource system)
HARNESS_DIR = "addons/test_mcp"
HARNESS_FILENAME = "test_harness.gd"
AUTOLOAD_NAME = "GodotTestMcpHarness"
OVERRIDE_CFG = "override.cfg"

# Marker comment so we can identify our override.cfg during crash recovery
MARKER = "# godot-test-mcp-injected"

# Disk backup filename (stored inside HARNESS_DIR)
_BACKUP_FILENAME = "override.cfg.bak"


class HarnessInjector:
    """Manages injection and cleanup of test harness in a Godot project.

    Strategy:
      1. Copy test_harness.gd to addons/test_mcp/
      2. Write override.cfg with autoload entry (Godot reads this automatically)
      3. On cleanup: delete override.cfg + addons/test_mcp/, restore backup

    This avoids all project.godot parsing and modification.
    """

    def __init__(self, project_path: str) -> None:
        self._project = Path(project_path)
        self._override_file = self._project / OVERRIDE_CFG
        self._harness_dir = self._project / HARNESS_DIR
        self._harness_file = self._harness_dir / HARNESS_FILENAME
        self._backup_file = self._harness_dir / _BACKUP_FILENAME
        self._override_backup: str | None = None

    def inject(self) -> None:
        """Copy harness GDScript and create override.cfg for autoload.

        Safe to call multiple times — cleans up first if already injected.
        Handles crash recovery: stale override.cfg from previous crash is
        detected via marker comment and cleaned up automatically.
        """
        self.cleanup()  # Ensure clean state (handles crash recovery)

        # 1. Copy harness GDScript from package data
        self._harness_dir.mkdir(parents=True, exist_ok=True)
        harness_source = Path(__file__).parent / "harness" / HARNESS_FILENAME
        shutil.copy2(harness_source, self._harness_file)

        # 2. Backup existing override.cfg if present (and not ours from a crash)
        if self._override_file.exists():
            content = self._override_file.read_text(encoding="utf-8")
            if MARKER not in content:
                self._override_backup = content
                self._backup_file.write_text(content, encoding="utf-8")

        # 3. Write override.cfg with our autoload
        self._override_file.write_text(
            f"{MARKER}\n"
            f"[autoload]\n"
            f"\n"
            f'{AUTOLOAD_NAME}="*res://{HARNESS_DIR}/{HARNESS_FILENAME}"\n',
            encoding="utf-8",
        )

    def cleanup(self) -> None:
        """Remove injected harness and restore override.cfg.

        Safe to call even if nothing was injected.
        """
        # 1. Restore or remove override.cfg
        if self._override_backup is not None:
            # Normal path: restore from in-memory backup
            self._override_file.write_text(self._override_backup, encoding="utf-8")
            self._override_backup = None
        elif self._backup_file.exists():
            # Crash recovery: restore from disk backup
            restored = self._backup_file.read_text(encoding="utf-8")
            self._override_file.write_text(restored, encoding="utf-8")
        elif self._override_file.exists():
            # No backup — only remove if it's ours (has marker)
            content = self._override_file.read_text(encoding="utf-8")
            if MARKER in content:
                self._override_file.unlink()

        # 2. Remove harness files (including disk backup)
        if self._backup_file.exists():
            self._backup_file.unlink()
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
