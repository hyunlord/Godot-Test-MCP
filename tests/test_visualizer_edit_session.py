"""Unit tests for visualizer approval edit sessions."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.visualizer_edit_session import VisualizerEditSessionStore


def test_edit_session_propose_and_apply(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir(parents=True)
    target = project / "a.txt"
    target.write_text("hello world", encoding="utf-8")

    store = VisualizerEditSessionStore(ttl_seconds=60)
    proposal = store.propose(
        project_path=str(project),
        file_path=str(target),
        operation="replace_text",
        payload={"old": "world", "new": "codex"},
        reason="test",
    )

    session = proposal["edit_session"]
    applied = store.apply(
        edit_session_id=session["edit_session_id"],
        approval_token=session["approval_token"],
    )

    assert applied["status"] == "applied"
    assert target.read_text(encoding="utf-8") == "hello codex"


def test_edit_session_cancel(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir(parents=True)
    target = project / "b.txt"
    target.write_text("abc", encoding="utf-8")

    store = VisualizerEditSessionStore(ttl_seconds=60)
    proposal = store.propose(
        project_path=str(project),
        file_path=str(target),
        operation="append_text",
        payload={"text": "def"},
        reason="test",
    )
    session = proposal["edit_session"]
    canceled = store.cancel(edit_session_id=session["edit_session_id"])

    assert canceled["status"] == "canceled"


def test_edit_session_rejects_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    store = VisualizerEditSessionStore(ttl_seconds=60)
    with pytest.raises(ValueError):
        store.propose(
            project_path=str(project),
            file_path=str(outside),
            operation="set_content",
            payload={"content": "y"},
            reason="test",
        )
