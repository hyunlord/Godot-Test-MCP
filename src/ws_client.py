"""Async WebSocket client for communicating with Godot TestHarness."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import websockets
from websockets.asyncio.client import ClientConnection


@dataclass
class GodotWebSocketClient:
    """Connects to Godot TestHarness WebSocket server and sends JSON-RPC commands."""

    host: str = "127.0.0.1"
    port: int = 9877
    timeout: float = 30.0
    _ws: ClientConnection | None = field(default=None, init=False, repr=False)
    _request_id: int = field(default=0, init=False, repr=False)

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    @property
    def is_connected(self) -> bool:
        return self._ws is not None

    async def connect(self, retries: int = 10, delay: float = 0.5) -> None:
        """Connect to Godot WebSocket server with retries.

        Godot needs time to boot and open the WS port.
        Default: 10 retries x 0.5s = 5 seconds max wait.

        Raises:
            ConnectionError: If all retries fail.
        """
        last_error: Exception | None = None
        for _attempt in range(retries):
            try:
                self._ws = await websockets.connect(self.url)
                # Verify with ping
                result = await self.send_command("ping")
                if result.get("pong"):
                    return
            except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
                last_error = e
                if self._ws:
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                    self._ws = None
                await asyncio.sleep(delay)

        raise ConnectionError(
            f"Failed to connect to Godot TestHarness at {self.url} "
            f"after {retries} attempts. "
            f"Is Godot running with --test-harness? Last error: {last_error}"
        )

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def send_command(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC command and wait for response.

        Args:
            method: Command name (e.g. "advance_ticks").
            params: Command parameters (e.g. {"count": 100}).

        Returns:
            The "result" dict from the response.

        Raises:
            ConnectionError: If not connected.
            RuntimeError: If Godot returns an error response.
            asyncio.TimeoutError: If response takes longer than self.timeout.
        """
        if self._ws is None:
            raise ConnectionError("Not connected to Godot. Call connect() first.")

        self._request_id += 1
        request = {
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }

        await self._ws.send(json.dumps(request))
        raw = await asyncio.wait_for(self._ws.recv(), timeout=self.timeout)
        response = json.loads(raw)

        if "error" in response:
            err = response["error"]
            raise RuntimeError(
                f"Godot error ({err.get('code', '?')}): {err.get('message', 'unknown')}"
            )

        return response.get("result", {})
