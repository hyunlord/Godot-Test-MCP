"""Execute compiled natural-language test plans through MCP Godot primitives."""

from __future__ import annotations

import asyncio
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from .artifact_store import ArtifactStore
from .nl_schema import NLCompiledPlan, NLStep
from .visual_oracle import VisualOracle


@dataclass
class NLExecutionContext:
    """Execution dependencies injected from server layer."""

    project_path: str
    launch: Callable[[str, str], Awaitable[dict[str, Any]]]
    stop: Callable[[bool], Awaitable[dict[str, Any]]]
    ws_command: Callable[[str, dict[str, Any] | None], Awaitable[dict[str, Any]]]
    read_errors: Callable[[], dict[str, list[dict[str, Any]]]]
    read_output: Callable[[int], list[str]]


class NLTestExecutor:
    """Runs compiled test plans and emits structured PASS/FAIL reports."""

    def __init__(self, visual_oracle: VisualOracle | None = None) -> None:
        self._visual_oracle: VisualOracle = visual_oracle or VisualOracle()

    async def run(
        self,
        plan: NLCompiledPlan,
        mode: str,
        timeout_seconds: int,
        artifact_level: str,
        context: NLExecutionContext,
    ) -> dict[str, Any]:
        """Run the compiled plan and return a full execution report."""
        run_id: str = _new_run_id()
        store = ArtifactStore(project_path=context.project_path, run_id=run_id)

        runtime_mode: str = _resolve_runtime_mode(mode=mode, requires_visual=plan.requires_visual)
        start_time: float = time.time()
        step_results: list[dict[str, Any]] = []
        assertion_results: list[dict[str, Any]] = []
        evidence: list[dict[str, Any]] = []
        screenshots: list[str] = []
        frames: list[str] = []
        errors: list[dict[str, Any]] = []
        final_result: str = "ERROR"
        final_confidence: float = plan.confidence

        launched: bool = False

        try:
            launch_response = await asyncio.wait_for(
                context.launch(runtime_mode, plan.scene),
                timeout=max(10, min(timeout_seconds, 120)),
            )
            launched = launch_response.get("status") == "launched"
            store.append_event({"event": "launch", "response": launch_response})

            if not launched:
                final_result = "ERROR"
                errors.append({"stage": "launch", "message": "failed to launch Godot"})
            else:
                capabilities = await context.ws_command("get_capabilities", {})
                store.append_event({"event": "capabilities", "response": capabilities})

                for index, step in enumerate(plan.steps):
                    step_result = await self._execute_step(
                        index=index,
                        step=step,
                        context=context,
                        store=store,
                        capabilities=capabilities,
                        artifact_level=artifact_level,
                    )
                    step_results.append(step_result)
                    if step_result.get("is_assertion"):
                        assertion_results.append(step_result)
                    evidence.extend(step_result.get("evidence", []))
                    if step_result.get("error") is not None:
                        errors.append(step_result["error"])
                    if step_result.get("screenshot"):
                        screenshots.append(str(step_result["screenshot"]))
                    if step_result.get("frame"):
                        frames.append(str(step_result["frame"]))

                final_result = _aggregate_result(assertion_results)
                if any(str(item.get("status", "")) == "ERROR" for item in step_results):
                    final_result = "ERROR"
                final_confidence = _aggregate_confidence(assertion_results, plan.confidence)

        except asyncio.TimeoutError:
            final_result = "ERROR"
            errors.append(
                {
                    "stage": "run",
                    "message": f"execution timed out after {timeout_seconds}s",
                }
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            final_result = "ERROR"
            errors.append({"stage": "run", "message": str(exc)})
        finally:
            stop_response = await context.stop(False)
            store.append_event({"event": "stop", "response": stop_response})

        runtime_seconds: float = round(time.time() - start_time, 3)
        ffmpeg_available: bool = shutil.which("ffmpeg") is not None
        video_info: dict[str, Any] = {
            "available": False,
            "path": None,
            "reason": "ffmpeg not installed" if not ffmpeg_available else "no frames captured",
        }
        if ffmpeg_available and len(frames) > 0:
            video_path = str((store.root_dir / "video.mp4").resolve())
            rendered = await _render_video(
                frames_dir=store.frames_dir,
                output_path=Path(video_path),
            )
            video_info = {
                "available": rendered,
                "path": video_path if rendered else None,
                "reason": None if rendered else "ffmpeg render failed",
            }

        summary: str = _build_summary(
            result=final_result,
            runtime_seconds=runtime_seconds,
            assertion_results=assertion_results,
            unsupported=plan.unsupported_phrases,
        )

        report: dict[str, Any] = {
            "result": final_result,
            "confidence": final_confidence,
            "run_id": run_id,
            "runtime_mode": runtime_mode,
            "runtime_seconds": runtime_seconds,
            "compiled_plan": plan.to_dict(),
            "step_results": step_results,
            "assertions": assertion_results,
            "unsupported_phrases": list(plan.unsupported_phrases),
            "evidence": evidence,
            "artifacts": {
                "screenshots": screenshots,
                "frames": frames,
                "video": video_info,
                "logs": [str(store.events_path.resolve())],
            },
            "summary": summary,
            "errors": errors,
        }

        report_path: str = store.write_report(report)
        report["artifacts"]["logs"].append(report_path)
        store.write_report(report)
        return report

    async def _execute_step(
        self,
        index: int,
        step: NLStep,
        context: NLExecutionContext,
        store: ArtifactStore,
        capabilities: dict[str, Any],
        artifact_level: str,
    ) -> dict[str, Any]:
        """Execute one IR step and return normalized step result."""
        step_type: str = step.step_type
        result: dict[str, Any] = {
            "index": index,
            "step_type": step_type,
            "source_text": step.source_text,
            "confidence": step.confidence,
            "is_assertion": step_type.startswith("assert_"),
            "status": "PASS",
            "details": {},
            "evidence": [],
            "error": None,
        }

        if step_type == "launch":
            result["details"] = {"status": "skipped", "reason": "handled by executor"}
            return result

        if step_type == "discover":
            result["details"] = {
                "status": "ok",
                "capabilities_found": len(capabilities.get("nodes", [])) if isinstance(capabilities, dict) else 0,
            }
            return result

        try:
            if step_type == "set_property":
                response = await context.ws_command(
                    "set_property",
                    {
                        "path": step.params.get("path", ""),
                        "property": step.params.get("property", ""),
                        "value": step.params.get("value"),
                    },
                )
                result["details"] = response
                result["status"] = "PASS" if response.get("status") == "ok" else "ERROR"

            elif step_type == "call_method":
                response = await context.ws_command(
                    "call_method",
                    {
                        "path": step.params.get("path", ""),
                        "method": step.params.get("method", ""),
                        "args": step.params.get("args", []),
                    },
                )
                result["details"] = response
                result["status"] = "PASS" if response.get("status") == "ok" else "ERROR"

            elif step_type == "send_input":
                response = await context.ws_command("send_input", dict(step.params))
                result["details"] = response
                result["status"] = "PASS" if response.get("status") == "ok" else "ERROR"

            elif step_type == "wait":
                if "frames" in step.params:
                    response = await context.ws_command(
                        "wait_frames", {"frames": step.params.get("frames", 1)}
                    )
                    result["details"] = response
                    result["status"] = "PASS" if response.get("status") == "ok" else "ERROR"
                else:
                    seconds = float(step.params.get("seconds", 0.1))
                    await asyncio.sleep(max(0.0, seconds))
                    result["details"] = {"status": "ok", "slept_seconds": seconds}
                    result["status"] = "PASS"

            elif step_type == "assert_state":
                response = await context.ws_command(
                    "get_property",
                    {
                        "path": step.params.get("path", ""),
                        "property": step.params.get("property", ""),
                    },
                )
                if response.get("status") != "ok":
                    result["status"] = "UNDETERMINED"
                    result["details"] = response
                    result["confidence"] = min(step.confidence, 0.45)
                else:
                    actual = response.get("value")
                    expected = step.params.get("expected")
                    operator = str(step.params.get("operator", "=="))
                    passed = _compare_values(actual=actual, expected=expected, operator=operator)
                    result["status"] = "PASS" if passed else "FAIL"
                    result["details"] = {
                        "actual": actual,
                        "expected": expected,
                        "operator": operator,
                    }
                    result["evidence"].append(
                        {
                            "type": "state",
                            "path": step.params.get("path", ""),
                            "property": step.params.get("property", ""),
                            "actual": actual,
                            "expected": expected,
                            "operator": operator,
                        }
                    )

            elif step_type == "assert_no_errors":
                data = context.read_errors()
                collected_errors: list[dict[str, Any]] = data.get("errors", [])
                collected_warnings: list[dict[str, Any]] = data.get("warnings", [])
                has_errors: bool = len(collected_errors) > 0
                result["status"] = "FAIL" if has_errors else "PASS"
                result["details"] = {
                    "error_count": len(collected_errors),
                    "warning_count": len(collected_warnings),
                }
                if has_errors:
                    result["evidence"].append(
                        {
                            "type": "errors",
                            "first_error": collected_errors[0],
                        }
                    )

            elif step_type == "assert_visual":
                screenshot_path = store.screenshot_target(f"assert_{index:03d}")
                capture = await context.ws_command(
                    "capture_screenshot", {"path": screenshot_path}
                )
                snapshot = await context.ws_command("get_visual_snapshot", {})

                if artifact_level == "full":
                    frame_path = store.frame_target(f"frame_{index:03d}")
                    frame_capture = await context.ws_command(
                        "capture_frame", {"path": frame_path}
                    )
                    if frame_capture.get("status") == "ok":
                        result["frame"] = frame_capture.get("path", frame_path)

                clause = str(step.params.get("clause", step.source_text))
                oracle_input: dict[str, Any] = (
                    snapshot if snapshot.get("status") == "ok" else {"nodes": []}
                )
                oracle_result = self._visual_oracle.evaluate(clause=clause, snapshot=oracle_input)
                result["status"] = oracle_result.get("result", "UNDETERMINED")
                result["confidence"] = float(oracle_result.get("confidence", step.confidence))
                result["details"] = {
                    "capture": capture,
                    "snapshot_status": snapshot.get("status"),
                    "oracle": oracle_result,
                }
                result["screenshot"] = capture.get("path", screenshot_path)
                result["evidence"].append(
                    {
                        "type": "visual",
                        "clause": clause,
                        "screenshot": result["screenshot"],
                        "oracle": oracle_result,
                    }
                )

            else:
                result["status"] = "UNDETERMINED"
                result["details"] = {"reason": f"unsupported step type: {step_type}"}

        except Exception as exc:  # pragma: no cover - defensive fallback
            result["status"] = "ERROR"
            result["error"] = {"stage": step_type, "message": str(exc)}

        if result["status"] in {"ERROR", "UNDETERMINED"} and result["error"] is None:
            result["error"] = {
                "stage": step_type,
                "message": str(result.get("details", {})),
            }

        store.append_event(
            {
                "event": "step",
                "index": index,
                "step_type": step_type,
                "status": result["status"],
                "details": result.get("details", {}),
            }
        )
        return result


def _resolve_runtime_mode(mode: str, requires_visual: bool) -> str:
    """Resolve run mode with automatic visual-aware fallback."""
    if mode in {"headless", "windowed"}:
        return mode
    return "windowed" if requires_visual else "headless"


def _aggregate_result(assertion_results: list[dict[str, Any]]) -> str:
    """Aggregate per-assertion statuses into final run result."""
    if not assertion_results:
        return "UNDETERMINED"

    statuses: list[str] = [str(item.get("status", "UNDETERMINED")) for item in assertion_results]
    if any(status == "ERROR" for status in statuses):
        return "ERROR"
    if any(status == "FAIL" for status in statuses):
        return "FAIL"
    if any(status == "UNDETERMINED" for status in statuses):
        return "UNDETERMINED"
    return "PASS"


def _aggregate_confidence(assertion_results: list[dict[str, Any]], fallback: float) -> float:
    """Aggregate confidence values from assertions."""
    if not assertion_results:
        return round(fallback, 3)

    values: list[float] = []
    for item in assertion_results:
        try:
            values.append(float(item.get("confidence", fallback)))
        except (TypeError, ValueError):
            values.append(fallback)

    average: float = sum(values) / len(values)
    return round(max(0.0, min(1.0, average)), 3)


def _build_summary(
    result: str,
    runtime_seconds: float,
    assertion_results: list[dict[str, Any]],
    unsupported: list[str],
) -> str:
    """Build concise run summary string."""
    total_assertions: int = len(assertion_results)
    unsupported_count: int = len(unsupported)
    return (
        f"Result={result}, assertions={total_assertions}, "
        f"unsupported_phrases={unsupported_count}, runtime={runtime_seconds:.2f}s"
    )


def _new_run_id() -> str:
    """Generate deterministic-looking run identifier."""
    timestamp: str = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


async def _render_video(frames_dir: Path, output_path: Path) -> bool:
    """Render frame PNG files into an MP4 video using ffmpeg."""
    pattern: str = str((frames_dir / "*.png").resolve())
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-framerate",
        "30",
        "-pattern_type",
        "glob",
        "-i",
        pattern,
        "-pix_fmt",
        "yuv420p",
        str(output_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    exit_code: int = await process.wait()
    return exit_code == 0 and output_path.is_file()


def _compare_values(actual: Any, expected: Any, operator: str) -> bool:
    """Compare two values with a normalized operator."""
    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected

    try:
        actual_num: float = float(actual)
        expected_num: float = float(expected)
    except (TypeError, ValueError):
        return False

    if operator == ">":
        return actual_num > expected_num
    if operator == "<":
        return actual_num < expected_num
    if operator == ">=":
        return actual_num >= expected_num
    if operator == "<=":
        return actual_num <= expected_num
    return False
