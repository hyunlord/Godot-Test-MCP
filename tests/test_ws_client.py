"""Unit tests for GodotWebSocketClient."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from src.ws_client import GodotWebSocketClient


class TestGodotWebSocketClient:
    """Tests for the WebSocket client dataclass."""

    def test_default_values(self) -> None:
        client = GodotWebSocketClient()
        assert client.host == "127.0.0.1"
        assert client.port == 9877
        assert client.timeout == 30.0
        assert client.url == "ws://127.0.0.1:9877"
        assert client.is_connected is False

    def test_custom_values(self) -> None:
        client = GodotWebSocketClient(host="localhost", port=8080, timeout=10.0)
        assert client.url == "ws://localhost:8080"

    def test_is_connected_false_when_no_ws(self) -> None:
        client = GodotWebSocketClient()
        assert client.is_connected is False


class TestSendCommand:
    """Tests for send_command method."""

    @pytest.fixture
    def client(self) -> GodotWebSocketClient:
        return GodotWebSocketClient()

    async def test_send_command_not_connected(self, client: GodotWebSocketClient) -> None:
        with pytest.raises(ConnectionError, match="Not connected"):
            await client.send_command("ping")

    async def test_send_command_success(self, client: GodotWebSocketClient) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "id": 1,
            "result": {"pong": True, "tick": 42},
        }))
        client._ws = mock_ws

        result = await client.send_command("ping")

        assert result == {"pong": True, "tick": 42}
        mock_ws.send.assert_called_once()
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["method"] == "ping"
        assert sent_data["id"] == 1
        assert sent_data["params"] == {}

    async def test_send_command_with_params(self, client: GodotWebSocketClient) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "id": 1,
            "result": {"path": "/root/Main", "name": "Main"},
        }))
        client._ws = mock_ws

        result = await client.send_command("get_node", {"path": "/root/Main"})

        assert result["path"] == "/root/Main"
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["params"] == {"path": "/root/Main"}

    async def test_send_command_error_response(self, client: GodotWebSocketClient) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "id": 1,
            "error": {"code": -1, "message": "Node not found: /root/Bad"},
        }))
        client._ws = mock_ws

        with pytest.raises(RuntimeError, match="Node not found"):
            await client.send_command("get_node", {"path": "/root/Bad"})

    async def test_send_command_increments_id(self, client: GodotWebSocketClient) -> None:
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({"id": 1, "result": {}}))
        client._ws = mock_ws

        await client.send_command("ping")
        await client.send_command("ping")

        assert client._request_id == 2


class TestDisconnect:
    """Tests for disconnect method."""

    async def test_disconnect_when_connected(self) -> None:
        client = GodotWebSocketClient()
        mock_ws = AsyncMock()
        client._ws = mock_ws

        await client.disconnect()

        mock_ws.close.assert_called_once()
        assert client._ws is None

    async def test_disconnect_when_not_connected(self) -> None:
        client = GodotWebSocketClient()
        await client.disconnect()  # Should not raise
        assert client._ws is None

    async def test_disconnect_handles_close_error(self) -> None:
        client = GodotWebSocketClient()
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock(side_effect=Exception("connection lost"))
        client._ws = mock_ws

        await client.disconnect()  # Should not raise
        assert client._ws is None


class TestConnect:
    """Tests for connect method with retries."""

    @patch("src.ws_client.websockets.connect")
    async def test_connect_all_retries_fail(self, mock_connect: AsyncMock) -> None:
        mock_connect.side_effect = ConnectionRefusedError("refused")
        client = GodotWebSocketClient()

        with pytest.raises(ConnectionError, match="Cannot connect"):
            await client.connect(retries=2, delay=0.01)

        assert client._ws is None
