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


def test_approved_web_usage_and_adult_blocking(parent_credentials):
    with (
        TestClient(main.app, headers=basic(parent_credentials)) as parent,
        TestClient(main.app) as agent,
        TestClient(main.app) as browser,
        TestClient(main.app) as extension,
    ):
        child, credential = enroll(parent, agent, "Web test", "mmt-test-web")
        device_id, token = credential.split(".")
        enrollment = {"Authorization": f"Bearer {device_id}.{security.dashboard_key(token)}"}
        assert browser.get("/web-tracking/session").status_code == 401
        assert agent.get("/web-tracking/session").status_code == 401
        assert browser.post("/children/login", headers=enrollment, json={
            "child_id": child["id"], "pin": "2580",
        }).status_code == 200

        response = browser.post("/requests/", json={
            "request_type": "PERMISSION_WEB",
            "target_detail": "https://WWW.LESSON.EXAMPLE./chapter?topic=math",
            "reason_from_child": "Học bài",
            "requested_minutes": 15,
        })
        assert response.status_code == 201, response.text
        assert response.json()["target_detail"].startswith("lesson.example ")
        request_id = response.json()["id"]
        assert parent.patch(f"/requests/{request_id}", json={"status": "APPROVED"}).status_code == 200

        session = browser.get("/web-tracking/session").json()
        assert "lesson.example" in session["targets"]
        extension.headers["Authorization"] = f"Bearer {session['token']}"
        assert extension.get("/rules/").status_code == 401
        assert browser.post("/web-tracking/usage", json={
            "host": "lesson.example", "duration_seconds": 17,
        }).status_code == 401
        assert extension.post("/web-tracking/usage", headers={"Origin": "chrome-extension://test"}, json={
            "host": "www.lesson.example", "duration_seconds": 17,
        }).status_code == 201
        rules = agent.get("/rules/").json()
        rule = next(rule for rule in rules if rule["target_value"] == "lesson.example")
        assert rule["used_seconds"] == 17
        assert agent.get("/usage-stats/").json()["total_seconds"] == 17

        unsafe = "https://www.porn.example/placeholder"
        with database.SessionLocal() as db:
            # An allowance carried over from before the website policy must be overridden.
            db.add(models.AppWebRule(
                device_id=device_id, rule_type="WEBSITE", target_value="porn.example", action="ALLOW"
            ))
            db.commit()
        response = browser.post("/check-permission/", json={"target": unsafe, "rule_type": "WEBSITE"})
        assert response.json()["allowed"] is False
        assert "18+" in response.json()["reason"]
        assert browser.post("/requests/", json={
            "request_type": "PERMISSION_WEB", "target_detail": unsafe, "reason_from_child": "Mẫu kiểm thử",
        }).status_code == 422
        assert extension.post("/web-tracking/usage", json={
            "host": "porn.example", "duration_seconds": 10,
        }).status_code == 403
        assert parent.delete(f"/children/{child['id']}").status_code == 200


def test_curfew_uses_saved_timezone_for_web_access(parent_credentials, monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.services import curfew

    engine = create_engine(f"sqlite:///{tmp_path / 'curfew.db'}")
    models.Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    instant = datetime(2026, 11, 20, 16, 45, tzinfo=timezone.utc)

    def clock(timezone_name):
        return instant.astimezone(ZoneInfo(timezone_name or "Asia/Tokyo"))

    monkeypatch.setattr(curfew, "curfew_clock", clock)
    try:
        with database.SessionLocal() as db:
            db.add_all([
                models.TimeLimit(category="LEARNING", bedtime="21:30", wakeup_time="07:00"),
                models.TimeLimit(category="OVERALL", bedtime="00:55", wakeup_time="06:00"),
            ])
            db.commit()
        with (
            TestClient(main.app, headers=basic(parent_credentials)) as parent,
            TestClient(main.app) as agent,
        ):
            enroll(parent, agent, "Curfew test", "mmt-test-curfew")
            rule = parent.post("/rules/", json={
                "rule_type": "WEBSITE", "target_value": "lesson.example", "action": "ALLOW",
            })
            assert rule.status_code == 201
            website = {"target": "https://lesson.example", "rule_type": "WEBSITE"}
            legacy = agent.post("/check-permission/", json=website).json()
            assert legacy["is_curfew"] is True
            assert "01:45" in legacy["reason"]

            result = parent.post("/curfew/", json={
                "bedtime": "00:55", "wakeup_time": "06:00", "timezone": "Asia/Ho_Chi_Minh",
            })
            assert result.status_code == 200, result.text
            assert result.json() == {
                "bedtime": "00:55",
                "wakeup_time": "06:00",
                "timezone": "Asia/Ho_Chi_Minh",
                "current_time": "23:45",
                "is_within_curfew": False,
            }
            assert agent.post("/check-permission/", json=website).json()["allowed"] is True
            assert agent.get("/usage-stats/").json()["is_bedtime"] is False
            assert agent.get("/devices/mmt-test-curfew/config").json()["bedtime"] == "00:55"
            assert parent.get("/onboarding/config").json()["bedtime"] == "00:55"

            instant = datetime(2026, 11, 20, 17, 54, tzinfo=timezone.utc)
            assert agent.post("/check-permission/", json=website).json()["allowed"] is True
            instant = datetime(2026, 11, 20, 17, 55, tzinfo=timezone.utc)
            blocked = agent.post("/check-permission/", json=website).json()
            assert blocked["is_curfew"] is True
            assert "00:55" in blocked["reason"]
            assert agent.get("/usage-stats/").json()["is_bedtime"] is True
            instant = datetime(2026, 11, 20, 23, 0, tzinfo=timezone.utc)
            assert agent.post("/check-permission/", json=website).json()["allowed"] is True

            assert parent.post("/curfew/", json={"bedtime": "24:55"}).status_code == 422
            assert parent.post("/curfew/", json={"timezone": "Invalid/Zone"}).status_code == 422
            assert parent.get("/curfew/").json()["timezone"] == "Asia/Ho_Chi_Minh"
    finally:
        engine.dispose()
