"""Live visualizer server over shared HTTP + WebSocket port."""

from __future__ import annotations

import asyncio
import http
import json
import mimetypes
from pathlib import Path
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response


class VisualizerLiveServer:
    """Hosts static visualizer artifacts and pushes live events."""

    def __init__(self) -> None:
        self._server: Server | None = None
        self._sockets: set[ServerConnection] = set()
        self._host = "127.0.0.1"
        self._port = 0
        self._static_root: Path | None = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    async def start(self, *, static_root: Path, port: int = 0) -> dict[str, Any]:
        if self.is_running:
            return {
                "status": "running",
                "host": self._host,
                "port": self._port,
                "url": f"http://{self._host}:{self._port}/",
                "ws_url": f"ws://{self._host}:{self._port}/ws",
            }

        self._static_root = static_root.resolve()
        self._port = int(port) if int(port) > 0 else 0

        async def _process_request(connection: ServerConnection, request: Request):
            path = request.path
            if path.startswith("/ws"):
                return None

            if self._static_root is None:
                return connection.respond(http.HTTPStatus.INTERNAL_SERVER_ERROR, "live server not ready\n")

            normalized = path.split("?", 1)[0]
            rel = "index.html" if normalized in {"", "/"} else normalized.lstrip("/")
            target = (self._static_root / rel).resolve()
            if not self._is_inside(self._static_root, target) or not target.is_file():
                return connection.respond(http.HTTPStatus.NOT_FOUND, "not found\n")

            data = target.read_bytes()
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            headers = Headers(
                [
                    ("Content-Type", content_type),
                    ("Content-Length", str(len(data))),
                    ("Cache-Control", "no-store"),
                ]
            )
            return Response(http.HTTPStatus.OK.value, http.HTTPStatus.OK.phrase, headers, data)

        self._server = await serve(
            self._handle_ws,
            self._host,
            self._port,
            process_request=_process_request,
            max_size=10 * 1024 * 1024,
        )

        sock = next(iter(self._server.sockets or []), None)
        if sock is not None:
            self._port = int(sock.getsockname()[1])

        return {
            "status": "started",
            "host": self._host,
            "port": self._port,
            "url": f"http://{self._host}:{self._port}/",
            "ws_url": f"ws://{self._host}:{self._port}/ws",
        }

    async def stop(self) -> dict[str, Any]:
        if self._server is None:
            return {"status": "not_running"}

        for sock in list(self._sockets):
            try:
                await sock.close()
            except Exception:
                pass
        self._sockets.clear()

        self._server.close()
        await self._server.wait_closed()
        self._server = None
        return {"status": "stopped"}

    async def publish(self, event: dict[str, Any]) -> None:
        if self._server is None or len(self._sockets) == 0:
            return

        message = json.dumps(event, ensure_ascii=False)
        dead: list[ServerConnection] = []
        for sock in list(self._sockets):
            try:
                await sock.send(message)
            except ConnectionClosed:
                dead.append(sock)
            except Exception:
                dead.append(sock)
        for sock in dead:
            self._sockets.discard(sock)

    async def _handle_ws(self, websocket: ServerConnection) -> None:
        path = websocket.request.path if websocket.request is not None else ""
        if not path.startswith("/ws"):
            await websocket.close(code=1008, reason="invalid endpoint")
            return

        self._sockets.add(websocket)
        try:
            await websocket.send(json.dumps({"type": "hello", "status": "connected"}, ensure_ascii=False))
            async for message in websocket:
                if message == "ping":
                    await websocket.send("pong")
                else:
                    await websocket.send(json.dumps({"type": "echo", "payload": message}, ensure_ascii=False))
        finally:
            self._sockets.discard(websocket)

    def _is_inside(self, parent: Path, child: Path) -> bool:
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False
