"""Schema types for natural-language test compilation and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


StepType = Literal[
    "launch",
    "discover",
    "set_property",
    "call_method",
    "send_input",
    "wait",
    "assert_state",
    "assert_visual",
    "assert_no_errors",
]


@dataclass
class NLStep:
    """One executable step in the compiled natural-language test plan."""

    step_type: StepType
    params: dict[str, Any] = field(default_factory=dict)
    source_text: str = ""
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "step_type": self.step_type,
            "params": self.params,
            "source_text": self.source_text,
            "confidence": self.confidence,
        }


@dataclass
class NLCompiledPlan:
    """Compiled execution plan generated from free-form natural-language input."""

    spec_text: str
    scene: str
    steps: list[NLStep]
    unsupported_phrases: list[str]
    confidence: float
    requires_visual: bool
    requires_input: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "spec_text": self.spec_text,
            "scene": self.scene,
            "steps": [step.to_dict() for step in self.steps],
            "unsupported_phrases": list(self.unsupported_phrases),
            "confidence": self.confidence,
            "requires_visual": self.requires_visual,
            "requires_input": self.requires_input,
        }
