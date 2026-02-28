"""Async WebSocket client for Godot TestHarness communication."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import websockets
from websockets.asyncio.client import ClientConnection


@dataclass
class GodotWebSocketClient:
    """Connects to Godot TestHarness and sends JSON-RPC commands."""

    host: str = "127.0.0.1"
    port: int = 9877
    timeout: float = 30.0
    _ws: ClientConnection | None = field(default=None, init=False, repr=False)
    _request_id: int = field(default=0, init=False, repr=False)

    @property
    def url(self) -> str:
        """WebSocket URL."""
        return f"ws://{self.host}:{self.port}"

    @property
    def is_connected(self) -> bool:
        """Return True if WebSocket is connected."""
        return self._ws is not None

    async def connect(self, retries: int = 15, delay: float = 0.5) -> None:
        """Connect to Godot WS server with retries.

        Two-phase approach:
          Phase 1: Standard retries (retries × delay)
          Phase 2: If phase 1 fails, try 5 more attempts with 3s delay
                   (fallback for stdout buffering issues in headless mode)

        Raises:
            ConnectionError: If all retries fail.
        """
        last_error: Exception | None = None

        # Phase 1: Standard retries (existing behavior)
        for _ in range(retries):
            try:
                self._ws = await websockets.connect(self.url)
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

        # Phase 2: Extended fallback (for headless stdout buffering)
        for _ in range(5):
            try:
                self._ws = await websockets.connect(self.url)
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
                await asyncio.sleep(3.0)  # Longer delay for fallback

        raise ConnectionError(
            f"Cannot connect to Godot TestHarness at {self.url} "
            f"after {retries + 5} attempts. Last error: {last_error}"
        )

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def send_command(
        self, method: str, params: dict | None = None
    ) -> dict:
        """Send a JSON-RPC command and wait for response.

        Args:
            method: Command name (e.g. "get_tree_info").
            params: Command parameters.

        Returns:
            The "result" dict from the response.

        Raises:
            ConnectionError: If not connected.
            RuntimeError: If Godot returns an error response.
            asyncio.TimeoutError: If response takes longer than self.timeout.
        """
        if self._ws is None:
            raise ConnectionError("Not connected. Call connect() first.")

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
                f"Godot error ({err.get('code', '?')}): "
                f"{err.get('message', 'unknown')}"
            )

        return response.get("result", {})
