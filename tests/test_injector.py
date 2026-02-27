"""Unit tests for HarnessInjector."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.injector import AUTOLOAD_NAME, HARNESS_DIR, HARNESS_FILENAME, MARKER, HarnessInjector


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """Create a minimal fake Godot project directory."""
    godot_file = tmp_path / "project.godot"
    godot_file.write_text(
        '[gd_resource]\nconfig_version=5\n\n[application]\nrun/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
    # Create the harness source that injector expects
    harness_src = Path(__file__).parent.parent / "src" / "harness" / HARNESS_FILENAME
    assert harness_src.exists(), f"Harness source not found at {harness_src}"
    return tmp_path


@pytest.fixture
def fake_project_with_autoload(tmp_path: Path) -> Path:
    """Create a fake Godot project that already has an [autoload] section."""
    godot_file = tmp_path / "project.godot"
    godot_file.write_text(
        '[gd_resource]\nconfig_version=5\n\n[autoload]\n\nMyGame="*res://game.gd"\n\n[application]\nrun/main_scene="res://main.tscn"\n',
        encoding="utf-8",
    )
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

    def test_inject_adds_autoload_section(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        godot_content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert "[autoload]" in godot_content
        assert AUTOLOAD_NAME in godot_content
        assert MARKER in godot_content

    def test_inject_appends_to_existing_autoload(self, fake_project_with_autoload: Path) -> None:
        injector = HarnessInjector(str(fake_project_with_autoload))
        injector.inject()
        godot_content = (fake_project_with_autoload / "project.godot").read_text(encoding="utf-8")
        assert AUTOLOAD_NAME in godot_content
        assert 'MyGame="*res://game.gd"' in godot_content
        # Only one [autoload] section
        assert godot_content.count("[autoload]") == 1

    def test_inject_raises_if_no_project_godot(self, tmp_path: Path) -> None:
        injector = HarnessInjector(str(tmp_path))
        with pytest.raises(FileNotFoundError, match="project.godot"):
            injector.inject()

    def test_inject_is_idempotent(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.inject()  # Should not raise or duplicate
        godot_content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert godot_content.count(AUTOLOAD_NAME) == 1


class TestCleanup:
    """Tests for the cleanup method."""

    def test_cleanup_removes_harness_file(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        assert injector.is_injected
        injector.cleanup()
        assert not injector.is_injected

    def test_cleanup_restores_project_godot(self, fake_project: Path) -> None:
        original = (fake_project / "project.godot").read_text(encoding="utf-8")
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        injector.cleanup()
        restored = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert restored == original

    def test_cleanup_safe_when_not_injected(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.cleanup()  # Should not raise

    def test_cleanup_removes_marker_without_backup(self, fake_project: Path) -> None:
        """Simulate crash recovery — no in-memory backup, but marker exists in file."""
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        # Simulate crash: create new injector without backup
        injector2 = HarnessInjector(str(fake_project))
        injector2.cleanup()
        godot_content = (fake_project / "project.godot").read_text(encoding="utf-8")
        assert MARKER not in godot_content
        assert AUTOLOAD_NAME not in godot_content

    def test_cleanup_preserves_other_autoloads(self, fake_project_with_autoload: Path) -> None:
        injector = HarnessInjector(str(fake_project_with_autoload))
        injector.inject()
        injector.cleanup()
        godot_content = (fake_project_with_autoload / "project.godot").read_text(encoding="utf-8")
        assert 'MyGame="*res://game.gd"' in godot_content
        assert AUTOLOAD_NAME not in godot_content

    def test_cleanup_leaves_dir_if_not_empty(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        # Put an extra file in the harness dir
        extra = fake_project / HARNESS_DIR / "user_file.gd"
        extra.write_text("# user file", encoding="utf-8")
        injector.cleanup()
        # Dir should still exist (has user file) but harness removed
        assert not (fake_project / HARNESS_DIR / HARNESS_FILENAME).exists()
        assert extra.exists()


class TestIsInjected:
    """Tests for the is_injected property."""

    def test_not_injected_initially(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        assert not injector.is_injected

    def test_injected_after_inject(self, fake_project: Path) -> None:
        injector = HarnessInjector(str(fake_project))
        injector.inject()
        assert injector.is_injected
