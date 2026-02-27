"""Parse Godot stdout/stderr output into structured error objects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ParsedError:
    level: str          # "error" | "warning"
    category: str       # "SCRIPT_ERROR" | "PARSE_ERROR" | "RESOURCE_ERROR" | "GENERAL_ERROR"
    message: str        # Error message body
    source: str         # "res://scripts/..." or ""
    line: int           # Line number or -1
    timestamp: float    # Seconds since process start
    raw: str            # Original text before parsing
    count: int = 1      # Repeat count (dedup)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "category": self.category,
            "message": self.message,
            "source": self.source,
            "line": self.line,
            "timestamp": self.timestamp,
            "raw": self.raw,
            "count": self.count,
        }


# Pre-compiled patterns (priority order)
_PARSE_ERROR_RE = re.compile(
    r"(res://\S+\.gd):(\d+)\s*-\s*Parse Error:\s*(.+)"
)
_RESOURCE_ERROR_RE = re.compile(
    r"(?:Cannot open file|Failed to load resource)[:\s]*\"?(res://[^\"\s]+)\"?"
)
_AT_LINE_RE = re.compile(
    r"\s+at:\s*(res://\S+):(\d+)"
)
_AT_LINE_NO_SOURCE_RE = re.compile(
    r"\s+at:\s*(.*)"
)


class ErrorParser:
    """Incremental parser for Godot stdout/stderr error output.

    Feed lines one at a time via feed_line(). The parser handles multi-line
    error formats (SCRIPT ERROR + "   at:" continuation) and deduplicates
    repeated errors.
    """

    def __init__(self) -> None:
        self._errors: list[ParsedError] = []
        self._warnings: list[ParsedError] = []
        self._seen: dict[str, int] = {}  # dedup key -> index in _errors/_warnings

        # Multi-line pending state
        self._pending_line: str | None = None
        self._pending_elapsed: float = 0.0
        self._pending_category: str = ""

    def feed_line(self, line: str, elapsed: float) -> ParsedError | None:
        """Process one line of Godot output.

        Returns a ParsedError if an error/warning was detected, else None.
        For multi-line errors, returns on the continuation line.
        """
        result = None

        # 1. Handle pending multi-line error
        if self._pending_line is not None:
            if line.startswith("   at:"):
                m = _AT_LINE_RE.match(line)
                if m:
                    result = self._complete_pending(
                        source=m.group(1),
                        line_no=int(m.group(2)),
                    )
                else:
                    result = self._complete_pending(source="", line_no=-1)
                return result
            else:
                # Next line is not "   at:" — complete pending as standalone
                result = self._complete_pending(source="", line_no=-1)
                # Fall through to process current line

        # 2. Match current line against patterns
        # Pattern 2: Parse Error (single line)
        m = _PARSE_ERROR_RE.match(line)
        if m:
            parsed = self._add_error(
                level="error",
                category="PARSE_ERROR",
                message=m.group(3),
                source=m.group(1),
                line_no=int(m.group(2)),
                elapsed=elapsed,
                raw=line,
            )
            return parsed or result

        # Pattern 3/4: Resource Error (single line)
        m = _RESOURCE_ERROR_RE.match(line)
        if m:
            parsed = self._add_error(
                level="error",
                category="RESOURCE_ERROR",
                message=line,
                source=m.group(1),
                line_no=-1,
                elapsed=elapsed,
                raw=line,
            )
            return parsed or result

        # Pattern 1: SCRIPT ERROR (multi-line start)
        if line.startswith("SCRIPT ERROR:"):
            self._pending_line = line
            self._pending_elapsed = elapsed
            self._pending_category = "SCRIPT_ERROR"
            return result

        # Pattern 5/6: ERROR (multi-line start possible)
        if line.startswith("ERROR:"):
            self._pending_line = line
            self._pending_elapsed = elapsed
            self._pending_category = "GENERAL_ERROR"
            return result

        # Pattern 7/8: WARNING (multi-line start possible)
        if line.startswith("WARNING:"):
            self._pending_line = line
            self._pending_elapsed = elapsed
            self._pending_category = "WARNING"
            return result

        return result

    def get_errors(self) -> list[ParsedError]:
        """Return all collected errors (deduplicated)."""
        return list(self._errors)

    def get_warnings(self) -> list[ParsedError]:
        """Return all collected warnings (deduplicated)."""
        return list(self._warnings)

    def flush(self) -> ParsedError | None:
        """Force-complete any pending multi-line error."""
        if self._pending_line is not None:
            return self._complete_pending(source="", line_no=-1)
        return None

    def _complete_pending(self, source: str, line_no: int) -> ParsedError:
        """Complete a pending multi-line error/warning."""
        assert self._pending_line is not None

        pending_line = self._pending_line
        elapsed = self._pending_elapsed
        category = self._pending_category

        # Clear pending state
        self._pending_line = None

        # Extract message from the pending line
        # "SCRIPT ERROR: msg" / "ERROR: msg" / "WARNING: msg"
        colon_idx = pending_line.index(":")
        message = pending_line[colon_idx + 1:].strip()

        if source:
            raw = f"{pending_line}\n   at: {source}:{line_no}"
        else:
            raw = pending_line

        level = "warning" if category == "WARNING" else "error"
        if category == "WARNING":
            category = "GENERAL_WARNING"

        return self._add_error(
            level=level,
            category=category,
            message=message,
            source=source,
            line_no=line_no,
            elapsed=elapsed,
            raw=raw,
        )

    def _add_error(
        self,
        level: str,
        category: str,
        message: str,
        source: str,
        line_no: int,
        elapsed: float,
        raw: str,
    ) -> ParsedError:
        """Add error with deduplication. Returns the ParsedError (new or existing)."""
        # Build dedup key
        dedup_key = f"{level}:{source}:{line_no}:{message[:80]}"

        if dedup_key in self._seen:
            idx = self._seen[dedup_key]
            target_list = self._warnings if level == "warning" else self._errors
            target_list[idx].count += 1
            return target_list[idx]

        error = ParsedError(
            level=level,
            category=category,
            message=message,
            source=source,
            line=line_no,
            timestamp=elapsed,
            raw=raw,
        )

        target_list = self._warnings if level == "warning" else self._errors
        self._seen[dedup_key] = len(target_list)
        target_list.append(error)
        return error
