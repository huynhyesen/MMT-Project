import os
import logging
import asyncio
import time
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from contextlib import asynccontextmanager
import json
from . import database, models, schemas, security
from fastapi.middleware.cors import CORSMiddleware

from .services.classification import (
    extract_target_name,
    is_system_process,
    classify_item
)

from .services.formatters import (
    format_remaining,
    format_usage_duration,
)

from .services.curfew import (
    current_curfew, curfew_clock, household_timezone, store_curfew, usage_day_start
)
from .services.realtime import manager
from agent.ai_filter.text_analyzer import AITextAnalyzer
from agent.web_policy import additional_adult_hosts, is_adult_host, normalize_host


# Tự động tạo bảng database nếu chưa tồn tại
models.Base.metadata.create_all(bind=database.engine)

def auto_migrate_db():
    """Bổ sung các cột còn thiếu trong SQLite mà không làm mất dữ liệu."""
    import sqlite3

    conn = sqlite3.connect(database.DB_PATH)

    try:
        cursor = conn.cursor()

        # Migration cho bảng devices.
        cursor.execute("PRAGMA table_info(devices)")
        existing_device_cols = {row[1] for row in cursor.fetchall()}

        if existing_device_cols:
            device_columns = {
                "user_id": "VARCHAR(50)",
                "device_hwid": "VARCHAR(100)",
                "pairing_code": "VARCHAR(20)",
                "pairing_expires_at": "DATETIME",
                "pairing_token": "VARCHAR(100)",
                "is_paired": "BOOLEAN DEFAULT 0",
                "child_profile_id": "INTEGER",
                "platform": "VARCHAR(50) DEFAULT 'Linux'",
                "ip_address": "VARCHAR(50)",
                "anti_tamper_active": "BOOLEAN DEFAULT 1",
                "content_filter_active": "BOOLEAN DEFAULT 1",
                "last_seen": "DATETIME",
                "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
            }

            for column_name, column_type in device_columns.items():
                if column_name not in existing_device_cols:
                    cursor.execute(
                        f"ALTER TABLE devices ADD COLUMN {column_name} {column_type}"
                    )
                    logging.info(
                        "Database migration: added devices.%s",
                        column_name,
                    )

        # Migration cho bảng alert_logs (nếu bảng đã tồn tại).
        cursor.execute("PRAGMA table_info(alert_logs)")
        existing_alert_cols = {row[1] for row in cursor.fetchall()}

        if existing_alert_cols and "category" not in existing_alert_cols:
            cursor.execute(
                "ALTER TABLE alert_logs "
                "ADD COLUMN category VARCHAR(50) "
                "DEFAULT 'UNAPPROVED_ACCESS'"
            )
            logging.info("Database migration: added alert_logs.category")

        if "device_id" not in existing_alert_cols:
            cursor.execute("ALTER TABLE alert_logs ADD COLUMN device_id VARCHAR REFERENCES devices(id)")
        if "attempt_count" not in existing_alert_cols:
            cursor.execute("ALTER TABLE alert_logs ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 1")

        for table in ("minimal_telemetry_logs", "child_requests"):
            columns = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
            if "device_id" not in columns:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN device_id VARCHAR REFERENCES devices(id)")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_device_id ON {table}(device_id)")

        # Keep the paired device first when upgrading a database with duplicate assignments.
        cursor.execute("""
            UPDATE devices
            SET child_profile_id = NULL, is_paired = 0, status = 'OFFLINE',
                pairing_code = NULL, pairing_expires_at = NULL, pairing_token = NULL,
                device_hwid = NULL
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY child_profile_id
                        ORDER BY is_paired DESC, last_seen DESC, created_at DESC, id
                    ) AS position FROM devices WHERE child_profile_id IS NOT NULL
                ) WHERE position > 1
            )
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_child_profile ON devices(child_profile_id)")
        for child_id, pin in cursor.execute("SELECT id, pin FROM child_profiles").fetchall():
            if pin and not security.is_pin_hash(pin):
                cursor.execute("UPDATE child_profiles SET pin = ? WHERE id = ?", (security.hash_pin(pin), child_id))

        conn.commit()

    except sqlite3.Error:
        conn.rollback()
        logging.exception(
            "Database migration failed for %s",
            database.DB_PATH,
        )
        raise

    finally:
        conn.close()

auto_migrate_db()

# Kích hoạt dịch vụ tự động nhận diện trên mạng Wi-Fi (UDP LAN Discovery)
try:
    import sys
    AGENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "agent")
    if AGENT_DIR not in sys.path:
        sys.path.insert(0, AGENT_DIR)
    from lan_discovery import start_discovery_responder
    start_discovery_responder(http_port=8008)
except Exception:
    pass

def clear_usage(db: Session, cutoff=None):
    logs = db.query(models.MinimalTelemetryLog)
    if cutoff is not None:
        logs = logs.filter(models.MinimalTelemetryLog.timestamp < cutoff)
    logs.delete()
    for rule in db.query(models.AppWebRule).all():
        rule.used_minutes = 0


def perform_daily_reset(db: Session, today_str: Optional[str] = None, *, automatic=False):
    """Reset daily counters and pending requests in one transaction."""
    timezone_name = household_timezone(db)
    day = date.fromisoformat(today_str) if today_str else curfew_clock(timezone_name).date()
    today_str = day.isoformat()
    cutoff = usage_day_start(timezone_name, day)
    if automatic:
        previous_day = db.get(models.DailyRollover, 1)
        if previous_day and previous_day.day >= today_str:
            return False
        # Initialize a migrated database only after checking for stale activity.
        if previous_day is None:
            stale = db.query(models.MinimalTelemetryLog.id).filter(
                models.MinimalTelemetryLog.timestamp < cutoff
            ).first() or db.query(models.ChildRequest.id).filter(
                models.ChildRequest.status == "PENDING",
                models.ChildRequest.created_at < cutoff,
            ).first()
            if not stale:
                db.execute(sqlite_insert(models.DailyRollover).values(id=1, day=today_str)
                           .on_conflict_do_nothing(index_elements=["id"]))
                db.commit()
                return False
    claim = sqlite_insert(models.DailyRollover).values(id=1, day=today_str)
    claimed = db.execute(claim.on_conflict_do_update(
        index_elements=["id"],
        set_={"day": today_str},
        where=models.DailyRollover.day < today_str if automatic else None,
    ))
    if automatic and claimed.rowcount != 1:
        db.rollback()
        return False
    clear_usage(db, cutoff if automatic else None)
    pending = db.query(models.ChildRequest).filter(models.ChildRequest.status == "PENDING")
    if automatic:
        pending = pending.filter(models.ChildRequest.created_at < cutoff)
    pending.update({models.ChildRequest.status: "EXPIRED"})
    db.commit()
    return True


async def notify_daily_reset():
    await manager.broadcast_json({"type": "DAILY_RESET_TRIGGERED"})


async def daily_rollover_worker():
    while True:
        await asyncio.sleep(15)
        try:
            with database.SessionLocal() as db:
                if perform_daily_reset(db, automatic=True):
                    await notify_daily_reset()
        except Exception:
            logging.exception("Daily reset failed; will retry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    with database.SessionLocal() as db:
        perform_daily_reset(db, automatic=True)
    rollover_task = asyncio.create_task(daily_rollover_worker())
    try:
        yield
    finally:
        rollover_task.cancel()
        try:
            await rollover_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Parental Control Backend", version="1.3.0", lifespan=lifespan)

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

DEVICE_API = {
    ("GET", "/children/active"), ("GET", "/usage-stats"), ("GET", "/rules"),
    ("GET", "/curfew"), ("GET", "/requests"), ("POST", "/requests"),
    ("POST", "/telemetry"), ("POST", "/check-permission"), ("POST", "/classify"),
    ("POST", "/alerts"), ("POST", "/ai/content-check"),
}


@app.middleware("http")
async def authorize_request(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    method = request.method
    if method == "OPTIONS":
        return await call_next(request)
    if (method, path) in {
        ("GET", "/web-tracking/policy"), ("POST", "/web-tracking/usage"),
        ("POST", "/web-tracking/alert"),
    }:
        request.state.device = security.resolve_device(request, web_tracking=True)
        if request.state.device:
            return await call_next(request)
        return JSONResponse({"detail": "Phiên theo dõi web đã hết hạn."}, status_code=401)
    if (method, path) == ("GET", "/web-tracking/session"):
        request.state.device = security.resolve_device(request, child_only=True)
        if request.state.device and security.same_origin(request):
            return await call_next(request)
        return JSONResponse({"detail": "Cần đăng nhập hồ sơ trẻ."}, status_code=401)
    if method not in {"GET", "HEAD"} and not security.same_origin(request):
        return JSONResponse({"detail": "Nguồn yêu cầu không hợp lệ."}, status_code=403)
    if (method in {"GET", "HEAD"} and (
        path in {"/", "/favicon.ico"} or path == "/child" or
        path.startswith(("/child/", "/assets/"))
    )) or (method, path) == ("POST", "/devices/pair"):
        return await call_next(request)
    if (method, path) in {("GET", "/children/assigned"), ("POST", "/children/login")}:
        request.state.device = security.resolve_device(request, enrollment=True)
        if request.state.device:
            return await call_next(request)
        return JSONResponse({"detail": "Hãy mở dashboard từ Agent đã ghép nối."}, status_code=401)
    parent_console = request.headers.get("x-mmt-console") == "parent"
    if not parent_console and ((method, path) in DEVICE_API or (method == "GET" and path.startswith("/devices/") and path.endswith("/config"))):
        request.state.device = security.resolve_device(
            request, agent_only=path.endswith("/config")
        )
        if request.state.device:
            return await call_next(request)
    parent = security.parent_session(request)
    if not parent:
        if not os.getenv("MMT_PARENT_PASSWORD"):
            return JSONResponse({"detail": "Cần cấu hình MMT_PARENT_PASSWORD trên máy chủ."}, status_code=503)
        headers = {"WWW-Authenticate": 'Basic realm="MMT Parent"'} if path == "/parent" else {}
        return JSONResponse({"detail": "Cần xác thực phụ huynh."}, status_code=401, headers=headers)
    response = await call_next(request)
    if request.cookies.get(security.PARENT_COOKIE) != parent:
        response.set_cookie(
            security.PARENT_COOKIE, parent, httponly=True, samesite="strict",
            secure=request.url.scheme == "https", max_age=8 * 3600,
        )
    return response


def client_device(request: Request):
    return getattr(request.state, "device", None)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/parent", "/child")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Đường dẫn thư mục static UI
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PARENT_APP_DIR = os.path.join(BASE_DIR, "parent-app")
CHILD_APP_DIR = os.path.join(BASE_DIR, "child-app")

app.mount("/assets", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "assets")), name="dashboard-assets")

if os.path.exists(PARENT_APP_DIR):
    app.mount("/parent", StaticFiles(directory=PARENT_APP_DIR, html=True), name="parent-app")
if os.path.exists(CHILD_APP_DIR):
    app.mount("/child", StaticFiles(directory=CHILD_APP_DIR, html=True), name="child-app")


@app.get("/")
def read_root(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        html_content = """
        <!DOCTYPE html>
        <html lang="vi">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>MMT - Hệ Thống Quản Lý Máy Tính Trẻ Em</title>
            <link rel="stylesheet" href="/parent/style.css">
            <link rel="stylesheet" href="/assets/dashboard.css">
        </head>
        <body class="bg-slate-900 text-slate-100 min-h-screen flex items-center justify-center p-4">
            <div class="max-w-md w-full bg-slate-800 border border-slate-700 rounded-3xl p-6 md:p-8 text-center shadow-2xl space-y-6">
                <div class="w-16 h-16 bg-blue-500/20 text-blue-400 rounded-2xl flex items-center justify-center text-3xl mx-auto border border-blue-500/30">
                    🛡️
                </div>
                <div>
                    <h1 class="text-2xl font-bold text-white">MMT Parental Control</h1>
                    <p class="text-xs text-slate-400 mt-1">Cổng điều khiển tương thích Điện thoại, Máy tính bảng & Máy tính</p>
                </div>
                <div class="space-y-3">
                    <a href="/parent/" class="flex items-center justify-between p-4 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 rounded-2xl font-bold text-sm shadow-md transition group">
                        <div class="flex items-center gap-3">
                            <span class="text-xl">🧙‍♂️</span>
                            <div class="text-left">
                                <div>Trạm Điều Khiển Phụ Huynh</div>
                                <div class="text-[11px] text-blue-200 font-normal">Duyệt web, đặt giờ, reset & giám sát</div>
                            </div>
                        </div>
                        <span class="group-hover:translate-x-1 transition">➔</span>
                    </a>
                    <a href="/child/" class="flex items-center justify-between p-4 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 rounded-2xl font-bold text-sm shadow-md transition group">
                        <div class="flex items-center gap-3">
                            <span class="text-xl">🚀</span>
                            <div class="text-left">
                                <div>Góc Học Tập & Giải Trí Của Con</div>
                                <div class="text-[11px] text-emerald-200 font-normal">Xem đếm ngược, web mở & xin thêm giờ</div>
                            </div>
                        </div>
                        <span class="group-hover:translate-x-1 transition">➔</span>
                    </a>
                    <a href="/docs" target="_blank" class="flex items-center justify-between p-3.5 bg-slate-700/60 hover:bg-slate-700 rounded-2xl text-xs font-semibold text-slate-300 transition">
                        <span class="flex items-center gap-2"><span>📚</span> Tài liệu API (Swagger UI)</span>
                        <span>↗</span>
                    </a>
                </div>
                <div class="text-[11px] text-slate-500 pt-2 border-t border-slate-700">
                    Đang hoạt động trên cổng 8000 • Hỗ trợ đa thiết bị qua LAN Wi-Fi
                </div>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content)
    return {
        "message": "Parental Control Backend đang hoạt động thành công!",
        "parent_portal": "/parent/",
        "child_portal": "/child/",
        "docs": "/docs"
    }

# ==========================================
# QUẢN LÝ KẾT NỐI WEBSOCKET THỜI GIAN THỰC
# ==========================================


@app.websocket("/ws/agent/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    if not security.same_origin(websocket):
        await websocket.close(code=1008)
        return
    if device_id == "parent_dashboard" and security.parent_session(websocket):
        channel = "parent_dashboard"
    elif device_id == "child_pc_01" and (device := security.resolve_device(websocket, child_only=True)):
        channel = device.device_hwid
    else:
        await websocket.close(code=1008)
        return
    await manager.connect(channel, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)

# ==========================================
# 0. ĐIỀU KHIỂN TỪ XA QUA REST API
# ==========================================
@app.post("/control/lock")
async def remote_lock():
    await manager.broadcast_json({
        "type": "LOCK_MACHINE",
        "sender": "parent_dashboard",
        "message": "🔒 Máy tính đã bị khóa bởi Phụ huynh!"
    })
    return {"status": "success", "message": "Đã gửi lệnh khóa máy!"}

@app.post("/control/unlock")
async def remote_unlock():
    await manager.broadcast_json({
        "type": "UNLOCK_MACHINE",
        "sender": "parent_dashboard",
        "message": "🔓 Máy tính đã được mở khóa bởi Phụ huynh!"
    })
    return {"status": "success", "message": "Đã gửi lệnh mở khóa máy!"}

@app.post("/control/message")
async def remote_message(payload: dict):
    msg = payload.get("message", "")
    await manager.broadcast_json({
        "type": "PARENT_MESSAGE",
        "sender": "parent_dashboard",
        "message": msg
    })
    return {"status": "success", "message": "Đã gửi thông điệp tới máy con!"}


####    API 

from .routers import devices, relay 

app.include_router(devices.router)

app.include_router(relay.router)

######




text_filter = AITextAnalyzer()


@app.post("/ai/content-check", response_model=schemas.ContentFilterResult)
def api_content_check(req: schemas.ContentFilterAnalysisRequest):
    """Check an explicitly supplied hostname or text against the available rules."""
    if req.image_base64 is not None:
        raise HTTPException(422, "Bản hiện tại hỗ trợ tên miền và văn bản. Phân tích ảnh chưa khả dụng.")

    host = normalize_host(req.url)
    text = " ".join(part for part in (req.window_title, req.text_content) if part).strip()
    if not host and not text:
        raise HTTPException(422, "Cần nhập tên miền hợp lệ hoặc văn bản để kiểm tra.")
    if host and is_adult_host(host):
        return schemas.ContentFilterResult(
            is_safe=False, violation_category="ADULT",
            reason="Tên miền thuộc bộ lọc 18+.", suggested_action="BLOCK_AND_CLOSE",
        )

    result = text_filter.analyze(text)
    return schemas.ContentFilterResult(
        is_safe=result["is_safe"],
        violation_category=result.get("category"),
        confidence=result.get("confidence", 0.0),
        reason=result.get("reason"),
        suggested_action=result.get("suggested_action", "ALLOW"),
    )


# ==========================================
# 1. THIẾT LẬP LẦN ĐẦU (ONBOARDING SETUP)
# ==========================================
@app.get("/onboarding/config")
def get_onboarding_config(db: Session = Depends(database.get_db)):
    """Lấy cấu hình quy chuẩn gốc."""
    learn_limit = db.query(models.TimeLimit).filter(models.TimeLimit.category == "LEARNING").first()
    ent_limit = db.query(models.TimeLimit).filter(models.TimeLimit.category == "ENTERTAINMENT").first()
    
    curfew = current_curfew(db)
    rules = db.query(models.AppWebRule).all()
    allowed = [r.target_value for r in rules if r.action == "ALLOW"]
    blocked = [r.target_value for r in rules if r.action == "BLOCK"]

    return {
        "learning_limit_minutes": learn_limit.daily_limit_minutes if learn_limit else 180,
        "entertainment_limit_minutes": ent_limit.daily_limit_minutes if ent_limit else 45,
        "bedtime": curfew.bedtime,
        "wakeup_time": curfew.wakeup_time,
        "allowed_sites": allowed or [],
        "blocked_sites": blocked or ["youtube.com", "facebook.com", "discord.com", "tiktok.com"]
    }

@app.post("/onboarding/setup")
async def save_onboarding_setup(config: schemas.OnboardingSetupRequest, db: Session = Depends(database.get_db)):
    """Lưu cấu hình quy chuẩn gốc từ Onboarding Setup Wizard."""
    # Cập nhật hoặc tạo TimeLimit
    learn_limit = db.query(models.TimeLimit).filter(models.TimeLimit.category == "LEARNING").first()
    if not learn_limit:
        learn_limit = models.TimeLimit(
            category="LEARNING", 
            daily_limit_minutes=config.learning_limit_minutes, 
            bedtime=config.bedtime,
            wakeup_time=config.wakeup_time or "06:00"
        )
        db.add(learn_limit)
    else:
        learn_limit.daily_limit_minutes = config.learning_limit_minutes
        learn_limit.bedtime = config.bedtime
        learn_limit.wakeup_time = config.wakeup_time or "06:00"

    ent_limit = db.query(models.TimeLimit).filter(models.TimeLimit.category == "ENTERTAINMENT").first()
    if not ent_limit:
        ent_limit = models.TimeLimit(
            category="ENTERTAINMENT", 
            daily_limit_minutes=config.entertainment_limit_minutes, 
            bedtime=config.bedtime,
            wakeup_time=config.wakeup_time or "06:00"
        )
        db.add(ent_limit)
    else:
        ent_limit.daily_limit_minutes = config.entertainment_limit_minutes
        ent_limit.bedtime = config.bedtime
        ent_limit.wakeup_time = config.wakeup_time or "06:00"

    # Xóa và nạp lại quy tắc Web & App
    db.query(models.AppWebRule).delete()
    for site in config.allowed_sites:
        clean = extract_target_name(site)
        if clean:
            r_type = "WEBSITE" if "." in clean else "APP"
            db.add(models.AppWebRule(rule_type=r_type, target_value=clean, action="ALLOW", time_limit_minutes=config.learning_limit_minutes, used_minutes=0))

    for site in config.blocked_sites:
        clean = extract_target_name(site)
        if clean:
            r_type = "WEBSITE" if "." in clean else "APP"
            db.add(models.AppWebRule(rule_type=r_type, target_value=clean, action="BLOCK", time_limit_minutes=config.entertainment_limit_minutes, used_minutes=0))

    store_curfew(db, config.bedtime, config.wakeup_time)
    db.commit()

    await manager.broadcast_json({
        "type": "ONBOARDING_UPDATED",
        "message": "Cấu hình gốc của hệ thống đã được cập nhật thành công!"
    })

    return {"status": "success", "message": "Đã lưu cấu hình gốc thành công!"}

# ==========================================
# 3. QUẢN LÝ THIẾT BỊ VÀ TELEMETRY (NT2)
# ==========================================
def device_rules(db, device):
    query = db.query(models.AppWebRule)
    if device:
        query = query.filter(
            models.AppWebRule.device_id.is_(None) | (models.AppWebRule.device_id == device.id)
        ).order_by(models.AppWebRule.device_id.is_not(None).desc())
    return query


def owned_rows(query, model, device):
    return query.filter(model.device_id == device.id) if device else query


def effective_web_rules(db, device):
    rules = {}
    for rule in device_rules(db, device).filter(models.AppWebRule.rule_type == "WEBSITE"):
        host = normalize_host(rule.target_value)
        if host:
            rules.setdefault(host, rule)
    return rules


def web_rule_for_host(host, rules):
    labels = host.split(".")
    for index in range(len(labels)):
        rule = rules.get(".".join(labels[index:]))
        if rule and rule.action == "BLOCK":
            return rule
    return rules.get(host)


def todays_usage(db, device, query, timezone_name=None):
    cutoff = usage_day_start(timezone_name or household_timezone(db))
    return owned_rows(query, models.MinimalTelemetryLog, device).filter(
        models.MinimalTelemetryLog.timestamp >= cutoff
    )


def web_usage_seconds(db, device, timezone_name=None):
    logs = todays_usage(db, device, db.query(
        models.MinimalTelemetryLog.app_name, func.sum(models.MinimalTelemetryLog.duration_seconds)
    ), timezone_name).group_by(models.MinimalTelemetryLog.app_name)
    return dict(logs.all())


def remaining_web_seconds(rule, used_seconds):
    limit = rule.time_limit_minutes if rule else 0
    return max(0, limit * 60 - used_seconds) if limit else None


def browser_web_policy(db, device):
    rules = effective_web_rules(db, device)
    curfew = current_curfew(db)
    usage = web_usage_seconds(db, device, curfew.timezone)
    policy = {
        "targets": [], "blocked": [], "ask": [], "expired": [],
        "remaining": {}, "expired_usage": {}, "track_unrestricted": True, "adult": sorted(additional_adult_hosts()),
    }
    for host, rule in rules.items():
        effective = web_rule_for_host(host, rules)
        if effective.action == "BLOCK" or is_adult_host(host):
            policy["blocked"].append(host)
        elif effective.action == "ASK":
            policy["ask"].append(host)
        elif effective.action == "ALLOW":
            remaining = remaining_web_seconds(rule, usage.get(host, 0))
            if remaining == 0:
                policy["expired"].append(host)
                policy["expired_usage"][host] = usage.get(host, 0)
            else:
                policy["targets"].append(host)
                if remaining is not None:
                    policy["remaining"][host] = remaining

    profile = db.get(models.ChildProfile, device.child_profile_id)
    daily_limit = (profile.daily_limit_minutes or 120) if profile else 120
    daily_remaining = max(0, daily_limit * 60 - sum(usage.values()))
    policy["daily_remaining"] = daily_remaining
    policy["daily_used_seconds"] = sum(usage.values())
    policy["restriction"] = (
        "curfew" if curfew.is_within_curfew else "daily" if daily_remaining == 0 else None
    )
    return policy


@app.get("/web-tracking/session")
def web_tracking_session(request: Request, db: Session = Depends(database.get_db)):
    device = client_device(request)
    return JSONResponse(
        {"token": security.web_tracking_token(device), **browser_web_policy(db, device)},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/web-tracking/policy")
def web_tracking_policy(request: Request, db: Session = Depends(database.get_db)):
    return JSONResponse(
        browser_web_policy(db, client_device(request)),
        headers={"Cache-Control": "no-store"},
    )


@app.post("/web-tracking/usage", status_code=201)
def record_web_usage(data: schemas.WebUsageCreate, request: Request, db: Session = Depends(database.get_db)):
    device = client_device(request)
    host = normalize_host(data.host)
    rule = web_rule_for_host(host, effective_web_rules(db, device))
    if not host or is_adult_host(host) or (rule and rule.action != "ALLOW"):
        raise HTTPException(403, "Tên miền chưa được phép theo dõi.")

    usage = web_usage_seconds(db, device)
    remaining = remaining_web_seconds(rule, usage.get(host, 0))
    profile = db.get(models.ChildProfile, device.child_profile_id)
    daily_limit = (profile.daily_limit_minutes or 120) if profile else 120
    daily_remaining = max(0, daily_limit * 60 - sum(usage.values()))
    counted_seconds = min(data.duration_seconds, daily_remaining, remaining if remaining is not None else data.duration_seconds)
    if counted_seconds:
        db.add(models.MinimalTelemetryLog(
            device_id=device.id, app_name=host, domain=host, duration_seconds=counted_seconds
        ))
        db.commit()
    return {
        "status": "success",
        "recorded_seconds": counted_seconds,
        "used_seconds": usage.get(host, 0) + counted_seconds,
        "daily_used_seconds": sum(usage.values()) + counted_seconds,
        "remaining_seconds": remaining - counted_seconds if remaining is not None else None,
        "daily_remaining": daily_remaining - counted_seconds,
    }


@app.post("/web-tracking/alert")
async def record_adult_website_attempt(data: schemas.WebHost, request: Request, db: Session = Depends(database.get_db)):
    host = normalize_host(data.host)
    if not host or not is_adult_host(host):
        raise HTTPException(422, "Tên miền chưa được bộ lọc nhận diện là 18+.")

    device = client_device(request)
    await log_adult_website_attempt(host, device, db)
    return {"status": "success"}


async def log_adult_website_attempt(host, device, db):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    alert = db.query(models.AlertLog).filter_by(
        device_id=device.id, target_value=host, category="ADULT_WEBSITE"
    ).filter(models.AlertLog.timestamp >= now - timedelta(minutes=5)).order_by(
        models.AlertLog.timestamp.desc()
    ).first()
    first_attempt = alert is None
    if first_attempt:
        alert = models.AlertLog(
            device_id=device.id, target_value=host, category="ADULT_WEBSITE",
            reason="Tiện ích đã chặn tên miền 18+.", is_web=True, timestamp=now,
        )
        db.add(alert)
    else:
        alert.attempt_count += 1
        alert.timestamp = now
    db.commit()

    profile = db.get(models.ChildProfile, device.child_profile_id)
    await manager.send_to_device("parent_dashboard", {
        "type": "ADULT_WEBSITE_BLOCKED", "domain": host,
        "child_name": profile.name if profile else None,
        "first_attempt": first_attempt,
    })


@app.post("/telemetry/", status_code=201)
def receive_telemetry(data: schemas.TelemetryCreate, request: Request, db: Session = Depends(database.get_db)):
    """Nhận siêu dữ liệu thời lượng hoạt động từ Agent hoặc Web tracker."""
    clean_target = extract_target_name(data.app_name) or data.app_name
    if is_system_process(clean_target):
        return {"status": "ignored", "message": "Tiến trình hệ thống bị bỏ qua."}
        
    device = client_device(request)
    db_log = models.MinimalTelemetryLog(
        device_id=device.id if device else None,
        app_name=clean_target,
        domain=data.domain,
        duration_seconds=data.duration_seconds
    )
    db.add(db_log)
    db.flush()

    # Đồng bộ used_minutes cho quy tắc (nếu có)
    if not device:  # Keep the legacy aggregate counter for parent-originated telemetry.
        total = db.query(func.sum(models.MinimalTelemetryLog.duration_seconds))
        target_total_sec = todays_usage(db, device, total).filter(
            models.MinimalTelemetryLog.app_name == clean_target
        ).scalar() or 0
        matched_rule = db.query(models.AppWebRule).filter_by(target_value=clean_target).first()
        if matched_rule:
            matched_rule.used_minutes = target_total_sec // 60
    db.commit()

    return {"status": "success", "message": "Telemetry logged safely.", "target": clean_target}

# ==========================================
# 3.1. KIỂM TRA QUYỀN TRUY CẬP VÀ PHÂN LOẠI
# ==========================================
@app.post("/check-permission/")
async def check_permission(payload: schemas.CheckPermissionRequest, request: Request, db: Session = Depends(database.get_db)):
    """Kiểm tra một web/app có được phép hay không, đồng thời phân loại và trả về hạn mức."""
    device = client_device(request)
    raw_target = payload.target
    host = normalize_host(raw_target)
    is_web = payload.rule_type == "WEBSITE" or (payload.rule_type is None and host and not host.endswith(".exe"))
    target = host if is_web else extract_target_name(raw_target)
    if not target:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp địa chỉ web hoặc tên ứng dụng")

    classification = classify_item(target, is_web=bool(is_web))
    if is_web and is_adult_host(host):
        if device:
            await log_adult_website_attempt(host, device, db)
        return {"allowed": False, "target": host, "classification": classification,
                "reason": "Trang web thuộc nhóm nội dung 18+ bị chặn."}

    # 1. Kiểm tra giờ giới nghiêm (Bedtime Mode)
    curfew = current_curfew(db)
    if curfew.is_within_curfew:
        return {
            "allowed": False,
            "target": target,
            "classification": classification,
            "reason": (
                f"Đang trong giờ giới nghiêm ({curfew.bedtime}–{curfew.wakeup_time}). "
                f"Giờ app đang dùng là {curfew.current_time} ({curfew.timezone})."
            ),
            "is_curfew": True
        }

    # 2. Kiểm tra hạn mức chung hôm nay của trẻ
    active_child = db.get(models.ChildProfile, device.child_profile_id) if device else None
    child_limit = active_child.daily_limit_minutes if active_child and active_child.daily_limit_minutes else 120
    sums = db.query(func.sum(models.MinimalTelemetryLog.duration_seconds))
    telemetry = todays_usage(db, device, sums, curfew.timezone)
    db_total_sec = telemetry.scalar() or 0
    total_mins = db_total_sec // 60
    if total_mins >= child_limit and child_limit > 0:
        return {
            "allowed": False,
            "target": target,
            "classification": classification,
            "reason": f"Đã dùng hết {child_limit} phút sử dụng máy tính hôm nay. Vui lòng xin cha mẹ thêm giờ.",
            "is_expired": True
        }

    # 3. Kiểm tra quy tắc cụ thể trong Database
    if is_web:
        matched_rule = web_rule_for_host(target, effective_web_rules(db, device))
    else:
        matched_rule = device_rules(db, device).filter(
            models.AppWebRule.rule_type == "APP",
            func.lower(models.AppWebRule.target_value) == target.lower(),
        ).first()

    if matched_rule:
        if matched_rule.action == "ASK":
            return {
                "allowed": False, "target": target, "classification": classification,
                "reason": "Trang web này cần phụ huynh cho phép.", "requires_permission": True,
            }
        if matched_rule.action == "BLOCK":
            return {
                "allowed": False,
                "target": target,
                "classification": classification,
                "reason": f"'{target}' đã bị Cha Mẹ đưa vào danh sách chặn truy cập."
            }
        
        limit_m = matched_rule.time_limit_minutes if matched_rule.time_limit_minutes is not None else 60
        used_seconds = telemetry.filter(func.lower(models.MinimalTelemetryLog.app_name).in_([
            target.lower(), f"www.{target.lower()}",
        ])).scalar() or 0
        used_m = used_seconds // 60
        if limit_m > 0 and used_m >= limit_m:
            return {
                "allowed": False,
                "target": target,
                "classification": classification,
                "reason": f"Đã dùng hết {limit_m} phút dành cho mục này hôm nay.",
                "is_expired": True,
                "time_limit_minutes": limit_m,
                "used_minutes": used_m
            }
        return {
            "allowed": True,
            "target": target,
            "classification": classification,
            "time_limit_minutes": limit_m,
            "used_minutes": used_m,
            "used_seconds": used_seconds,
            "remaining_minutes": max(0, limit_m - used_m)
        }

    if is_web:
        return {"allowed": True, "target": host, "classification": classification}

    # 4. Kiểm tra danh sách cấm mặc định
    blocked_defaults = ["youtube.com", "facebook.com", "discord.com", "tiktok.com", "roblox"]
    if any(b in target.lower() for b in blocked_defaults):
        return {
            "allowed": False,
            "target": target,
            "classification": classification,
            "reason": f"'{target}' thuộc danh sách mạng xã hội / giải trí bị giới hạn. Cần xin phép Cha Mẹ."
        }

    # 5. Nếu chưa có quy tắc cho phép: cảnh báo web lạ
    return {
        "allowed": False,
        "target": target,
        "classification": classification,
        "reason": f"'{target}' là trang web/ứng dụng lạ chưa có trong danh sách được duyệt của Cha Mẹ."
    }

@app.post("/classify/")
def api_classify(payload: schemas.CheckPermissionRequest):
    """Assign a reporting category from the hostname or application name."""
    target = extract_target_name(payload.target)
    is_web = payload.rule_type == "WEBSITE" if payload.rule_type else None
    return classify_item(target, is_web=is_web)

# ==========================================
# 4. XIN PHÉP & PHÊ DUYỆT (NT3 & NT5)
# ==========================================
@app.post("/requests/", status_code=201, response_model=schemas.ChildRequestResponse)
async def create_child_request(req: schemas.ChildRequestCreate, request: Request, db: Session = Depends(database.get_db)):
    """Gửi yêu cầu xin phép mở Web/Phần mềm hoặc xin thêm giờ."""
    is_web_request = req.request_type in {"PERMISSION_WEB", "PERMISSION_WEBSITE", "UNLOCK_WEB", "UNLOCK_WEBSITE", "WEB_TIME_EXTENSION"}
    clean_target = normalize_host(req.target_detail) if is_web_request else extract_target_name(req.target_detail or "")
    if is_web_request and (not clean_target or is_adult_host(clean_target)):
        raise HTTPException(422, "Tên miền không hợp lệ hoặc thuộc nhóm nội dung 18+ bị chặn.")
    tags_info = []
    if req.category:
        tags_info.append(f"Nhãn: {req.category}")
    if req.requested_minutes and req.requested_minutes > 0:
        tags_info.append(f"Xin: {req.requested_minutes} phút")
    
    detail = clean_target
    if tags_info:
        detail = f"{clean_target} [{' | '.join(tags_info)}]"

    device = client_device(request)
    db_req = models.ChildRequest(
        device_id=device.id if device else None,
        request_type=req.request_type,
        target_detail=detail,
        reason_from_child=req.reason_from_child,
        status="PENDING",
        parent_feedback=None
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)

    created_at_str = db_req.created_at.strftime("%Y-%m-%d %H:%M:%S") if db_req.created_at else ""
    await manager.send_to_device("parent_dashboard", {
        "type": "NEW_REQUEST",
        "data": {
            "id": db_req.id,
            "request_type": db_req.request_type,
            "target_detail": db_req.target_detail,
            "clean_target": clean_target,
            "reason_from_child": db_req.reason_from_child,
            "category": req.category,
            "status": db_req.status,
            "created_at": created_at_str
        }
    })
    return db_req

@app.get("/requests/", response_model=List[schemas.ChildRequestResponse])
def get_child_requests(request: Request, db: Session = Depends(database.get_db)):
    """Xem lại toàn bộ lịch sử yêu cầu và phản hồi."""
    device = client_device(request)
    query = db.query(models.ChildRequest).order_by(models.ChildRequest.id.desc())
    if device:
        return owned_rows(query, models.ChildRequest, device).all()
    return [
        schemas.ChildRequestResponse.model_validate(record).model_copy(update={"child_name": name})
        for record, name in query.add_columns(models.ChildProfile.name).outerjoin(
            models.Device, models.ChildRequest.device_id == models.Device.id
        ).outerjoin(models.ChildProfile, models.Device.child_profile_id == models.ChildProfile.id).all()
    ]

@app.patch("/requests/{request_id}", response_model=schemas.ChildRequestResponse)
async def update_child_request(
    request_id: int, 
    action: schemas.RequestActionUpdate, 
    db: Session = Depends(database.get_db)
):
    """Phụ huynh phê duyệt/từ chối yêu cầu và gửi lời phản hồi cho con (NT5)."""
    req = db.query(models.ChildRequest).filter(models.ChildRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu")

    if req.status != "PENDING":
        raise HTTPException(409, "Yêu cầu này đã được xử lý hoặc hết hạn.")
    req.status = action.status
    if action.parent_feedback is not None:
        req.parent_feedback = action.parent_feedback
    
    clean_target = extract_target_name(req.target_detail)
    limit_mins = 30
    if "Xin:" in req.target_detail:
        try:
            part = req.target_detail.split("Xin:")[1].split("phút")[0].strip()
            limit_mins = int(part)
        except Exception:
            pass
    elif "thêm" in req.target_detail:
        try:
            import re
            m = re.search(r'(\d+)\s*phút', req.target_detail)
            if m:
                limit_mins = int(m.group(1))
        except Exception:
            pass

    device = db.get(models.Device, req.device_id) if req.device_id else None
    if action.status == "APPROVED":
        if req.request_type == "WEB_TIME_EXTENSION":
            host = normalize_host(clean_target)
            rule = web_rule_for_host(host, effective_web_rules(db, device))
            if not host or is_adult_host(host) or not rule or rule.action != "ALLOW" or not rule.time_limit_minutes:
                raise HTTPException(409, "Trang web này không có hạn mức để gia hạn.")
            used_seconds = web_usage_seconds(db, device).get(host, 0)
            limit = max(rule.time_limit_minutes, (used_seconds + 59) // 60) + limit_mins
            if rule.device_id == req.device_id:
                rule.time_limit_minutes = limit
            else:
                db.add(models.AppWebRule(
                    device_id=req.device_id, rule_type="WEBSITE", target_value=host,
                    action="ALLOW", time_limit_minutes=limit, used_minutes=0,
                ))
        elif "TIME" in req.request_type:
            # Thêm thời gian vào hồ sơ con đang hoạt động
            active_child = db.get(models.ChildProfile, device.child_profile_id) if device else None
            if active_child:
                active_child.daily_limit_minutes = (active_child.daily_limit_minutes or 120) + limit_mins
            
        elif any(k in req.request_type for k in ["PERMISSION", "UNLOCK"]):
            rule_type = "WEBSITE" if any(w in req.request_type for w in ["WEB", "WEBSITE"]) else "APP"
            
            if rule_type == "WEBSITE":
                clean_target = normalize_host(clean_target)
                if not clean_target or is_adult_host(clean_target):
                    raise HTTPException(403, "Tên miền không hợp lệ hoặc thuộc nhóm nội dung 18+ bị chặn.")
            if rule_type == "WEBSITE":
                previous = web_rule_for_host(clean_target, effective_web_rules(db, device))
                if previous and previous.action == "ASK" and previous.time_limit_minutes:
                    limit_mins = min(limit_mins, previous.time_limit_minutes)
            existing = db.query(models.AppWebRule).filter(
                func.lower(models.AppWebRule.target_value) == clean_target.lower(),
                models.AppWebRule.device_id == req.device_id,
            ).first()
            if existing:
                existing.action = "ALLOW"
                existing.time_limit_minutes = (
                    limit_mins if rule_type == "WEBSITE" else max(existing.time_limit_minutes or 60, limit_mins)
                )
            else:
                new_rule = models.AppWebRule(
                    device_id=req.device_id,
                    rule_type=rule_type,
                    target_value=clean_target,
                    action="ALLOW",
                    time_limit_minutes=limit_mins,
                    used_minutes=0
                )
                db.add(new_rule)

    db.commit()
    db.refresh(req)

    event = {
        "type": "REQUEST_DECIDED",
        "data": {
            "id": req.id,
            "request_type": req.request_type,
            "target_detail": req.target_detail,
            "clean_target": clean_target,
            "status": req.status,
            "parent_feedback": req.parent_feedback,
            "time_limit_minutes": limit_mins
        }
    }
    await manager.send_to_device("parent_dashboard", event)
    if device and device.device_hwid:
        await manager.send_to_device(device.device_hwid, event)
    return req

# ==========================================
# 5. QUẢN LÝ QUY TẮC & GIỚI HẠN THỜI GIAN
# ==========================================
@app.get("/rules/", response_model=List[schemas.AppWebRuleResponse])
def get_rules(request: Request, db: Session = Depends(database.get_db)):
    """Lấy danh sách các trang web / ứng dụng kèm thời gian giới hạn và thời gian còn lại."""
    count = db.query(models.AppWebRule).count()
    if count == 0:
        default_rules = [
            models.AppWebRule(rule_type="WEBSITE", target_value="youtube.com", action="ASK", time_limit_minutes=30, used_minutes=0),
            models.AppWebRule(rule_type="WEBSITE", target_value="discord.com", action="ASK", time_limit_minutes=20, used_minutes=0),
            models.AppWebRule(rule_type="WEBSITE", target_value="tiktok.com", action="ASK", time_limit_minutes=20, used_minutes=0),
            models.AppWebRule(rule_type="WEBSITE", target_value="facebook.com", action="ASK", time_limit_minutes=20, used_minutes=0),
        ]
        db.add_all(default_rules)
        db.commit()

    device = client_device(request)
    rules = device_rules(db, device).all()
    usage = {}
    if device:
        for target, seconds in web_usage_seconds(db, device).items():
            key = target.lower().removeprefix("www.")
            usage[key] = usage.get(key, 0) + seconds
    website_rules = effective_web_rules(db, device) if device else {}
    seen = set()
    results = []
    for r in rules:
        is_web = r.rule_type == "WEBSITE"
        target = normalize_host(r.target_value) if is_web else r.target_value.lower()
        if device and (r.rule_type, target) in seen:
            continue
        seen.add((r.rule_type, target))
        limit_m = r.time_limit_minutes if r.time_limit_minutes is not None else 60
        used_seconds = usage.get(target, 0) if device else (r.used_minutes or 0) * 60
        used_m = used_seconds // 60
        rem_m, rem_str, expired = format_remaining(limit_m, used_m)
        matched_web_rule = web_rule_for_host(target, website_rules) if is_web else None
        action = r.action
        if is_web and (is_adult_host(target) or (matched_web_rule and matched_web_rule.action == "BLOCK")):
            action = "BLOCK"
        results.append(schemas.AppWebRuleResponse(
            id=r.id,
            device_id=r.device_id,
            rule_type=r.rule_type,
            target_value=target if is_web and target else r.target_value,
            action=action,
            time_limit_minutes=limit_m,
            used_minutes=used_m,
            used_seconds=used_seconds,
            remaining_minutes=rem_m,
            remaining_formatted=rem_str,
            is_expired=expired
        ))
    return results

@app.post("/rules/", status_code=201, response_model=schemas.AppWebRuleResponse)
def create_rule(rule_data: schemas.AppWebRuleCreate, db: Session = Depends(database.get_db)):
    """Phụ huynh thêm quy tắc và cài đặt giới hạn thời gian."""
    is_web = rule_data.rule_type == "WEBSITE"
    clean_val = normalize_host(rule_data.target_value) if is_web else extract_target_name(rule_data.target_value)
    if not is_web and rule_data.action == "ASK":
        raise HTTPException(422, "Chế độ xin phép chỉ hỗ trợ website.")
    if not clean_val:
        raise HTTPException(422, "Tên miền hoặc ứng dụng không hợp lệ.")
    if is_web and is_adult_host(clean_val) and rule_data.action != "BLOCK":
        raise HTTPException(403, "Không thể cho phép tên miền thuộc nhóm nội dung 18+.")
    matching = db.query(models.AppWebRule).filter(
        models.AppWebRule.rule_type == rule_data.rule_type,
        func.lower(models.AppWebRule.target_value) == clean_val.lower(),
    )
    existing = matching.filter(models.AppWebRule.device_id.is_(None)).first()
    if is_web:
        matching.filter(models.AppWebRule.device_id.is_not(None)).update({
            "action": rule_data.action or "ALLOW",
            "time_limit_minutes": rule_data.time_limit_minutes if rule_data.time_limit_minutes is not None else 60,
        }, synchronize_session=False)
    if existing:
        existing.rule_type = rule_data.rule_type
        existing.action = rule_data.action or "ALLOW"
        if rule_data.time_limit_minutes is not None:
            existing.time_limit_minutes = rule_data.time_limit_minutes
        db.commit()
        db.refresh(existing)
        rem_m, rem_str, expired = format_remaining(existing.time_limit_minutes, existing.used_minutes or 0)
        return schemas.AppWebRuleResponse(
            id=existing.id,
            device_id=existing.device_id,
            rule_type=existing.rule_type,
            target_value=existing.target_value,
            action=existing.action,
            time_limit_minutes=existing.time_limit_minutes,
            used_minutes=existing.used_minutes or 0,
            remaining_minutes=rem_m,
            remaining_formatted=rem_str,
            is_expired=expired
        )

    new_rule = models.AppWebRule(
        rule_type=rule_data.rule_type,
        target_value=clean_val,
        action=rule_data.action or "ALLOW",
        time_limit_minutes=rule_data.time_limit_minutes if rule_data.time_limit_minutes is not None else 60,
        used_minutes=0
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    
    rem_m, rem_str, expired = format_remaining(new_rule.time_limit_minutes, 0)
    return schemas.AppWebRuleResponse(
        id=new_rule.id,
        device_id=new_rule.device_id,
        rule_type=new_rule.rule_type,
        target_value=new_rule.target_value,
        action=new_rule.action,
        time_limit_minutes=new_rule.time_limit_minutes,
        used_minutes=0,
        remaining_minutes=rem_m,
        remaining_formatted=rem_str,
        is_expired=expired
    )

@app.patch("/rules/{rule_id}/limit")
async def update_rule_limit(rule_id: str, limit_data: schemas.SetLimitRequest, db: Session = Depends(database.get_db)):
    """Phụ huynh điều chỉnh giới hạn thời gian cho một quy tắc cụ thể."""
    rule = db.query(models.AppWebRule).filter(models.AppWebRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Không tìm thấy quy tắc")
    
    rule.time_limit_minutes = limit_data.time_limit_minutes
    db.commit()
    db.refresh(rule)

    rem_m, rem_str, expired = format_remaining(rule.time_limit_minutes, rule.used_minutes or 0)
    
    await manager.broadcast_json({
        "type": "LIMIT_UPDATED",
        "target_value": rule.target_value,
        "time_limit_minutes": rule.time_limit_minutes,
        "remaining_minutes": rem_m,
        "remaining_formatted": rem_str
    })

    return {
        "status": "success", 
        "target_value": rule.target_value, 
        "time_limit_minutes": rule.time_limit_minutes,
        "remaining_formatted": rem_str
    }

@app.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, db: Session = Depends(database.get_db)):
    """Xóa / thu hồi quy tắc."""
    rule = db.query(models.AppWebRule).filter(models.AppWebRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule không tồn tại")
    db.delete(rule)
    db.commit()
    return {"status": "success", "message": "Đã xóa quy tắc thành công"}

# ==========================================
# 6. CÁC TÍNH NĂNG RESET DÀNH CHO PHỤ HUYNH
# ==========================================
@app.post("/reset/daily", include_in_schema=False)
async def reset_daily(db: Session = Depends(database.get_db)):
    perform_daily_reset(db)
    await notify_daily_reset()
    return {"status": "success", "message": "Đã đặt lại thời gian sử dụng về 0."}


@app.post("/reset/usage")
async def reset_usage_time(db: Session = Depends(database.get_db)):
    """Reset toàn bộ thời gian sử dụng hôm nay về 0 (Thủ công từ Phụ huynh)."""
    clear_usage(db)
    db.commit()
    await manager.broadcast_json({
        "type": "USAGE_RESET",
        "message": "Phụ huynh đã đặt lại toàn bộ thời gian sử dụng hôm nay về 0."
    })
    return {"status": "success", "message": "Đã đặt lại thời gian sử dụng về 0."}

@app.post("/reset/rules")
async def reset_rules(db: Session = Depends(database.get_db)):
    """Reset các quy tắc Web & App về mặc định ban đầu."""
    db.query(models.AppWebRule).delete()
    default_rules = [
        models.AppWebRule(rule_type="WEBSITE", target_value="youtube.com", action="ASK", time_limit_minutes=30, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="discord.com", action="ASK", time_limit_minutes=20, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="tiktok.com", action="ASK", time_limit_minutes=20, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="facebook.com", action="ASK", time_limit_minutes=20, used_minutes=0),
    ]
    db.add_all(default_rules)
    db.commit()

    await manager.broadcast_json({
        "type": "RULES_RESET",
        "message": "Các quy tắc web/app đã được đặt lại về mặc định."
    })
    return {"status": "success", "message": "Đã đặt lại quy tắc về mặc định."}

@app.post("/reset/requests")
async def reset_requests(db: Session = Depends(database.get_db)):
    """Xóa sạch lịch sử yêu cầu của con."""
    db.query(models.ChildRequest).delete()
    db.commit()

    await manager.broadcast_json({
        "type": "REQUESTS_RESET",
        "message": "Hộp thư yêu cầu đã được làm sạch."
    })
    return {"status": "success", "message": "Đã làm sạch lịch sử yêu cầu."}

@app.post("/reset/all")
async def reset_all_system(db: Session = Depends(database.get_db)):
    """Khôi phục cài đặt gốc toàn diện cho hệ thống."""
    db.query(models.MinimalTelemetryLog).delete()
    db.query(models.AppWebRule).delete()
    default_rules = [
        models.AppWebRule(rule_type="WEBSITE", target_value="youtube.com", action="ASK", time_limit_minutes=30, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="discord.com", action="ASK", time_limit_minutes=20, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="tiktok.com", action="ASK", time_limit_minutes=20, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="facebook.com", action="ASK", time_limit_minutes=20, used_minutes=0),
    ]
    db.add_all(default_rules)
    db.query(models.ChildRequest).delete()
    db.commit()

    await manager.broadcast_json({
        "type": "FULL_RESET",
        "message": "Hệ thống đã được khôi phục về cài đặt gốc."
    })
    return {"status": "success", "message": "Hệ thống đã khôi phục cài đặt gốc thành công."}

# ==========================================
# 7. THỐNG KÊ THỜI GIAN SỬ DỤNG, GIỜ GIỚI NGHIÊM & THỜI GIAN CÒN LẠI
# ==========================================
@app.get("/usage-stats/", response_model=schemas.UsageStatsResponse)
def get_usage_stats(request: Request, child_id: Optional[int] = None, db: Session = Depends(database.get_db)):
    """Trả về thống kê thời gian sử dụng, thời gian giới hạn và thời gian còn lại."""
    
    device = client_device(request)
    selected_child = None
    if not device and child_id is not None:
        selected_child = db.get(models.ChildProfile, child_id)
        if selected_child is None:
            raise HTTPException(404, "Không tìm thấy hồ sơ trẻ.")
        device = db.query(models.Device).filter_by(child_profile_id=child_id).first()
    if device:
        selected_child = db.get(models.ChildProfile, device.child_profile_id)
    curfew = current_curfew(db)

    # Chỉ thống kê dữ liệu telemetry ghi trong ngày hiện tại của gia đình.
    real_usage_sec_map = {}

    logs = db.query(
        models.MinimalTelemetryLog.app_name,
        func.sum(models.MinimalTelemetryLog.duration_seconds).label("total_sec")
    )
    if selected_child and not device:
        db_logs = []
    else:
        db_logs = todays_usage(db, device, logs, curfew.timezone).group_by(
            models.MinimalTelemetryLog.app_name
        ).all()

    for app_name, total_sec in db_logs:
        if is_system_process(app_name):
            continue
        clean_n = (extract_target_name(app_name) or app_name).lower()
        if clean_n and not is_system_process(clean_n):
            real_usage_sec_map[clean_n] = real_usage_sec_map.get(clean_n, 0) + int(total_sec or 0)

    total_actual_sec = sum(real_usage_sec_map.values()) or 0
    total_minutes = total_actual_sec // 60

    app_rules = device_rules(db, device).filter(models.AppWebRule.rule_type == "APP").all()
    app_limits = {}
    for rule in app_rules:
        app_limits.setdefault(rule.target_value.lower(), rule.time_limit_minutes)
    website_rules = effective_web_rules(db, device)

    items: List[schemas.UsageItemResponse] = []
    web_hosts = {
        host for host, in todays_usage(db, device, db.query(models.MinimalTelemetryLog.domain), curfew.timezone)
        .filter(models.MinimalTelemetryLog.domain.is_not(None)).distinct()
    }
    category_seconds = {"LEARNING": 0, "ENTERTAINMENT": 0, "SOCIAL": 0, "UTILITY": 0, "OTHER": 0, "ADULT": 0}

    for name, seconds in sorted(real_usage_sec_map.items(), key=lambda item: item[1], reverse=True):
        minutes = seconds // 60
        info = classify_item(name, is_web=True if name in web_hosts else None)
        cat = info["category"]
        tag = info["tag"]
        if tag == "OTHER" and name in web_hosts:
            cat = "Chưa phân loại"
        
        if tag == "ADULT":
            limit_m = 0
        elif name in web_hosts:
            rule = web_rule_for_host(name, website_rules)
            limit_m = (rule.time_limit_minutes or 0) if rule else 0
        else:
            limit_m = info["default_limit"]
            for rule_name, configured_limit in app_limits.items():
                if rule_name in name or name in rule_name:
                    if configured_limit is not None:
                        limit_m = configured_limit
                    break

        rem_m, rem_str, is_exp = format_remaining(limit_m, minutes)
        if tag == "ADULT":
            rem_m, rem_str = 0, "Chặn theo bộ lọc"

        category = tag if tag != "OTHER" or name in web_hosts else "UTILITY"
        category_seconds[category] += seconds
        pct = round(seconds / total_actual_sec * 100, 1) if total_actual_sec else 0

        items.append(schemas.UsageItemResponse(
            app_name=name,
            duration_minutes=minutes,
            duration_formatted=format_usage_duration(seconds),
            category=cat,
            tag=tag,
            icon=info["icon"],
            badge_color=info["badge_color"],
            percentage=pct,
            time_limit_minutes=limit_m,
            remaining_minutes=rem_m,
            remaining_formatted=rem_str,
            is_expired=is_exp
        ))

    active_child = selected_child
    child_name = active_child.name if active_child else "Chưa có hồ sơ"
    child_daily_limit = active_child.daily_limit_minutes if active_child and active_child.daily_limit_minutes else 120
    child_remaining_seconds = max(0, (child_daily_limit * 60) - total_actual_sec)
    child_remaining = max(0, child_daily_limit - total_minutes)

    last_approved_ext = owned_rows(db.query(models.ChildRequest), models.ChildRequest, device).filter(
        models.ChildRequest.request_type == "TIME_EXTENSION",
        models.ChildRequest.status == "APPROVED"
    ).order_by(models.ChildRequest.id.desc()).first()
    ext_label = last_approved_ext.target_detail if last_approved_ext else None

    return schemas.UsageStatsResponse(
        total_minutes=total_minutes,
        total_formatted=format_usage_duration(total_actual_sec),
        learning_minutes=category_seconds["LEARNING"] // 60,
        learning_seconds=category_seconds["LEARNING"],
        learning_formatted=format_usage_duration(category_seconds["LEARNING"]),
        entertainment_minutes=category_seconds["ENTERTAINMENT"] // 60,
        entertainment_seconds=category_seconds["ENTERTAINMENT"],
        entertainment_formatted=format_usage_duration(category_seconds["ENTERTAINMENT"]),
        social_minutes=category_seconds["SOCIAL"] // 60,
        social_seconds=category_seconds["SOCIAL"],
        social_formatted=format_usage_duration(category_seconds["SOCIAL"]),
        utilities_minutes=category_seconds["UTILITY"] // 60,
        utilities_seconds=category_seconds["UTILITY"],
        unclassified_seconds=category_seconds["OTHER"],
        adult_seconds=category_seconds["ADULT"],
        utilities_formatted=format_usage_duration(category_seconds["UTILITY"]),
        is_bedtime=curfew.is_within_curfew,
        bedtime_hour=curfew.bedtime,
        wakeup_hour=curfew.wakeup_time,
        timezone=curfew.timezone,
        server_time=curfew.server_time,
        child_name=child_name,
        daily_limit_minutes=child_daily_limit,
        remaining_minutes=child_remaining,
        total_seconds=total_actual_sec,
        remaining_seconds=child_remaining_seconds,
        extension_label=ext_label,
        items=items
    )

# ==========================================
# KHUNG GIỜ GIỚI NGHIÊM & VÔ HIỆU HÓA TÙY CHỈNH
# ==========================================
@app.get("/curfew/", response_model=schemas.CurfewResponse)
def get_curfew(db: Session = Depends(database.get_db)):
    return current_curfew(db)


@app.post("/curfew/", response_model=schemas.CurfewResponse)
async def update_curfew(req: schemas.CurfewUpdateRequest, db: Session = Depends(database.get_db)):
    store_curfew(db, req.bedtime, req.wakeup_time, req.timezone)
    db.commit()

    curfew = current_curfew(db)
    await manager.broadcast_json({"type": "CURFEW_UPDATED", **curfew.model_dump(mode="json")})
    return curfew


# ==========================================
# QUẢN LÝ HỒ SƠ CON CÁI (CHILD PROFILES) & ĐĂNG NHẬP
# ==========================================
def child_response(profile, device=None):
    return schemas.ChildProfileResponse.model_validate(profile).model_copy(
        update={"device": schemas.DeviceResponse.model_validate(device) if device else None}
    )


@app.get("/children/", response_model=List[schemas.ChildProfileResponse])
def get_children(db: Session = Depends(database.get_db)):
    return [
        child_response(child, device)
        for child, device in db.query(models.ChildProfile, models.Device).outerjoin(
            models.Device, models.Device.child_profile_id == models.ChildProfile.id
        ).order_by(models.ChildProfile.id).all()
    ]


@app.post("/children/", status_code=201, response_model=schemas.ChildProfileResponse)
async def create_child(child: schemas.ChildProfileCreate, db: Session = Depends(database.get_db)):
    name = child.name.strip()
    device_name = child.device_name.strip() if child.device_name is not None else f"Máy của {name}"[:100]
    if not name or not device_name:
        raise HTTPException(422, "Tên trẻ và tên máy không được để trống.")
    profile = models.ChildProfile(
        name=name, avatar=child.avatar or "🧒", age=child.age,
        pin=security.hash_pin(child.pin), daily_limit_minutes=child.daily_limit_minutes,
    )
    try:
        db.add(profile)
        db.flush()
        device = devices.register_child_device(db, profile, device_name)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Không thể tạo mã ghép nối. Vui lòng thử lại.") from exc
    await manager.send_to_device("parent_dashboard", {"type": "PROFILES_UPDATED"})
    return child_response(profile, device)


@app.post("/children/{child_id}/pairing", response_model=schemas.DeviceResponse)
async def renew_child_pairing(child_id: int, db: Session = Depends(database.get_db)):
    profile = db.get(models.ChildProfile, child_id)
    if not profile:
        raise HTTPException(404, "Không tìm thấy hồ sơ trẻ.")
    device = db.query(models.Device).filter_by(child_profile_id=child_id).first()
    old_hwid = device.device_hwid if device else None
    try:
        if device is None:
            device = devices.register_child_device(db, profile, f"Máy của {profile.name}"[:100])
        else:
            device.device_hwid = device.pairing_token = None
            device.is_paired = False
            device.status = "PENDING_PAIR"
            devices.refresh_pairing_code(db, device)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Không thể tạo mã ghép nối. Vui lòng thử lại.") from exc
    _pin_attempts.pop(device.id, None)
    if old_hwid:
        await manager.close_device(old_hwid)
    return device


@app.delete("/children/{child_id}")
async def delete_child(child_id: int, db: Session = Depends(database.get_db)):
    profile = db.get(models.ChildProfile, child_id)
    if not profile:
        raise HTTPException(404, "Không tìm thấy hồ sơ trẻ.")
    device = db.query(models.Device).filter_by(child_profile_id=child_id).first()
    hwid = device.device_hwid if device else None
    if device:
        for model in (models.TimeLimit, models.AppWebRule, models.MinimalTelemetryLog, models.ChildRequest):
            db.query(model).filter_by(device_id=device.id).delete()
        db.delete(device)
    db.delete(profile)
    db.commit()
    if device:
        _pin_attempts.pop(device.id, None)
    if hwid:
        await manager.close_device(hwid)
    return {"message": "Đã xóa hồ sơ trẻ và thiết bị liên kết."}


@app.get("/children/assigned", response_model=schemas.ChildProfileResponse)
def get_assigned_child(request: Request, db: Session = Depends(database.get_db)):
    return db.get(models.ChildProfile, request.state.device.child_profile_id)


_pin_attempts = {}


@app.post("/children/login")
async def login_child(req: schemas.ChildLoginRequest, request: Request, db: Session = Depends(database.get_db)):
    device = request.state.device
    if device.child_profile_id != req.child_id:
        raise HTTPException(403, "Hồ sơ này không thuộc thiết bị.")
    profile = db.get(models.ChildProfile, req.child_id)
    now = time.monotonic()
    failures, expires = _pin_attempts.get(device.id, (0, now + 300))
    if now >= expires:
        failures, expires = 0, now + 300
    if failures >= 5:
        raise HTTPException(429, "Sai PIN quá nhiều lần. Vui lòng thử lại sau.")
    if not profile or not security.verify_pin(req.pin, profile.pin):
        _pin_attempts[device.id] = (failures + 1, expires)
        raise HTTPException(401, "PIN không chính xác.")
    _pin_attempts.pop(device.id, None)
    response = JSONResponse({"success": True, "message": "Đăng nhập thành công."})
    response.set_cookie(
        security.CHILD_COOKIE, security.dashboard_session(device), httponly=True,
        samesite="strict", secure=request.url.scheme == "https", max_age=8 * 3600,
    )
    return response


@app.get("/children/active", response_model=Optional[schemas.ChildProfileResponse])
def get_active_child(request: Request, db: Session = Depends(database.get_db)):
    device = client_device(request)
    return db.get(models.ChildProfile, device.child_profile_id) if device else None


# ==========================================
# CẢNH BÁO TRUY CẬP WEB LẠ & APP CHƯA PHÉP
# ==========================================
@app.get("/alerts/", response_model=List[schemas.AlertLogResponse])
def get_alerts(db: Session = Depends(database.get_db)):
    """Lấy danh sách các cảnh báo truy cập gần đây."""
    alerts = db.query(models.AlertLog, models.ChildProfile.name).outerjoin(
        models.Device, models.AlertLog.device_id == models.Device.id
    ).outerjoin(models.ChildProfile, models.Device.child_profile_id == models.ChildProfile.id)
    return [
        schemas.AlertLogResponse.model_validate(alert).model_copy(update={"child_name": name})
        for alert, name in alerts.order_by(models.AlertLog.timestamp.desc()).limit(30)
    ]

@app.post("/alerts/", response_model=schemas.AlertLogResponse)
async def create_alert(alert: schemas.AlertLogCreate, request: Request, db: Session = Depends(database.get_db)):
    """Ghi nhận cảnh báo khi trẻ cố tình truy cập web lạ hoặc ứng dụng bị cấm."""
    device = client_device(request)
    new_alert = models.AlertLog(
        device_id=device.id if device else None,
        target_value=alert.target_value.strip(),
        reason=alert.reason.strip(),
        category=alert.category or "UNAPPROVED_ACCESS",
        is_web=alert.is_web
    )
    db.add(new_alert)
    db.commit()
    db.refresh(new_alert)

    # Báo động tức thì tới toàn bộ phụ huynh qua WebSocket
    await manager.send_to_device("parent_dashboard", {
        "type": "UNAPPROVED_ATTEMPT",
        "app_name": alert.target_value,
        "category": new_alert.category,
        "message": f"Con vừa cố truy cập: '{alert.target_value}'. Lý do chặn: {alert.reason}",
        "timestamp": new_alert.timestamp.isoformat()
    })
    return new_alert

@app.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(database.get_db)):
    """Xóa một thông báo cảnh báo."""
    a = db.query(models.AlertLog).filter(models.AlertLog.id == alert_id).first()
    if a:
        db.delete(a)
        db.commit()
    return {"message": "Đã xóa cảnh báo"}

@app.delete("/alerts/")
def clear_all_alerts(db: Session = Depends(database.get_db)):
    """Xóa tất cả thông báo cảnh báo."""
    db.query(models.AlertLog).delete()
    db.commit()
    return {"message": "Đã xóa sạch tất cả cảnh báo"}

