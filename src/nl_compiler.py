"""Compile free-form natural language into executable Godot test steps."""

from __future__ import annotations

import json
import re
from typing import Any

from .nl_schema import NLCompiledPlan, NLStep


_SPLIT_RE = re.compile(r"(?:\n+|(?<=[!?])\s+|(?<=\.)\s+)")
_WAIT_RE = re.compile(
    r"(?:^|\s)(?:wait|sleep|대기)\s*(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds|초)?(?:$|\s)",
    re.IGNORECASE,
)
_SET_RE = re.compile(
    r"(?:set|설정)\s+([^\s]+)\.([A-Za-z_][A-Za-z0-9_]*)\s*(?:to|=|로|을|를)?\s*(.+)",
    re.IGNORECASE,
)
_CALL_RE = re.compile(
    r"(?:call|invoke|실행)\s+([^\s]+)\.([A-Za-z_][A-Za-z0-9_]*)(?:\((.*)\))?",
    re.IGNORECASE,
)
_STATE_ASSERT_RE = re.compile(
    r"([^\s]+)\.([A-Za-z_][A-Za-z0-9_]*)\s*(==|=|!=|>=|<=|>|<|is|should be|이어야|같아야|같다)\s*(.+)",
    re.IGNORECASE,
)
_INPUT_ACTION_RE = re.compile(
    r"(?:press|tap|input|trigger|키|누르)\s+([A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_NO_ERROR_RE = re.compile(
    r"(?:no\s+errors?|without\s+errors?|에러\s*없|오류\s*없)",
    re.IGNORECASE,
)
_VISUAL_HINT_RE = re.compile(
    r"(?:screen|screenshot|visible|display|text|color|colour|position|ui|화면|보이|텍스트|색|위치)",
    re.IGNORECASE,
)


class NLTestCompiler:
    """Rule-based compiler from natural language to execution IR."""

    def compile(self, spec_text: str, scene: str = "") -> NLCompiledPlan:
        """Compile free-form text into a structured test plan.

        Args:
            spec_text: Natural-language test specification.
            scene: Optional Godot scene path.

        Returns:
            NLCompiledPlan object containing executable steps.
        """
        normalized_text: str = spec_text.strip()
        steps: list[NLStep] = [
            NLStep(
                step_type="launch",
                params={"scene": scene},
                source_text="auto: launch",
                confidence=1.0,
            ),
            NLStep(
                step_type="discover",
                params={},
                source_text="auto: discover",
                confidence=1.0,
            ),
        ]

        unsupported: list[str] = []
        requires_visual: bool = False
        requires_input: bool = False
        recognized_segments: int = 0

        segments: list[str] = [
            seg.strip(" ,\t")
            for seg in _SPLIT_RE.split(normalized_text)
            if seg.strip(" ,\t")
        ]

        for segment in segments:
            matched_in_segment: bool = False
            mutation_matched: bool = False

            wait_match = _WAIT_RE.search(segment)
            if wait_match is not None:
                seconds: float = float(wait_match.group(1))
                steps.append(
                    NLStep(
                        step_type="wait",
                        params={"seconds": seconds},
                        source_text=segment,
                        confidence=0.9,
                    )
                )
                matched_in_segment = True

            set_match = _SET_RE.search(segment)
            if set_match is not None:
                path: str = set_match.group(1).strip()
                property_name: str = set_match.group(2).strip()
                value_raw: str = set_match.group(3).strip()
                steps.append(
                    NLStep(
                        step_type="set_property",
                        params={
                            "path": path,
                            "property": property_name,
                            "value": _parse_value(value_raw),
                        },
                        source_text=segment,
                        confidence=0.82,
                    )
                )
                matched_in_segment = True
                mutation_matched = True

            call_match = _CALL_RE.search(segment)
            if call_match is not None:
                path = call_match.group(1).strip()
                method_name = call_match.group(2).strip()
                args_text = (call_match.group(3) or "").strip()
                args: list[Any] = _parse_args(args_text)
                steps.append(
                    NLStep(
                        step_type="call_method",
                        params={"path": path, "method": method_name, "args": args},
                        source_text=segment,
                        confidence=0.8,
                    )
                )
                matched_in_segment = True
                mutation_matched = True

            input_match = _INPUT_ACTION_RE.search(segment)
            if input_match is not None:
                action_name: str = input_match.group(1).strip()
                steps.append(
                    NLStep(
                        step_type="send_input",
                        params={"action": action_name, "pressed": True},
                        source_text=segment,
                        confidence=0.76,
                    )
                )
                requires_input = True
                matched_in_segment = True

            # Only check assert_state if no mutation was matched in this segment
            if not mutation_matched:
                state_assert_match = _STATE_ASSERT_RE.search(segment)
            else:
                state_assert_match = None
            if state_assert_match is not None:
                raw_op: str = state_assert_match.group(3).strip().lower()
                op: str = _normalize_operator(raw_op)
                steps.append(
                    NLStep(
                        step_type="assert_state",
                        params={
                            "path": state_assert_match.group(1).strip(),
                            "property": state_assert_match.group(2).strip(),
                            "operator": op,
                            "expected": _parse_value(state_assert_match.group(4).strip()),
                        },
                        source_text=segment,
                        confidence=0.85,
                    )
                )
                matched_in_segment = True

            if _NO_ERROR_RE.search(segment) is not None:
                steps.append(
                    NLStep(
                        step_type="assert_no_errors",
                        params={},
                        source_text=segment,
                        confidence=0.92,
                    )
                )
                matched_in_segment = True

            if _VISUAL_HINT_RE.search(segment) is not None:
                steps.append(
                    NLStep(
                        step_type="assert_visual",
                        params={"clause": segment},
                        source_text=segment,
                        confidence=0.68,
                    )
                )
                requires_visual = True
                matched_in_segment = True

            if matched_in_segment:
                recognized_segments += 1
            else:
                unsupported.append(segment)

        if not any(step.step_type.startswith("assert_") for step in steps):
            steps.append(
                NLStep(
                    step_type="assert_no_errors",
                    params={},
                    source_text="auto: default no-error assertion",
                    confidence=0.7,
                )
            )

        confidence: float = _compute_confidence(
            total_segments=len(segments),
            recognized_segments=recognized_segments,
            unsupported_segments=len(unsupported),
        )

        return NLCompiledPlan(
            spec_text=normalized_text,
            scene=scene,
            steps=steps,
            unsupported_phrases=unsupported,
            confidence=confidence,
            requires_visual=requires_visual,
            requires_input=requires_input,
        )


def _parse_args(args_text: str) -> list[Any]:
    """Parse method call arguments from a compact string."""
    if not args_text:
        return []

    raw: str = args_text.strip()
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    parts: list[str] = [part.strip() for part in raw.split(",") if part.strip()]
    return [_parse_value(part) for part in parts]


def _parse_value(raw: str) -> Any:
    """Parse scalar and JSON-like values from text."""
    token: str = raw.strip()
    if token == "":
        return ""

    quoted_single: bool = token.startswith("'") and token.endswith("'") and len(token) >= 2
    quoted_double: bool = token.startswith('"') and token.endswith('"') and len(token) >= 2
    if quoted_single or quoted_double:
        return token[1:-1]

    lowered: str = token.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None

    try:
        if "." in token:
            return float(token)
        return int(token)
    except ValueError:
        pass

    if (token.startswith("{") and token.endswith("}")) or (
        token.startswith("[") and token.endswith("]")
    ):
        try:
            return json.loads(token)
        except json.JSONDecodeError:
            return token

    return token


def _normalize_operator(raw_op: str) -> str:
    """Normalize operator aliases to canonical symbols."""
    op_map: dict[str, str] = {
        "=": "==",
        "is": "==",
        "should be": "==",
        "이어야": "==",
        "같아야": "==",
        "같다": "==",
    }
    return op_map.get(raw_op, raw_op)


def _compute_confidence(
    total_segments: int,
    recognized_segments: int,
    unsupported_segments: int,
) -> float:
    """Compute normalized compile confidence [0.0, 1.0]."""
    if total_segments <= 0:
        return 0.3

    coverage: float = recognized_segments / total_segments
    penalty: float = 0.2 * (unsupported_segments / total_segments)
    score: float = 0.35 + (coverage * 0.65) - penalty
    bounded: float = max(0.0, min(1.0, score))
    return round(bounded, 3)
