"""Two-step approval edit sessions for visualizer direct editing."""

from __future__ import annotations

import difflib
import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_ALLOWED_OPERATIONS = {"replace_text", "append_text", "set_content"}


@dataclass
class EditSession:
    """In-memory + on-disk representation of one edit proposal."""

    edit_session_id: str
    approval_token: str
    project_path: str
    file_path: str
    operation: str
    payload: dict[str, Any]
    reason: str
    created_at: float
    expires_at: float
    before_hash: str
    after_hash: str
    backup_path: str
    diff: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "edit_session_id": self.edit_session_id,
            "approval_token": self.approval_token,
            "project_path": self.project_path,
            "file_path": self.file_path,
            "operation": self.operation,
            "payload": self.payload,
            "reason": self.reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "before_hash": self.before_hash,
            "after_hash": self.after_hash,
            "backup_path": self.backup_path,
            "diff": self.diff,
            "status": self.status,
        }


class VisualizerEditSessionStore:
    """Maintains proposal/apply/cancel lifecycle with rollback safety."""

    def __init__(self, ttl_seconds: int = 900) -> None:
        self._sessions: dict[str, EditSession] = {}
        self._ttl_seconds = ttl_seconds

    def propose(
        self,
        *,
        project_path: str,
        file_path: str,
        operation: str,
        payload: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        project = Path(project_path).resolve()
        target = Path(file_path).resolve() if Path(file_path).is_absolute() else (project / file_path).resolve()

        if operation not in _ALLOWED_OPERATIONS:
            raise ValueError(f"unsupported operation: {operation}")
        if not self._is_inside(project, target):
            raise ValueError("file_path must stay inside project_path")
        if not target.exists():
            raise ValueError(f"target file not found: {target}")

        before = target.read_text(encoding="utf-8")
        after = self._apply_operation(before=before, operation=operation, payload=payload)
        if before == after:
            raise ValueError("proposed edit produces no content changes")

        edit_session_id = uuid.uuid4().hex
        approval_token = secrets.token_urlsafe(24)
        created_at = time.time()
        expires_at = created_at + self._ttl_seconds

        backup_dir = project / ".godot-test-mcp" / "edit_sessions"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{edit_session_id}.bak"
        backup_path.write_text(before, encoding="utf-8")

        diff = "\n".join(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=str(target),
                tofile=str(target),
                lineterm="",
            )
        )

        session = EditSession(
            edit_session_id=edit_session_id,
            approval_token=approval_token,
            project_path=str(project),
            file_path=str(target),
            operation=operation,
            payload=dict(payload),
            reason=str(reason),
            created_at=created_at,
            expires_at=expires_at,
            before_hash=self._hash_text(before),
            after_hash=self._hash_text(after),
            backup_path=str(backup_path),
            diff=diff,
            status="proposed",
        )
        self._sessions[edit_session_id] = session
        self._persist_session(session)

        return {
            "status": "proposed",
            "edit_session": session.to_dict(),
            "impact_summary": self._summarize_diff(diff),
        }

    def apply(self, *, edit_session_id: str, approval_token: str) -> dict[str, Any]:
        session = self._sessions.get(edit_session_id)
        if session is None:
            raise ValueError("edit_session_id not found")
        if session.status != "proposed":
            raise ValueError(f"session is not applicable in current status: {session.status}")
        if time.time() > session.expires_at:
            session.status = "expired"
            self._persist_session(session)
            raise ValueError("edit session expired")
        if approval_token != session.approval_token:
            raise ValueError("invalid approval token")

        target = Path(session.file_path)
        if not target.exists():
            raise ValueError("target file disappeared before apply")

        before = target.read_text(encoding="utf-8")
        before_hash = self._hash_text(before)
        if before_hash != session.before_hash:
            session.status = "conflict"
            self._persist_session(session)
            raise ValueError("target file changed since proposal; re-propose required")

        after = self._apply_operation(before=before, operation=session.operation, payload=session.payload)
        after_hash = self._hash_text(after)
        if after_hash != session.after_hash:
            session.status = "conflict"
            self._persist_session(session)
            raise ValueError("computed content hash mismatch; re-propose required")

        target.write_text(after, encoding="utf-8")
        session.status = "applied"
        self._persist_session(session)

        return {
            "status": "applied",
            "edit_session_id": session.edit_session_id,
            "file_path": session.file_path,
            "backup_path": session.backup_path,
        }

    def cancel(self, *, edit_session_id: str) -> dict[str, Any]:
        session = self._sessions.get(edit_session_id)
        if session is None:
            raise ValueError("edit_session_id not found")
        if session.status == "applied":
            raise ValueError("cannot cancel already applied session")
        session.status = "canceled"
        self._persist_session(session)
        return {
            "status": "canceled",
            "edit_session_id": session.edit_session_id,
        }

    def _apply_operation(self, *, before: str, operation: str, payload: dict[str, Any]) -> str:
        if operation == "set_content":
            content = payload.get("content")
            if not isinstance(content, str):
                raise ValueError("payload.content must be string for set_content")
            return content

        if operation == "append_text":
            text = payload.get("text")
            if not isinstance(text, str):
                raise ValueError("payload.text must be string for append_text")
            return before + text

        if operation == "replace_text":
            old = payload.get("old")
            new = payload.get("new")
            count = payload.get("count", -1)
            if not isinstance(old, str) or not isinstance(new, str):
                raise ValueError("payload.old/new must be strings for replace_text")
            if old == "":
                raise ValueError("payload.old cannot be empty for replace_text")
            try:
                limit = int(count)
            except (TypeError, ValueError):
                limit = -1
            replaced = before.replace(old, new, limit)
            if replaced == before:
                raise ValueError("replace_text did not match any content")
            return replaced

        raise ValueError(f"unsupported operation: {operation}")

    def _persist_session(self, session: EditSession) -> None:
        project = Path(session.project_path)
        session_dir = project / ".godot-test-mcp" / "edit_sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_path = session_dir / f"{session.edit_session_id}.json"
        session_path.write_text(json.dumps(session.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _is_inside(self, parent: Path, child: Path) -> bool:
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    def _hash_text(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _summarize_diff(self, diff: str) -> dict[str, int]:
        added = 0
        removed = 0
        for line in diff.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
        return {"added_lines": added, "removed_lines": removed}
