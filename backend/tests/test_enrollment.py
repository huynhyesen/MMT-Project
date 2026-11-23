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

        session = browser.get("/web-tracking/session").json()
        extension.headers["Authorization"] = f"Bearer {session['token']}"
        assert browser.get("/web-tracking/policy").status_code == 401
        assert "lesson.example" not in extension.get("/web-tracking/policy").json()["targets"]

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

        policy = extension.get("/web-tracking/policy", headers={"Origin": "chrome-extension://test"})
        assert policy.status_code == 200 and "lesson.example" in policy.json()["targets"]
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
        explicit = parent.post("/rules/", json={
            "rule_type": "WEBSITE", "target_value": "https://blocked.example", "action": "BLOCK",
        })
        assert explicit.status_code == 201
        policy = extension.get("/web-tracking/policy").json()
        assert "blocked.example" in policy["blocked"]
        assert "porn.example" in policy["blocked"]
        assert "lesson.example" in policy["targets"]
        with database.SessionLocal() as db:
            db.add(models.AppWebRule(
                device_id=device_id, rule_type="WEBSITE", target_value="sub.blocked.example", action="ALLOW",
            ))
            db.commit()
        policy = extension.get("/web-tracking/policy").json()
        assert "sub.blocked.example" not in policy["targets"]
        assert extension.post("/web-tracking/usage", json={
            "host": "sub.blocked.example", "duration_seconds": 15,
        }).status_code == 403
        assert parent.delete("/rules/" + explicit.json()["id"]).status_code == 200
        assert "blocked.example" not in extension.get("/web-tracking/policy").json()["blocked"]

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


def test_youtube_approval_counts_as_entertainment(parent_credentials, monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from agent import blocker
    from agent.web_policy import blocked_hosts_for_agent

    engine = create_engine(f"sqlite:///{tmp_path / 'youtube.db'}")
    models.Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    hosts_file = tmp_path / "hosts"
    manual_entry = "192.0.2.1 www.youtube.com # local override\n"
    hosts_file.write_text(manual_entry)
    monkeypatch.setattr(blocker, "HOSTS_PATH", str(hosts_file))
    monkeypatch.setattr(blocker, "MANAGED_DOMAINS", set())
    try:
        with (
            TestClient(main.app, headers=basic(parent_credentials)) as parent,
            TestClient(main.app) as agent,
            TestClient(main.app) as child_browser,
            TestClient(main.app) as extension,
        ):
            assert parent.post("/curfew/", json={"bedtime": "00:00", "wakeup_time": "00:00"}).status_code == 200
            profile, credential = enroll(parent, agent, "YouTube test", "mmt-youtube")
            device_id, token = credential.split(".")
            enrollment = {"Authorization": f"Bearer {device_id}.{security.dashboard_key(token)}"}
            login = child_browser.post("/children/login", headers=enrollment, json={
                "child_id": profile["id"], "pin": "2580",
            })
            assert login.status_code == 200

            before = blocked_hosts_for_agent(agent.get("/rules/").json())
            assert "youtube.com" in before
            blocker.block_websites(before)
            assert "127.0.0.1 youtube.com # MMT_BLOCK" in hosts_file.read_text()

            pending = child_browser.post("/requests/", json={
                "request_type": "PERMISSION_WEB", "target_detail": "https://www.youtube.com/",
                "reason_from_child": "Giải trí", "requested_minutes": 30,
            })
            assert pending.status_code == 201
            request_id = pending.json()["id"]
            assert parent.patch(f"/requests/{request_id}", json={"status": "APPROVED"}).status_code == 200

            after = blocked_hosts_for_agent(agent.get("/rules/").json())
            assert "youtube.com" not in after
            assert before - after == {"youtube.com"}
            blocker.unblock_websites(before - after)
            blocker.block_websites(after)
            assert "127.0.0.1 youtube.com # MMT_BLOCK" not in hosts_file.read_text()
            assert manual_entry in hosts_file.read_text()

            target = {"target": "https://www.youtube.com/", "rule_type": "WEBSITE"}
            permission = child_browser.post("/check-permission/", json=target).json()
            assert permission["allowed"] is True
            assert permission["time_limit_minutes"] == 30

            session = child_browser.get("/web-tracking/session").json()
            assert "youtube.com" in session["targets"]
            extension.headers["Authorization"] = f"Bearer {session['token']}"
            assert extension.post("/web-tracking/usage", json={
                "host": "www.youtube.com", "duration_seconds": 17,
            }).status_code == 201

            stats = parent.get(f"/usage-stats/?child_id={profile['id']}").json()
            [item] = stats["items"]
            assert item["app_name"] == "youtube.com"
            assert item["tag"] == "ENTERTAINMENT"
            assert item["duration_formatted"] == "17 giây"
            assert item["time_limit_minutes"] == 30
            assert stats["entertainment_seconds"] == 17
            assert stats["entertainment_formatted"] == "17 giây"

            with database.SessionLocal() as db:
                db.add(models.MinimalTelemetryLog(
                    device_id=device_id, app_name="youtube.com", domain="youtube.com", duration_seconds=1782,
                ))
                db.commit()
            assert child_browser.post("/check-permission/", json=target).json()["allowed"] is True
            assert extension.post("/web-tracking/usage", json={
                "host": "youtube.com", "duration_seconds": 1,
            }).status_code == 201
            assert child_browser.post("/check-permission/", json=target).json()["is_expired"] is True
    finally:
        engine.dispose()


def test_free_browsing_blocks_adult_domains_and_enforces_website_limits(parent_credentials, monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from agent import web_policy

    engine = create_engine(f"sqlite:///{tmp_path / 'browsing.db'}")
    models.Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(web_policy, "_additional_hosts", frozenset())
    monkeypatch.setattr(web_policy, "_next_domain_check", 0)
    feed = tmp_path / "adult-domains.txt"
    feed.write_text("example-filtered.test\n", encoding="utf-8")
    monkeypatch.setenv("MMT_ADULT_DOMAINS_FILE", str(feed))

    try:
        with (
            TestClient(main.app, headers=basic(parent_credentials)) as parent,
            TestClient(main.app) as agent,
            TestClient(main.app) as child,
            TestClient(main.app) as extension,
        ):
            assert parent.post("/curfew/", json={"bedtime": "00:00", "wakeup_time": "00:00"}).status_code == 200
            profile, credential = enroll(parent, agent, "Free browsing test", "mmt-free-browser")
            device_id, token = credential.split(".")
            assert child.post("/children/login", headers={
                "Authorization": f"Bearer {device_id}.{security.dashboard_key(token)}",
            }, json={"child_id": profile["id"], "pin": "2580"}).status_code == 200
            state = child.get("/web-tracking/session").json()
            assert state["track_unrestricted"] is True
            assert "example-filtered.test" in state["adult"]
            extension.headers["Authorization"] = f"Bearer {state['token']}"

            def access(host):
                return child.post("/check-permission/", json={"target": host, "rule_type": "WEBSITE"}).json()

            assert access("ordinary.example")["allowed"] is True
            assert extension.post("/web-tracking/usage", json={"host": "ordinary.example", "duration_seconds": 13}).status_code == 201
            report = parent.get(f"/usage-stats/?child_id={profile['id']}").json()
            assert report["unclassified_seconds"] == 13
            assert report["items"][0]["category"] == "Chưa phân loại"

            configured = parent.post("/rules/", json={
                "rule_type": "WEBSITE", "target_value": "lesson.example",
                "action": "ASK", "time_limit_minutes": 1,
            })
            assert configured.status_code == 201
            assert access("lesson.example")["requires_permission"] is True
            assert "lesson.example" in extension.get("/web-tracking/policy").json()["ask"]

            def approve(kind, minutes):
                response = child.post("/requests/", json={
                    "request_type": kind, "target_detail": "lesson.example",
                    "reason_from_child": "Bài tập", "requested_minutes": minutes,
                })
                assert response.status_code == 201, response.text
                decided = parent.patch(f"/requests/{response.json()['id']}", json={"status": "APPROVED"})
                assert decided.status_code == 200, decided.text

            approve("PERMISSION_WEBSITE", 2)
            assert access("lesson.example")["time_limit_minutes"] == 1
            receipt = extension.post("/web-tracking/usage", json={
                "host": "lesson.example", "duration_seconds": 65,
            })
            assert receipt.status_code == 201
            assert receipt.json()["recorded_seconds"] == 60
            assert receipt.json()["remaining_seconds"] == 0
            assert access("lesson.example")["is_expired"] is True
            policy = extension.get("/web-tracking/policy").json()
            assert policy["expired_usage"]["lesson.example"] == 60
            assert "lesson.example" in policy["expired"]
            approve("WEB_TIME_EXTENSION", 5)
            assert access("lesson.example")["time_limit_minutes"] == 6
            assert "lesson.example" in extension.get("/web-tracking/policy").json()["targets"]

            assert access("example-filtered.test")["allowed"] is False
            assert extension.post("/web-tracking/alert", json={"host": "ordinary.example"}).status_code == 422
            for host in ("www.example-filtered.test", "example-filtered.test"):
                response = extension.post("/web-tracking/alert", json={"host": host})
                assert response.status_code == 200
            [alert] = parent.get("/alerts/").json()
            assert alert["target_value"] == "example-filtered.test"
            assert alert["attempt_count"] == 3
            assert alert["child_name"] == "Free browsing test"

            feed.write_text("updated-filter.test\n", encoding="utf-8")
            monkeypatch.setattr(web_policy, "_next_domain_check", 0)
            policy = extension.get("/web-tracking/policy").json()
            assert policy["adult"] == ["updated-filter.test"]
    finally:
        engine.dispose()
