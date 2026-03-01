"""Rule-based visual assertion oracle for language-agnostic game testing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_TEXT_RE = re.compile(r"(?:text|텍스트)\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_COUNT_RE = re.compile(r"(\d+)\s*(?:nodes?|objects?|entities?|개)", re.IGNORECASE)
_COLOR_HINT_RE = re.compile(r"(?:red|green|blue|yellow|orange|purple|색|빨강|파랑|초록)", re.IGNORECASE)
_POSITION_HINT_RE = re.compile(r"(?:left|right|center|top|bottom|위|아래|좌|우|중앙|위치)", re.IGNORECASE)


@dataclass
class VisualOracle:
    """Evaluates free-form visual assertions against snapshot metadata."""

    def evaluate(self, clause: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Evaluate one visual clause.

        Returns a dict containing result, confidence, and evidence.
        """
        normalized_clause: str = clause.strip()
        nodes: list[dict[str, Any]] = _extract_nodes(snapshot)

        text_match = _TEXT_RE.search(normalized_clause)
        if text_match is not None:
            needle: str = text_match.group(1)
            matched_nodes: list[str] = [
                str(node.get("path", node.get("name", "")))
                for node in nodes
                if needle.lower() in str(node.get("text", "")).lower()
            ]
            passed: bool = len(matched_nodes) > 0
            return {
                "result": "PASS" if passed else "FAIL",
                "confidence": 0.9 if passed else 0.85,
                "evidence": {
                    "type": "text",
                    "needle": needle,
                    "matched_nodes": matched_nodes,
                },
            }

        count_match = _COUNT_RE.search(normalized_clause)
        if count_match is not None:
            expected_count: int = int(count_match.group(1))
            actual_count: int = int(snapshot.get("visible_node_count", len(nodes)))
            passed = actual_count == expected_count
            return {
                "result": "PASS" if passed else "FAIL",
                "confidence": 0.86,
                "evidence": {
                    "type": "count",
                    "expected": expected_count,
                    "actual": actual_count,
                },
            }

        if _COLOR_HINT_RE.search(normalized_clause) is not None:
            return {
                "result": "UNDETERMINED",
                "confidence": 0.4,
                "evidence": {
                    "type": "color",
                    "reason": "color parsing from raw screenshot is unsupported in rule-only oracle",
                },
            }

        if _POSITION_HINT_RE.search(normalized_clause) is not None:
            return {
                "result": "UNDETERMINED",
                "confidence": 0.45,
                "evidence": {
                    "type": "position",
                    "reason": "position semantics require project-specific anchors",
                },
            }

        return {
            "result": "UNDETERMINED",
            "confidence": 0.35,
            "evidence": {
                "type": "unknown",
                "reason": "unsupported visual phrase",
            },
        }


def _extract_nodes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize node collection field from snapshot payload."""
    raw_nodes: Any = snapshot.get("nodes", [])
    if not isinstance(raw_nodes, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_nodes:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized
