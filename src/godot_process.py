"""Manage Godot subprocess lifecycle and output capture."""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING

from .error_parser import ErrorParser

if TYPE_CHECKING:
    from .config import Config


class GodotProcessManager:
    """Manages a single Godot subprocess with async stdout/stderr capture."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_lines: list[str] = []
        self._stderr_lines: list[str] = []
        self._parser: ErrorParser = ErrorParser()
        self._start_time: float = 0.0
        self._reader_task: asyncio.Task | None = None
        self._exit_code: int | None = None

    async def launch(
        self, mode: str, scene: str, extra_args: list[str],
        test_harness: bool = False,
    ) -> int:
        """Start Godot process. Stops existing process first if running.

        Args:
            mode: Run mode (headless, windowed, editor).
            scene: Scene path to run (empty = main scene).
            extra_args: Additional Godot CLI arguments.
            test_harness: If True, append --test-harness to enable WS bridge.

        Returns the PID of the new process.
        """
        if self.is_running:
            await self.stop()

        # Reset state
        self._stdout_lines = []
        self._stderr_lines = []
        self._parser = ErrorParser()
        self._exit_code = None

        cmd = self._build_cmd(mode, scene, extra_args)
        if test_harness:
            cmd.append("--test-harness")
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._start_time = time.time()
        self._reader_task = asyncio.create_task(self._read_streams())
        return self._process.pid

    async def stop(self, force: bool = False) -> int:
        """Stop the Godot process.

        Args:
            force: If True, send SIGKILL immediately. Otherwise SIGTERM first.

        Returns the exit code.
        """
        if self._process is None or self._process.returncode is not None:
            code = self._process.returncode if self._process else 0
            self._exit_code = code
            return code or 0

        if force:
            self._process.kill()
        else:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._process.kill()

        await self._process.wait()

        # Wait for reader task to finish consuming remaining output
        if self._reader_task and not self._reader_task.done():
            try:
                await asyncio.wait_for(self._reader_task, timeout=5)
            except asyncio.TimeoutError:
                self._reader_task.cancel()

        self._exit_code = self._process.returncode or 0
        return self._exit_code

    async def wait_for_exit(self, timeout: float) -> int:
        """Wait for the process to exit on its own (or until timeout).

        Returns the exit code.
        """
        if self._process is None:
            return 0

        try:
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Process didn't exit in time — kill it
            self._process.kill()
            await self._process.wait()

        # Wait for reader to finish
        if self._reader_task and not self._reader_task.done():
            try:
                await asyncio.wait_for(self._reader_task, timeout=5)
            except asyncio.TimeoutError:
                self._reader_task.cancel()

        self._exit_code = self._process.returncode or 0
        return self._exit_code

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def uptime(self) -> float:
        if self._start_time == 0.0:
            return 0.0
        return time.time() - self._start_time

    @property
    def exit_code(self) -> int | None:
        if self._process is None:
            return self._exit_code
        if self._process.returncode is not None:
            return self._process.returncode
        return self._exit_code

    def get_errors(self) -> list[dict]:
        """Return parsed errors as dicts."""
        return [e.to_dict() for e in self._parser.get_errors()]

    def get_warnings(self) -> list[dict]:
        """Return parsed warnings as dicts."""
        return [w.to_dict() for w in self._parser.get_warnings()]

    def get_output(self, tail: int = 100, pattern: str = "") -> list[str]:
        """Get combined stdout+stderr output.

        Args:
            tail: Return the last N lines.
            pattern: Regex filter pattern. Empty string means no filter.
        """
        combined = self._stdout_lines + self._stderr_lines
        if pattern:
            try:
                compiled = re.compile(pattern)
                combined = [ln for ln in combined if compiled.search(ln)]
            except re.error:
                pass  # Invalid regex — return unfiltered
        if tail > 0:
            combined = combined[-tail:]
        return combined

    def _build_cmd(self, mode: str, scene: str, extra_args: list[str]) -> list[str]:
        cmd = [self._config.godot_path]
        if mode == "headless":
            cmd.append("--headless")
        elif mode == "editor":
            cmd.append("-e")
        # "windowed" = no special flag (default Godot behavior)
        cmd.extend(["--path", self._config.project_path])
        if scene:
            cmd.append(scene)
        cmd.append("--verbose")
        cmd.extend(extra_args)
        return cmd

    async def _read_streams(self) -> None:
        """Read stdout and stderr concurrently, feeding lines to the parser."""

        async def _read(
            stream: asyncio.StreamReader,
            buffer: list[str],
        ) -> None:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
                buffer.append(line)
                elapsed = time.time() - self._start_time
                self._parser.feed_line(line, elapsed)
                # Cap buffer at 50,000 lines
                if len(buffer) > 50_000:
                    del buffer[:10_000]

        assert self._process is not None
        assert self._process.stdout is not None
        assert self._process.stderr is not None

        await asyncio.gather(
            _read(self._process.stdout, self._stdout_lines),
            _read(self._process.stderr, self._stderr_lines),
        )
        # Flush any pending multi-line error
        self._parser.flush()
