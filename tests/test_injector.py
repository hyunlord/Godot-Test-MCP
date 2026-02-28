"""Unit tests for HarnessInjector (project.godot modification approach).

The injector now writes directly to project.godot instead of using override.cfg
because Godot 4 override.cfg cannot add NEW autoload entries — only override
values for autoloads already declared in project.godot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.injector import (
    AUTOLOAD_NAME,
    HARNESS_DIR,
    HARNESS_FILENAME,
    HarnessInjector,
    _AUTOLOAD_ENTRY,
)

_PROJECT_GODOT_WITH_AUTOLOAD = (
    "[gd_resource]\nconfig_version=5\n\n"
    "[application]\nrun/main_scene=\"res://main.tscn\"\n\n"
    "[autoload]\n\n"
    'SomeManager="*res://some_manager.gd"\n\n'
    "[display]\nwindow/size/viewport_width=1920\n"
)

_PROJECT_GODOT_NO_AUTOLOAD = (
    "[gd_resource]\nconfig_version=5\n\n"
    "[application]\nrun/main_scene=\"res://main.tscn\"\n"
)


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """Fake Godot project WITH an existing [autoload] section."""
    (tmp_path / "project.godot").write_text(
        _PROJECT_GODOT_WITH_AUTOLOAD, encoding="utf-8"
    )
    harness_src = Path(__file__).parent.parent / "src" / "harness" / HARNESS_FILENAME
    assert harness_src.exists(), f"Harness source not found at {harness_src}"
    return tmp_path


@pytest.fixture
def fake_project_no_autoload(tmp_path: Path) -> Path:
    """Fake Godot project WITHOUT an [autoload] section."""
    (tmp_path / "project.godot").write_text(
        _PROJECT_GODOT_NO_AUTOLOAD, encoding="utf-8"
    )
    harness_src = Path(__file__).parent.parent / "src" / "harness" / HARNESS_FILENAME
    assert harness_src.exists()
    return tmp_path


class TestInject:
    """Tests for the inject method."""

    def test_inject_creates_harness_file(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        harness_file = fake_project / HARNESS_DIR / HARNESS_FILENAME
        assert harness_file.exists()
        content = harness_file.read_text(encoding="utf-8")
        assert "TestHarness" in content

    def test_inject_adds_autoload_to_project_godot(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert _AUTOLOAD_ENTRY in content
        assert AUTOLOAD_NAME in content

    def test_inject_autoload_entry_in_autoload_section(self, fake_project: Path) -> None:
        """Entry must appear inside the [autoload] section, not elsewhere."""
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        content = (fake_project / "project.godot").read_text(encoding="utf-8")
        lines = content.splitlines()
        autoload_idx = next(i for i, l in enumerate(lines) if l.strip() == "[autoload]")
        entry_idx = next(i for i, l in enumerate(lines) if l.strip() == _AUTOLOAD_ENTRY)
        # Entry must come after [autoload] header
        assert entry_idx > autoload_idx
        # Entry must come before any subsequent section header (if any)
        next_section = next(
            (i for i, l in enumerate(lines) if i > autoload_idx and l.startswith("[") and l.strip() != "[autoload]"),
            len(lines),
        )
        assert entry_idx < next_section

    def test_inject_creates_autoload_section_when_absent(
        self, fake_project_no_autoload: Path
    ) -> None:
        injector = HarnessInjector(str(fake_project_no_autoload))
        injector.inject()
        content = (fake_project_no_autoload / "project.godot").read_text(encoding="utf-8")
        assert "[autoload]" in content
        assert _AUTOLOAD_ENTRY in content

    def test_inject_does_not_create_override_cfg(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        assert not (fake_project / "override.cfg").exists()

    def test_inject_preserves_existing_autoloads(self, fake_project: Path) -> None:
        """Existing autoload entries must not be removed or altered."""
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert 'SomeManager="*res://some_manager.gd"' in content

    def test_inject_preserves_other_sections(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert "[display]" in content
        assert "window/size/viewport_width=1920" in content

    def test_inject_is_idempotent(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.inject()  # Should not raise or duplicate
        content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert content.count(_AUTOLOAD_ENTRY) == 1

    def test_inject_harness_path_uses_res_protocol(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert f'"*res://{HARNESS_DIR}/{HARNESS_FILENAME}"' in content


class TestCleanup:
    """Tests for the cleanup method."""

    def test_cleanup_removes_harness_file(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        assert injector.is_injected
        injector.cleanup()
        assert not injector.is_injected

    def test_cleanup_removes_autoload_entry(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.cleanup()
        content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert _AUTOLOAD_ENTRY not in content
        assert AUTOLOAD_NAME not in content

    def test_cleanup_preserves_existing_autoloads(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.cleanup()
        content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert 'SomeManager="*res://some_manager.gd"' in content

    def test_cleanup_removes_harness_dir(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.cleanup()
        assert not (fake_project / HARNESS_DIR).exists()

    def test_cleanup_safe_when_not_injected(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.cleanup()  # Should not raise

    def test_cleanup_does_not_alter_other_project_godot_content(
        self, fake_project: Path
    ) -> None:
        original = (fake_project / "project.godot").read_text(encoding="utf-8")
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.cleanup()
        after = (fake_project / "project.godot").read_text(encoding="utf-8")
        # All original lines must still be present
        for line in original.splitlines():
            assert line in after.splitlines(), f"Line lost: {line!r}"

    def test_cleanup_crash_recovery_removes_stale_entry(
        self, fake_project: Path
    ) -> None:
        """Simulate crash: first injector object lost, second detects stale entry."""
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        assert _AUTOLOAD_ENTRY in (fake_project / "project.godot").read_text(encoding="utf-8")

        # Crash: create new injector without prior in-memory state
        injector2 = HarnessInjector(str(fake_project))
        injector2.cleanup()

        content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert _AUTOLOAD_ENTRY not in content

    def test_cleanup_crash_recovery_no_override_cfg_created(
        self, fake_project: Path
    ) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector2 = HarnessInjector(str(fake_project))
        injector2.cleanup()
        assert not (fake_project / "override.cfg").exists()


class TestIsInjected:
    """Tests for the is_injected property."""

    def test_not_injected_initially(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        assert not injector.is_injected

    def test_injected_after_inject(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        assert injector.is_injected

    def test_not_injected_after_cleanup(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.cleanup()
        assert not injector.is_injected
