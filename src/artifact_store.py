"""Artifact persistence for natural-language test runs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ArtifactStore:
    """Writes run-level artifacts and reports under the Godot project directory."""

    project_path: str
    run_id: str
    root_dir: Path = field(init=False)
    screenshots_dir: Path = field(init=False)
    frames_dir: Path = field(init=False)
    events_path: Path = field(init=False)
    report_path: Path = field(init=False)

    def __post_init__(self) -> None:
        base: Path = Path(self.project_path).resolve()
        self.root_dir = base / ".godot-test-mcp" / "runs" / self.run_id
        self.screenshots_dir = self.root_dir / "screenshots"
        self.frames_dir = self.root_dir / "frames"
        self.events_path = self.root_dir / "events.jsonl"
        self.report_path = self.root_dir / "report.json"

        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)

    def append_event(self, event: dict[str, Any]) -> None:
        """Append one event as JSON line."""
        payload: dict[str, Any] = {
            "timestamp": round(time.time(), 3),
            **event,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def write_report(self, report: dict[str, Any]) -> str:
        """Write the final structured run report and return its path."""
        with self.report_path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
        return str(self.report_path)

    def screenshot_target(self, name: str) -> str:
        """Return absolute target path for a screenshot artifact."""
        safe_name: str = _safe_filename(name)
        return str((self.screenshots_dir / f"{safe_name}.png").resolve())

    def frame_target(self, name: str) -> str:
        """Return absolute target path for a frame artifact."""
        safe_name = _safe_filename(name)
        return str((self.frames_dir / f"{safe_name}.png").resolve())


def _safe_filename(name: str) -> str:
    """Sanitize file names for artifact outputs."""
    cleaned: str = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in name)
    return cleaned.strip("_") or "artifact"
