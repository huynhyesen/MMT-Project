
import json

from unittest.mock import MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import database, models
from app.routers import relay


# ============================================================
# MOCK DATABASE
# ============================================================

class MockQuery:
    def __init__(self, result=None):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.result

    def all(self):
        return self.result if self.result is not None else []


class MockDatabase:
    def __init__(self):
        self.query_results = {}
        self.added_objects = []
        self.deleted_objects = []

        self.add = MagicMock(side_effect=self._add)
        self.commit = MagicMock()
        self.refresh = MagicMock()
        self.delete = MagicMock(side_effect=self._delete)
        self.close = MagicMock()

    def _add(self, obj):
        self.added_objects.append(obj)

    def _delete(self, obj):
        self.deleted_objects.append(obj)

    def query(self, model):
        result = self.query_results.get(model)

        return MockQuery(result)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def mock_db():
    return MockDatabase()


@pytest.fixture
def client(mock_db):
    def override_get_db():
        yield mock_db

    app.dependency_overrides[database.get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def mock_relay_manager(monkeypatch):
    async def mock_connect(device_hwid, websocket):
        # Giả lập quá trình chấp nhận WebSocket connection
        await websocket.accept()

    connect = AsyncMock(side_effect=mock_connect)
    broadcast_json = AsyncMock()
    broadcast_text = AsyncMock()
    disconnect = MagicMock()

    monkeypatch.setattr(
        relay.manager, "connect", connect
    )
    monkeypatch.setattr(
        relay.manager, "broadcast_json", broadcast_json
    )
    monkeypatch.setattr(
        relay.manager, "broadcast_text", broadcast_text
    )
    monkeypatch.setattr(
        relay.manager, "disconnect", disconnect
    )

    return {
        "connect": connect,
        "broadcast_json": broadcast_json,
        "broadcast_text": broadcast_text,
        "disconnect": disconnect,
    }



# ============================================================
# DEVICE ROUTER - ROUTE REGISTRATION
# ============================================================

def test_device_routes_registered(client):
    paths = app.openapi()["paths"]

    expected_routes = {
        "/devices/create": "post",
        "/devices/pair": "post",
        "/devices/": "get",
        "/devices/{hwid}/config": "get",
        "/devices/{device_id}": "delete",
    }

    for path, method in expected_routes.items():
        assert path in paths
        assert method in paths[path]


# ============================================================
# DEVICE ROUTER - CREATE
# ============================================================

def test_create_device_missing_required_field(client):
    response = client.post(
        "/devices/create",
        json={}
    )

    assert response.status_code == 422


# ============================================================
# DEVICE ROUTER - PAIR
# ============================================================

def test_pair_device_invalid_code(client, mock_db):
    mock_db.query_results[models.Device] = None

    response = client.post(
        "/devices/pair",
        json={
            "device_hwid": "test-hwid",
            "pairing_code": "INVALID-CODE",
            "platform": "Linux"
        }
    )

    assert response.status_code == 404


def test_pair_device_missing_required_fields(client):
    response = client.post(
        "/devices/pair",
        json={}
    )

    assert response.status_code == 422


# ============================================================
# DEVICE ROUTER - GET DEVICES
# ============================================================

def test_get_devices_empty(client, mock_db):
    mock_db.query_results[models.Device] = []

    response = client.get("/devices/")

    assert response.status_code == 200
    assert response.json() == []


# ============================================================
# DEVICE ROUTER - GET CONFIG
# ============================================================

def test_get_device_config_not_found(client, mock_db):
    mock_db.query_results[models.Device] = None

    response = client.get(
        "/devices/nonexistent-device/config"
    )

    assert response.status_code == 404


# ============================================================
# DEVICE ROUTER - DELETE
# ============================================================

def test_delete_device_not_found(client, mock_db):
    mock_db.query_results[models.Device] = None

    response = client.delete(
        "/devices/nonexistent-device"
    )

    assert response.status_code == 404


# ============================================================
# RELAY ROUTER - ROUTE REGISTRATION
# ============================================================

def test_relay_http_route_registered(client):
    paths = app.openapi()["paths"]

    assert "/relay/command" in paths
    assert "post" in paths["/relay/command"]


def test_relay_websocket_route_registered(client):
    path = app.url_path_for(
        "cloud_relay_endpoint",
        device_hwid="test-device"
    )

    assert str(path) == "/ws/relay/test-device"


# ============================================================
# RELAY ROUTER - HTTP COMMAND
# ============================================================

def test_send_relay_command(
    client,
    mock_relay_manager
):
    response = client.post(
        "/relay/command",
        json={
            "target_hwid": "device-001",
            "action": "MESSAGE",
            "data": {
                "message": "Test message"
            }
        }
    )

    assert response.status_code == 200

    result = response.json()

    assert result["status"] == "success"
    assert "device-001" in result["message"]

    mock_relay_manager["broadcast_json"].assert_awaited_once()

    sent_message = (
        mock_relay_manager["broadcast_json"]
        .await_args.args[0]
    )

    assert sent_message["type"] == "MESSAGE"
    assert sent_message["target_hwid"] == "device-001"
    assert sent_message["sender"] == "parent_cloud"


def test_send_relay_command_default_action(
    client,
    mock_relay_manager
):
    response = client.post(
        "/relay/command",
        json={
            "target_hwid": "device-001"
        }
    )

    assert response.status_code == 200

    sent_message = (
        mock_relay_manager["broadcast_json"]
        .await_args.args[0]
    )

    assert sent_message["type"] == "MESSAGE"
    assert sent_message["data"] == {}


# ============================================================
# RELAY ROUTER - WEBSOCKET CONNECTION
# ============================================================

def test_relay_websocket_connect(
    client,
    mock_relay_manager
):
    with client.websocket_connect(
        "/ws/relay/device-001"
    ):
        mock_relay_manager["connect"].assert_awaited_once()

        args = mock_relay_manager["connect"].await_args.args

        assert args[0] == "device-001"

        mock_relay_manager[
            "broadcast_json"
        ].assert_awaited_once()

        connected_message = (
            mock_relay_manager["broadcast_json"]
            .await_args.args[0]
        )

        assert connected_message["type"] == "DEVICE_CONNECTED_WAN"
        assert connected_message["device_hwid"] == "device-001"

    mock_relay_manager["disconnect"].assert_called_once()


# ============================================================
# RELAY ROUTER - PING / PONG
# ============================================================

def test_relay_websocket_ping(
    client,
    mock_relay_manager
):
    with client.websocket_connect(
        "/ws/relay/device-001"
    ) as websocket:

        websocket.send_json({
            "type": "PING"
        })

        response = websocket.receive_json()

        assert response["type"] == "PONG"
        assert "timestamp" in response

        # PONG phải được gửi trực tiếp về client,
        # không broadcast sang các thiết bị khác.
        assert (
            mock_relay_manager["broadcast_json"].await_count
            == 1
        )


# ============================================================
# RELAY ROUTER - MESSAGE BROADCAST
# ============================================================

def test_relay_websocket_broadcast_message(
    client,
    mock_relay_manager
):
    with client.websocket_connect(
        "/ws/relay/device-001"
    ) as websocket:

        websocket.send_json({
            "type": "TELEMETRY",
            "data": {
                "app_name": "test-app"
            }
        })

        assert (
            mock_relay_manager["broadcast_json"].await_count
            == 2
        )

        forwarded_message = (
            mock_relay_manager["broadcast_json"]
            .await_args.args[0]
        )

        assert forwarded_message["type"] == "TELEMETRY"


# ============================================================
# RELAY ROUTER - RAW TEXT
# ============================================================

def test_relay_websocket_raw_text(
    client,
    mock_relay_manager
):
    with client.websocket_connect(
        "/ws/relay/device-001"
    ) as websocket:

        websocket.send_text("raw-message")

        mock_relay_manager[
            "broadcast_text"
        ].assert_awaited_once_with(
            "raw-message",
            sender_ws=mock_relay_manager[
                "broadcast_text"
            ].await_args.kwargs["sender_ws"]
        )


# ============================================================
# RELAY ROUTER - DISCONNECTION
# ============================================================

def test_relay_websocket_disconnect(
    client,
    mock_relay_manager
):
    with client.websocket_connect(
        "/ws/relay/device-001"
    ):
        pass

    mock_relay_manager["disconnect"].assert_called_once()

    messages = [
        call.args[0]
        for call in mock_relay_manager[
            "broadcast_json"
        ].await_args_list
    ]

    assert messages[0]["type"] == "DEVICE_CONNECTED_WAN"
    assert messages[-1]["type"] == "DEVICE_DISCONNECTED_WAN"
