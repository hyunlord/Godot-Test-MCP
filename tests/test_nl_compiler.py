"""Unit tests for natural-language compiler."""

from __future__ import annotations

from src.nl_compiler import NLTestCompiler


class TestNLTestCompiler:
    """Compiler behavior tests."""

    def test_compiles_state_flow_with_assertion(self) -> None:
        compiler = NLTestCompiler()
        plan = compiler.compile(
            "set /root/Main.score to 10. /root/Main.score should be 10. no errors",
            scene="res://main.tscn",
        )

        step_types = [step.step_type for step in plan.steps]
        assert step_types[0] == "launch"
        assert step_types[1] == "discover"
        assert "set_property" in step_types
        assert "assert_state" in step_types
        assert "assert_no_errors" in step_types
        assert plan.scene == "res://main.tscn"
        assert plan.confidence > 0.7

    def test_marks_visual_and_input_requirements(self) -> None:
        compiler = NLTestCompiler()
        plan = compiler.compile("press ui_accept. 화면에 text \"Game Over\" 가 보여야 한다")

        step_types = [step.step_type for step in plan.steps]
        assert "send_input" in step_types
        assert "assert_visual" in step_types
        assert plan.requires_input is True
        assert plan.requires_visual is True

    def test_collects_unsupported_phrases(self) -> None:
        compiler = NLTestCompiler()
        plan = compiler.compile("quantum banana hyperdrive makes no structured sense")

        assert len(plan.unsupported_phrases) == 1
        assert plan.unsupported_phrases[0].startswith("quantum banana")
        assert plan.confidence < 0.7

    def test_default_assert_no_errors_is_added(self) -> None:
        compiler = NLTestCompiler()
        plan = compiler.compile("wait 0.1 seconds")

        step_types = [step.step_type for step in plan.steps]
        assert "wait" in step_types
        assert "assert_no_errors" in step_types

    def test_parses_call_arguments(self) -> None:
        compiler = NLTestCompiler()
        plan = compiler.compile("call /root/Main.spawn_enemy(3, 'goblin')")

        call_step = next(step for step in plan.steps if step.step_type == "call_method")
        assert call_step.params["path"] == "/root/Main"
        assert call_step.params["method"] == "spawn_enemy"
        assert call_step.params["args"] == [3, "goblin"]
