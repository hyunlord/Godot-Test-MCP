"""Unit tests for visual oracle."""

from __future__ import annotations

from src.visual_oracle import VisualOracle


class TestVisualOracle:
    """Visual assertion evaluation tests."""

    def test_text_assertion_passes_when_text_exists(self) -> None:
        oracle = VisualOracle()
        snapshot = {
            "nodes": [
                {"name": "ScoreLabel", "path": "/root/Main/UI/Score", "text": "Score: 100"},
            ]
        }

        result = oracle.evaluate('text "Score" should appear', snapshot)
        assert result["result"] == "PASS"
        assert result["confidence"] >= 0.8

    def test_count_assertion_fails_when_count_mismatch(self) -> None:
        oracle = VisualOracle()
        snapshot = {
            "visible_node_count": 2,
            "nodes": [{"name": "A"}, {"name": "B"}],
        }

        result = oracle.evaluate("3 nodes should be visible", snapshot)
        assert result["result"] == "FAIL"

    def test_color_assertion_returns_undetermined(self) -> None:
        oracle = VisualOracle()
        snapshot = {"nodes": []}

        result = oracle.evaluate("the button should be red", snapshot)
        assert result["result"] == "UNDETERMINED"

    def test_unknown_visual_phrase_returns_undetermined(self) -> None:
        oracle = VisualOracle()
        snapshot = {"nodes": []}

        result = oracle.evaluate("the vibe should feel dramatic", snapshot)
        assert result["result"] == "UNDETERMINED"
        assert result["confidence"] <= 0.5
