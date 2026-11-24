
from base64 import b64encode
from types import SimpleNamespace

from unittest.mock import MagicMock, AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app import main
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

    def delete(self, *args, **kwargs):
        return 0

    def update(self, *args, **kwargs):
        return 0


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
def client(mock_db, parent_credentials):
    def override_get_db():
        yield mock_db

    app.dependency_overrides[database.get_db] = override_get_db

    credential = b64encode(":".join(parent_credentials).encode()).decode()
    with TestClient(app, headers={"Authorization": f"Basic {credential}"}) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def mock_relay_manager(monkeypatch):
    async def mock_connect(device_hwid, websocket):
        # Giả lập quá trình chấp nhận WebSocket connection
        await websocket.accept()

    monkeypatch.setattr(relay, "resolve_device", lambda *args, **kwargs: SimpleNamespace(device_hwid="device-001"))
    connect = AsyncMock(side_effect=mock_connect)
    broadcast_json = AsyncMock()
    broadcast_text = AsyncMock()
    disconnect = MagicMock()
    send_to_device = AsyncMock(return_value=True)

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
    monkeypatch.setattr(
        relay.manager, "send_to_device", send_to_device
    )

    return {
        "connect": connect,
        "broadcast_json": broadcast_json,
        "broadcast_text": broadcast_text,
        "disconnect": disconnect,
        "send_to_device": send_to_device,
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

    mock_relay_manager["send_to_device"].assert_awaited_once()

    target_hwid, sent_message = (
        mock_relay_manager["send_to_device"]
        .await_args.args
    )

    assert target_hwid == "device-001"
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

    target_hwid, sent_message = (
        mock_relay_manager["send_to_device"]
        .await_args.args
    )

    assert target_hwid == "device-001"
    assert sent_message["type"] == "MESSAGE"
    assert sent_message["data"] == {}


# ============================================================
# RELAY ROUTER - WEBSOCKET CONNECTION
# ============================================================

def test_relay_websocket_connect_and_disconnect(client, mock_relay_manager):
    with client.websocket_connect("/ws/relay/device-001") as socket:
        socket.send_json({"type": "PING"})
        assert socket.receive_json()["type"] == "PONG"
        mock_relay_manager["connect"].assert_awaited_once()
        assert mock_relay_manager["connect"].await_args.args[0] == "device-001"
    mock_relay_manager["disconnect"].assert_called_once()
    events = mock_relay_manager["send_to_device"].await_args_list
    assert [call.args[0] for call in events] == ["parent_dashboard", "parent_dashboard"]
    assert [call.args[1]["type"] for call in events] == [
        "DEVICE_CONNECTED_WAN", "DEVICE_DISCONNECTED_WAN"
    ]


def test_relay_websocket_events_are_scoped(client, mock_relay_manager):
    with client.websocket_connect("/ws/relay/device-001") as socket:
        socket.send_json({"type": "TELEMETRY", "data": {"app_name": "test-app"}})
        socket.send_text("raw-message")
        socket.send_json({"type": "PING"})
        assert socket.receive_json()["type"] == "PONG"
    events = mock_relay_manager["send_to_device"].await_args_list
    assert [call.args[1]["type"] for call in events] == [
        "DEVICE_CONNECTED_WAN", "TELEMETRY", "DEVICE_DISCONNECTED_WAN"
    ]
    assert events[1].args[0] == "parent_dashboard"
    mock_relay_manager["broadcast_json"].assert_not_awaited()
    mock_relay_manager["broadcast_text"].assert_not_awaited()


# ============================================================
# STANDARDIZED DAILY ROLLOVER & USAGE RESET
# ============================================================

def test_daily_rollover_and_usage_reset(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollover.db'}")
    models.Base.metadata.create_all(bind=engine)
    db = database.SessionLocal(bind=engine)
    try:
        db.add(models.DailyRollover(id=1, day="2098-12-31"))
        # Tạo dữ liệu giả định trong ngày
        rule = models.AppWebRule(
            rule_type="APP",
            target_value="test_game.exe",
            action="BLOCK",
            time_limit_minutes=60,
            used_minutes=45
        )
        db.add(rule)
        log = models.MinimalTelemetryLog(
            app_name="test_game.exe",
            duration_seconds=2700
        )
        db.add(log)
        req = models.ChildRequest(
            request_type="TIME_EXTENSION",
            target_detail="30",
            reason_from_child="Học bài",
            status="PENDING"
        )
        db.add(req)
        db.commit()

        # Thực thi hàm chuẩn hóa daily reset
        assert main.perform_daily_reset(db, today_str="2099-01-01", automatic=True)
        assert not main.perform_daily_reset(db, today_str="2099-01-01", automatic=True)

        # Kiểm tra kết quả
        refreshed_rule = db.query(models.AppWebRule).filter(
            models.AppWebRule.target_value == "test_game.exe"
        ).first()
        assert refreshed_rule.used_minutes == 0

        logs_count = db.query(models.MinimalTelemetryLog).count()
        assert logs_count == 0

        refreshed_req = db.query(models.ChildRequest).filter(
            models.ChildRequest.id == req.id
        ).first()
        assert refreshed_req.status == "EXPIRED"

    finally:
        db.close()
        engine.dispose()


def test_rollover_and_usage_at_vietnam_midnight(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from app.services import curfew

    engine = create_engine(f"sqlite:///{tmp_path / 'vietnam-midnight.db'}")
    models.Base.metadata.create_all(bind=engine)
    instant = datetime(2026, 11, 20, 16, 59, 59, tzinfo=timezone.utc)

    def clock(timezone_name):
        return instant.astimezone(ZoneInfo(timezone_name))

    monkeypatch.setattr(main, "curfew_clock", clock)
    monkeypatch.setattr(curfew, "curfew_clock", clock)
    try:
        with database.SessionLocal(bind=engine) as db:
            db.add(models.DailyRollover(id=1, day="2026-11-20"))
            db.add(models.MinimalTelemetryLog(
                app_name="example.org", duration_seconds=40, timestamp=instant.replace(tzinfo=None),
            ))
            db.commit()
            assert main.web_usage_seconds(db, None) == {"example.org": 40}
            assert not main.perform_daily_reset(db, automatic=True)

            instant = datetime(2026, 11, 20, 17, 0, tzinfo=timezone.utc)
            assert main.web_usage_seconds(db, None) == {}
            db.add(models.MinimalTelemetryLog(
                app_name="example.org", duration_seconds=10, timestamp=instant.replace(tzinfo=None),
            ))
            db.commit()
            assert main.perform_daily_reset(db, automatic=True)
            assert main.web_usage_seconds(db, None) == {"example.org": 10}
            assert db.query(models.MinimalTelemetryLog).count() == 1
    finally:
        engine.dispose()


def test_reset_usage_endpoint(client, mock_db, monkeypatch):
    rule = models.AppWebRule(used_minutes=45)
    mock_db.query_results[models.AppWebRule] = [rule]
    broadcast = AsyncMock()
    monkeypatch.setattr(main.manager, "broadcast_json", broadcast)
    query = MagicMock(wraps=mock_db.query)
    monkeypatch.setattr(mock_db, "query", query)

    res = client.post("/reset/usage")

    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert rule.used_minutes == 0
    assert models.ChildRequest not in [call.args[0] for call in query.call_args_list]
    mock_db.commit.assert_called_once()
    broadcast.assert_awaited_once()
    assert broadcast.await_args.args[0]["type"] == "USAGE_RESET"

