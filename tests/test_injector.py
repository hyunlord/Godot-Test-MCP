"""Unit tests for HarnessInjector (override.cfg approach)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.injector import (
    AUTOLOAD_NAME,
    HARNESS_DIR,
    HARNESS_FILENAME,
    MARKER,
    OVERRIDE_CFG,
    HarnessInjector,
)


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """Create a minimal fake Godot project directory."""
    godot_file = tmp_path / "project.godot"
    godot_file.write_text(
        '[gd_resource]\nconfig_version=5\n\n[application]\nrun/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    # Ensure harness source exists (test prerequisite)
    harness_src = Path(__file__).parent.parent / "src" / "harness" / HARNESS_FILENAME
    assert harness_src.exists(), f"Harness source not found at {harness_src}"
    return tmp_path


@pytest.fixture
def fake_project_with_override(tmp_path: Path) -> Path:
    """Create a fake Godot project that already has an override.cfg."""
    godot_file = tmp_path / "project.godot"
    godot_file.write_text(
        '[gd_resource]\nconfig_version=5\n',
        encoding="utf-8",
    )
    override_file = tmp_path / OVERRIDE_CFG
    override_file.write_text(
        '[rendering]\nrenderer/rendering_method="forward_plus"\n',
        encoding="utf-8",
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

    def test_inject_creates_override_cfg(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        override = fake_project / OVERRIDE_CFG
        assert override.exists()
        content = override.read_text(encoding="utf-8")
        assert "[autoload]" in content
        assert AUTOLOAD_NAME in content

    def test_inject_override_has_marker(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        content = (fake_project / OVERRIDE_CFG).read_text(encoding="utf-8")
        assert MARKER in content

    def test_inject_does_not_modify_project_godot(self, fake_project: Path) -> None:
        original = (fake_project / "project.godot").read_text(encoding="utf-8")
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        after = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert after == original

    def test_inject_backs_up_existing_override(self, fake_project_with_override: Path) -> None:
        original_override = (fake_project_with_override / OVERRIDE_CFG).read_text(encoding="utf-8")
        injector = HarnessInjector(str(fake_project_with_override))
        injector.inject()
        # Our override.cfg should replace the original
        content = (fake_project_with_override / OVERRIDE_CFG).read_text(encoding="utf-8")
        assert MARKER in content
        assert AUTOLOAD_NAME in content
        # Disk backup should exist
        backup = fake_project_with_override / HARNESS_DIR / "override.cfg.bak"
        assert backup.exists()
        assert backup.read_text(encoding="utf-8") == original_override

    def test_inject_is_idempotent(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.inject()  # Should not raise or duplicate
        content = (fake_project / OVERRIDE_CFG).read_text(encoding="utf-8")
        assert content.count(AUTOLOAD_NAME) == 1


class TestCleanup:
    """Tests for the cleanup method."""

    def test_cleanup_removes_harness_file(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        assert injector.is_injected
        injector.cleanup()
        assert not injector.is_injected

    def test_cleanup_removes_override_cfg(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.cleanup()
        assert not (fake_project / OVERRIDE_CFG).exists()

    def test_cleanup_removes_harness_dir(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.cleanup()
        assert not (fake_project / HARNESS_DIR).exists()

    def test_cleanup_restores_existing_override(self, fake_project_with_override: Path) -> None:
        original = (fake_project_with_override / OVERRIDE_CFG).read_text(encoding="utf-8")
        injector = HarnessInjector(str(fake_project_with_override))
        injector.inject()
        injector.cleanup()
        restored = (fake_project_with_override / OVERRIDE_CFG).read_text(encoding="utf-8")
        assert restored == original

    def test_cleanup_safe_when_not_injected(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.cleanup()  # Should not raise

    def test_cleanup_does_not_touch_project_godot(self, fake_project: Path) -> None:
        original = (fake_project / "project.godot").read_text(encoding="utf-8")
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.cleanup()
        after = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert after == original

    def test_cleanup_crash_recovery_removes_our_override(self, fake_project: Path) -> None:
        """Simulate crash: no in-memory backup, but our override.cfg exists."""
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        # Simulate crash: new injector without in-memory backup
        injector2 = HarnessInjector(str(fake_project))
        injector2.cleanup()
        assert not (fake_project / OVERRIDE_CFG).exists()

    def test_cleanup_crash_recovery_restores_user_override(self, fake_project_with_override: Path) -> None:
        """Simulate crash: disk backup exists, restore user's original override.cfg."""
        original = (fake_project_with_override / OVERRIDE_CFG).read_text(encoding="utf-8")
        injector = HarnessInjector(str(fake_project_with_override))
        injector.inject()
        # Simulate crash: new injector without in-memory backup
        injector2 = HarnessInjector(str(fake_project_with_override))
        injector2.cleanup()
        restored = (fake_project_with_override / OVERRIDE_CFG).read_text(encoding="utf-8")
        assert restored == original

    def test_cleanup_preserves_user_override_without_marker(self, fake_project: Path) -> None:
        """If override.cfg exists without marker and no backup, leave it alone."""
        user_override = fake_project / OVERRIDE_CFG
        user_override.write_text('[display]\nwidth=800\n', encoding="utf-8")
        injector = HarnessInjector(str(fake_project))
        injector.cleanup()
        assert user_override.exists()
        assert user_override.read_text(encoding="utf-8") == '[display]\nwidth=800\n'


class TestIsInjected:
    """Tests for the is_injected property."""

    def test_not_injected_initially(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        assert not injector.is_injected

    def test_injected_after_inject(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        assert injector.is_injected
