from base64 import b64encode

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from app import database, main, models, security


def basic(credentials):
    return {"Authorization": "Basic " + b64encode(":".join(credentials).encode()).decode()}


def enroll(parent, agent, name, hwid):
    created = parent.post("/children/", json={"name": name, "pin": "2580", "device_name": f"PC {name}"})
    assert created.status_code == 201, created.text
    profile = created.json()
    assert "pin" not in profile
    assert not profile["device"]["is_paired"]
    code = profile["device"]["pairing_code"]
    paired = agent.post("/devices/pair", json={"device_hwid": hwid, "pairing_code": code})
    assert paired.status_code == 200, paired.text
    assert agent.post("/devices/pair", json={"device_hwid": "extra", "pairing_code": code}).status_code == 404
    credential = paired.json()["device_credential"]
    agent.headers["Authorization"] = f"Bearer {credential}"
    return profile, credential


def test_one_device_per_child_and_scoped_access(parent_credentials):
    with (
        TestClient(main.app, headers=basic(parent_credentials)) as parent,
        TestClient(main.app) as first_agent,
        TestClient(main.app) as second_agent,
        TestClient(main.app) as child_browser,
    ):
        assert parent.post("/children/", json={"name": "Thiếu PIN"}).status_code == 422
        first, credential = enroll(parent, first_agent, "An", "mmt-test-an")
        second, _ = enroll(parent, second_agent, "Bình", "mmt-test-binh")
        duplicate = parent.post("/devices/create", json={"child_profile_id": first["id"], "device_name": "Extra"})
        assert duplicate.status_code == 409
        assert child_browser.post("/reset/usage").status_code == 401
        assert first_agent.post("/control/lock").status_code == 401
        assert first_agent.get("/devices/mmt-test-binh/config").status_code == 404
        assert first_agent.get("/devices/mmt-test-an/config").status_code == 200
        assert child_browser.get("/children/").status_code == 401

        device_id, token = credential.split(".")
        enrollment = {"Authorization": f"Bearer {device_id}.{security.dashboard_key(token)}"}
        assert child_browser.get("/children/assigned", headers=enrollment).json()["id"] == first["id"]
        assert child_browser.post("/children/login", headers=enrollment, json={
            "child_id": second["id"], "pin": "2580",
        }).status_code == 403
        assert child_browser.get("/children/active").status_code == 401
        assert child_browser.post("/children/login", headers=enrollment, json={
            "child_id": first["id"], "pin": "2580",
        }).status_code == 200
        assert child_browser.get("/children/active").json()["id"] == first["id"]

        with database.SessionLocal() as db:
            stored = db.get(models.ChildProfile, first["id"]).pin
            assert stored != "2580" and security.verify_pin("2580", stored)

        assert first_agent.post("/telemetry/", json={"app_name": "example.org", "duration_seconds": 60}).status_code == 201
        assert first_agent.get("/usage-stats/").json()["total_seconds"] == 60
        assert second_agent.get("/usage-stats/").json()["total_seconds"] == 0

        request = child_browser.post("/requests/", json={
            "request_type": "TIME_EXTENSION", "target_detail": "", "reason_from_child": "Học bài", "requested_minutes": 15,
        })
        assert request.status_code == 201, request.text
        assert second_agent.get("/requests/").json() == []
        assert parent.patch(f"/requests/{request.json()['id']}", json={"status": "APPROVED"}).status_code == 200
        assert first_agent.get("/usage-stats/").json()["daily_limit_minutes"] == 135
        assert second_agent.get("/usage-stats/").json()["daily_limit_minutes"] == 120

        with pytest.raises(WebSocketDisconnect):
            with child_browser.websocket_connect("/ws/agent/parent_dashboard"):
                pytest.fail("A child must not enter the parent channel")
        with first_agent.websocket_connect("/ws/relay/mmt-test-an") as socket:
            socket.send_json({"type": "PING"})
            assert socket.receive_json()["type"] == "PONG"
            replaced = parent.post(f"/children/{first['id']}/pairing")
            assert replaced.status_code == 200
            assert replaced.json()["id"] == device_id
        assert first_agent.get("/usage-stats/").status_code == 401
        assert child_browser.get("/children/active").status_code == 401

        assert parent.delete(f"/children/{first['id']}").status_code == 200
        assert parent.delete(f"/children/{second['id']}").status_code == 200


def test_admin_requires_configuration_and_same_origin(parent_credentials, monkeypatch):
    with TestClient(main.app) as visitor:
        assert visitor.get("/parent/").status_code == 401
        assert visitor.post("/relay/command", json={"target_hwid": "example"}).status_code == 401
        assert visitor.post("/reset/usage", headers={
            **basic(parent_credentials), "Origin": "https://another.example",
        }).status_code == 403
        monkeypatch.delenv("MMT_PARENT_PASSWORD")
        assert visitor.get("/parent/").status_code == 503
