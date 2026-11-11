import os
import asyncio
import time
import random
import string
import hashlib
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from datetime import datetime, timedelta
from typing import List, Optional
from contextlib import asynccontextmanager
import json
import uuid
from . import database, models, schemas
from fastapi.middleware.cors import CORSMiddleware

from .services.classification import (
    extract_target_name,
    is_system_process,
    classify_item
)

from .services.formatters import (
    format_duration,
    format_remaining,
    is_within_curfew
)

from .services.realtime import manager


# Tự động tạo bảng database nếu chưa tồn tại
models.Base.metadata.create_all(bind=database.engine)

def auto_migrate_db():
    """Bổ sung các cột còn thiếu trong SQLite mà không làm mất dữ liệu."""
    import logging
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

# Biến theo dõi ngày để tự động reset mỗi ngày (Daily Rollover)
current_day_str = datetime.now().strftime("%Y-%m-%d")

def perform_daily_reset(db: Session, today_str: Optional[str] = None):
    """Thực hiện đầy đủ quy trình chuyển ngày tự động (Daily Rollover) chuẩn hóa:
    1. Đặt lại số phút đã sử dụng của tất cả các quy tắc ứng dụng & web về 0.
    2. Dọn sạch nhật ký hoạt động telemetry cũ để ngày mới tính từ 0 giây.
    3. Tự động đánh dấu hết hạn (EXPIRED) các yêu cầu xin thêm giờ của hôm trước.
    4. Phát sự kiện WebSocket DAILY_RESET_TRIGGERED để đồng bộ tức thời đến Dashboard Cha Mẹ và Máy Con.
    """
    global current_day_str
    if not today_str:
        today_str = datetime.now().strftime("%Y-%m-%d")
    current_day_str = today_str

    # 1. Đặt lại số phút đã sử dụng của tất cả quy tắc về 0
    for rule in db.query(models.AppWebRule).all():
        rule.used_minutes = 0

    # 2. Xóa nhật ký telemetry cũ của ngày hôm trước
    db.query(models.MinimalTelemetryLog).delete()

    # 3. Đánh dấu hết hạn các yêu cầu xin giờ chưa duyệt từ hôm trước
    db.query(models.ChildRequest).filter(
        models.ChildRequest.status == "PENDING"
    ).update({"status": "EXPIRED"})

    db.commit()

    # 4. Gửi tín hiệu thông báo thời gian thực qua WebSocket
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(manager.broadcast_json({
            "type": "DAILY_RESET_TRIGGERED",
            "date": today_str,
            "message": f"🌅 Bắt đầu ngày mới ({today_str}): Thời gian sử dụng đã được làm mới về 0 phút."
        }))
    except Exception:
        pass


def check_and_perform_daily_reset(db: Session):
    """Tự động kiểm tra chuyển ngày mỗi khi có API request: nếu bước sang ngày mới, tự động reset."""
    global current_day_str
    today_str = datetime.now().strftime("%Y-%m-%d")
    if today_str != current_day_str:
        perform_daily_reset(db, today_str)


async def daily_rollover_worker():
    """Tác vụ chạy ngầm định kỳ theo dõi đồng hồ:
    Đúng 00:00:00 hàng ngày, tự động kích hoạt reset chuyển ngày mà không cần đợi người dùng bấm hay gửi request.
    """
    while True:
        try:
            now = datetime.now()
            # Tính số giây còn lại đến 00:00:01 của ngày kế tiếp
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=1, microsecond=0)
            seconds_until_midnight = max(1.0, (tomorrow - now).total_seconds())

            # Ngủ tối đa 60 giây mỗi chu kỳ để phát hiện kịp thời nếu máy tính bị đổi giờ / sleep thức dậy
            await asyncio.sleep(min(seconds_until_midnight, 60.0))

            today_str = datetime.now().strftime("%Y-%m-%d")
            global current_day_str
            if today_str != current_day_str:
                db = database.SessionLocal()
                try:
                    perform_daily_reset(db, today_str)
                finally:
                    db.close()
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(60.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi chạy tác vụ nền tự động chuyển ngày đúng 00:00:00
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
            <script src="https://cdn.tailwindcss.com"></script>
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
    await manager.connect(device_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            
            parsed_json = None
            msg_type = ""
            try:
                parsed_json = json.loads(data)
                msg_type = parsed_json.get("type", "")
            except Exception:
                pass

            if "LOCK_MACHINE" in data or msg_type == "LOCK_MACHINE":
                await manager.broadcast_json({
                    "type": "LOCK_MACHINE",
                    "sender": device_id,
                    "message": "🔒 Máy tính đã bị khóa bởi Phụ huynh!"
                }, sender_ws=websocket)
            elif "UNLOCK_MACHINE" in data or msg_type == "UNLOCK_MACHINE":
                await manager.broadcast_json({
                    "type": "UNLOCK_MACHINE",
                    "sender": device_id,
                    "message": "🔓 Máy tính đã được mở khóa bởi Phụ huynh!"
                }, sender_ws=websocket)
            elif msg_type == "PARENT_MESSAGE":
                await manager.broadcast_json({
                    "type": "PARENT_MESSAGE",
                    "sender": device_id,
                    "message": parsed_json.get("message", "")
                }, sender_ws=websocket)
            elif msg_type == "UNAPPROVED_ATTEMPT":
                await manager.broadcast_json({
                    "type": "UNAPPROVED_ATTEMPT",
                    "sender": device_id,
                    "app_name": parsed_json.get("app_name", ""),
                    "message": parsed_json.get("message", "Con vừa cố mở phần mềm/web chưa được cho phép.")
                }, sender_ws=websocket)
            else:
                await manager.broadcast_text(data, sender_ws=websocket)
                
    except WebSocketDisconnect:
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




@app.post("/ai/content-check", response_model=schemas.ContentFilterResult)
def api_content_check(req: schemas.ContentFilterAnalysisRequest):
    """Endpoint phân tích nội dung AI văn bản theo thời gian thực."""
    import sys
    sys.path.insert(0, os.path.join(BASE_DIR, "agent"))
    from ai_filter.text_analyzer import AITextAnalyzer
    analyzer = AITextAnalyzer()

    text_to_check = f"{req.window_title or ''} {req.text_content or ''} {req.url or ''}".strip()
    result = analyzer.analyze(text_to_check)

    return schemas.ContentFilterResult(
        is_safe=result["is_safe"],
        violation_category=result.get("category"),
        confidence=result.get("confidence", 0.0),
        reason=result.get("reason"),
        suggested_action=result.get("suggested_action", "ALLOW")
    )


# ==========================================
# 1. THIẾT LẬP LẦN ĐẦU (ONBOARDING SETUP)
# ==========================================
@app.get("/onboarding/config")
def get_onboarding_config(db: Session = Depends(database.get_db)):
    """Lấy cấu hình quy chuẩn gốc."""
    learn_limit = db.query(models.TimeLimit).filter(models.TimeLimit.category == "LEARNING").first()
    ent_limit = db.query(models.TimeLimit).filter(models.TimeLimit.category == "ENTERTAINMENT").first()
    
    rules = db.query(models.AppWebRule).all()
    allowed = [r.target_value for r in rules if r.action == "ALLOW"]
    blocked = [r.target_value for r in rules if r.action == "BLOCK"]

    return {
        "learning_limit_minutes": learn_limit.daily_limit_minutes if learn_limit else 180,
        "entertainment_limit_minutes": ent_limit.daily_limit_minutes if ent_limit else 45,
        "bedtime": learn_limit.bedtime if learn_limit else "22:00",
        "wakeup_time": learn_limit.wakeup_time if learn_limit and learn_limit.wakeup_time else "06:00",
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

    db.commit()

    await manager.broadcast_json({
        "type": "ONBOARDING_UPDATED",
        "message": "Cấu hình gốc của hệ thống đã được cập nhật thành công!"
    })

    return {"status": "success", "message": "Đã lưu cấu hình gốc thành công!"}

# ==========================================
# 3. QUẢN LÝ THIẾT BỊ VÀ TELEMETRY (NT2)
# ==========================================
@app.post("/telemetry/", status_code=201)
def receive_telemetry(data: schemas.TelemetryCreate, db: Session = Depends(database.get_db)):
    """Nhận siêu dữ liệu thời lượng hoạt động từ Agent hoặc Web tracker."""
    check_and_perform_daily_reset(db)
    clean_target = extract_target_name(data.app_name) or data.app_name
    if is_system_process(clean_target):
        return {"status": "ignored", "message": "Tiến trình hệ thống bị bỏ qua."}
        
    db_log = models.MinimalTelemetryLog(
        app_name=clean_target,
        domain=data.domain,
        duration_seconds=data.duration_seconds
    )
    db.add(db_log)
    db.commit()

    # Đồng bộ used_minutes cho quy tắc (nếu có)
    target_total_sec = db.query(func.sum(models.MinimalTelemetryLog.duration_seconds)).filter(
        models.MinimalTelemetryLog.app_name.ilike(f"%{clean_target}%")
    ).scalar() or 0

    matched_rule = db.query(models.AppWebRule).filter(
        models.AppWebRule.target_value.ilike(f"%{clean_target}%") | (models.AppWebRule.target_value == clean_target)
    ).first()
    if matched_rule:
        matched_rule.used_minutes = target_total_sec // 60 if target_total_sec >= 60 else (1 if target_total_sec > 0 else 0)
        db.commit()

    return {"status": "success", "message": "Telemetry logged safely.", "target": clean_target}

# ==========================================
# 3.1. KIỂM TRA QUYỀN TRUY CẬP VÀ GÁN NHÃN AI
# ==========================================
@app.post("/check-permission/")
def check_permission(payload: dict, db: Session = Depends(database.get_db)):
    """Kiểm tra một web/app có được phép hay không, đồng thời gán nhãn AI và trả về hạn mức."""
    raw_target = payload.get("target", "")
    target = extract_target_name(raw_target)
    if not target:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp địa chỉ web hoặc tên ứng dụng")

    classification = classify_item(target)
    
    # 1. Kiểm tra giờ giới nghiêm (Bedtime Mode)
    curfew_record = db.query(models.TimeLimit).first()
    b_hour = curfew_record.bedtime if curfew_record and curfew_record.bedtime else "22:00"
    w_hour = curfew_record.wakeup_time if curfew_record and curfew_record.wakeup_time else "06:00"
    if is_within_curfew(b_hour, w_hour):
        return {
            "allowed": False,
            "target": target,
            "classification": classification,
            "reason": f"Đang trong giờ giới nghiêm ({b_hour} - {w_hour}). Không thể truy cập.",
            "is_curfew": True
        }

    # 2. Kiểm tra hạn mức chung hôm nay của trẻ
    active_child = db.query(models.ChildProfile).filter(models.ChildProfile.is_active == True).first()
    child_limit = active_child.daily_limit_minutes if active_child and active_child.daily_limit_minutes else 120
    db_total_sec = db.query(func.sum(models.MinimalTelemetryLog.duration_seconds)).scalar() or 0
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
    matched_rule = db.query(models.AppWebRule).filter(
        models.AppWebRule.target_value.ilike(f"%{target}%") | (models.AppWebRule.target_value == target)
    ).first()

    if matched_rule:
        if matched_rule.action == "BLOCK":
            return {
                "allowed": False,
                "target": target,
                "classification": classification,
                "reason": f"'{target}' đã bị Cha Mẹ đưa vào danh sách chặn truy cập."
            }
        
        limit_m = matched_rule.time_limit_minutes or 60
        used_m = matched_rule.used_minutes or 0
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
            "remaining_minutes": max(0, limit_m - used_m)
        }

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
def api_classify(payload: dict):
    """Sử dụng AI để gán nhãn phân loại cho web hoặc app."""
    target = extract_target_name(payload.get("target", ""))
    return classify_item(target)

# ==========================================
# 4. XIN PHÉP & PHÊ DUYỆT (NT3 & NT5)
# ==========================================
@app.post("/requests/", status_code=201, response_model=schemas.ChildRequestResponse)
async def create_child_request(req: schemas.ChildRequestCreate, db: Session = Depends(database.get_db)):
    """Gửi yêu cầu xin phép mở Web/Phần mềm hoặc xin thêm giờ."""
    clean_target = extract_target_name(req.target_detail or "")
    tags_info = []
    if req.category:
        tags_info.append(f"Nhãn: {req.category}")
    if req.requested_minutes and req.requested_minutes > 0:
        tags_info.append(f"Xin: {req.requested_minutes} phút")
    
    detail = clean_target
    if tags_info:
        detail = f"{clean_target} [{' | '.join(tags_info)}]"

    db_req = models.ChildRequest(
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
    await manager.broadcast_json({
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
def get_child_requests(db: Session = Depends(database.get_db)):
    """Xem lại toàn bộ lịch sử yêu cầu và phản hồi."""
    return db.query(models.ChildRequest).order_by(models.ChildRequest.id.desc()).all()

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

    if action.status == "APPROVED":
        if "TIME" in req.request_type:
            # Thêm thời gian vào hồ sơ con đang hoạt động
            active_child = db.query(models.ChildProfile).filter(models.ChildProfile.is_active == True).first()
            if active_child:
                active_child.daily_limit_minutes = (active_child.daily_limit_minutes or 120) + limit_mins
            
            # Cập nhật thêm hạn mức cho các quy tắc thuộc nhãn tương ứng (Học tập, Giải trí, Mạng xã hội)
            target_tag = "LEARNING"
            if req.target_detail:
                if "Giải trí" in req.target_detail:
                    target_tag = "ENTERTAINMENT"
                elif "Mạng xã hội" in req.target_detail:
                    target_tag = "SOCIAL"
            
            for rule in db.query(models.AppWebRule).filter(models.AppWebRule.action == "ALLOW").all():
                r_info = classify_item(rule.target_value)
                if r_info.get("tag") == target_tag:
                    rule.time_limit_minutes = (rule.time_limit_minutes or 60) + limit_mins

        elif any(k in req.request_type for k in ["PERMISSION", "UNLOCK"]):
            rule_type = "WEBSITE" if any(w in req.request_type for w in ["WEB", "WEBSITE"]) else "APP"
            
            existing = db.query(models.AppWebRule).filter(
                models.AppWebRule.target_value == clean_target
            ).first()
            if existing:
                existing.action = "ALLOW"
                existing.time_limit_minutes = max(existing.time_limit_minutes or 60, limit_mins)
            else:
                new_rule = models.AppWebRule(
                    rule_type=rule_type,
                    target_value=clean_target,
                    action="ALLOW",
                    time_limit_minutes=limit_mins,
                    used_minutes=0
                )
                db.add(new_rule)

    db.commit()
    db.refresh(req)

    await manager.broadcast_json({
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
    })
    return req

# ==========================================
# 5. QUẢN LÝ QUY TẮC & GIỚI HẠN THỜI GIAN
# ==========================================
@app.get("/rules/", response_model=List[schemas.AppWebRuleResponse])
def get_rules(db: Session = Depends(database.get_db)):
    """Lấy danh sách các trang web / ứng dụng kèm thời gian giới hạn và thời gian còn lại."""
    count = db.query(models.AppWebRule).count()
    if count == 0:
        default_rules = [
            models.AppWebRule(rule_type="WEBSITE", target_value="youtube.com", action="BLOCK", time_limit_minutes=30, used_minutes=0),
            models.AppWebRule(rule_type="WEBSITE", target_value="discord.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
            models.AppWebRule(rule_type="WEBSITE", target_value="tiktok.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
            models.AppWebRule(rule_type="WEBSITE", target_value="facebook.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
        ]
        db.add_all(default_rules)
        db.commit()

    rules = db.query(models.AppWebRule).all()
    results = []
    for r in rules:
        limit_m = r.time_limit_minutes if r.time_limit_minutes is not None else 60
        used_m = r.used_minutes or 0
        rem_m, rem_str, expired = format_remaining(limit_m, used_m)
        results.append(schemas.AppWebRuleResponse(
            id=r.id,
            device_id=r.device_id,
            rule_type=r.rule_type,
            target_value=r.target_value,
            action=r.action,
            time_limit_minutes=limit_m,
            used_minutes=used_m,
            remaining_minutes=rem_m,
            remaining_formatted=rem_str,
            is_expired=expired
        ))
    return results

@app.post("/rules/", status_code=201, response_model=schemas.AppWebRuleResponse)
def create_rule(rule_data: schemas.AppWebRuleCreate, db: Session = Depends(database.get_db)):
    """Phụ huynh thêm quy tắc và cài đặt giới hạn thời gian."""
    clean_val = extract_target_name(rule_data.target_value)
    existing = db.query(models.AppWebRule).filter(
        models.AppWebRule.target_value == clean_val
    ).first()
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
        time_limit_minutes=rule_data.time_limit_minutes or 60,
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
@app.post("/reset/usage")
async def reset_usage_time(db: Session = Depends(database.get_db)):
    """Reset toàn bộ thời gian sử dụng hôm nay về 0 (Thủ công từ Phụ huynh)."""
    perform_daily_reset(db)
    return {"status": "success", "message": "Đã đặt lại thời gian sử dụng về 0."}

@app.post("/reset/rules")
async def reset_rules(db: Session = Depends(database.get_db)):
    """Reset các quy tắc Web & App về mặc định ban đầu."""
    db.query(models.AppWebRule).delete()
    default_rules = [
        models.AppWebRule(rule_type="WEBSITE", target_value="youtube.com", action="BLOCK", time_limit_minutes=30, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="discord.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="tiktok.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="facebook.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
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
        models.AppWebRule(rule_type="WEBSITE", target_value="youtube.com", action="BLOCK", time_limit_minutes=30, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="discord.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="tiktok.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="facebook.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
    ]
    db.add_all(default_rules)
    db.query(models.ChildRequest).delete()
    db.query(models.Device).delete()
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
def get_usage_stats(db: Session = Depends(database.get_db)):
    """Trả về thống kê thời gian sử dụng, thời gian giới hạn và thời gian còn lại."""
    check_and_perform_daily_reset(db)
    
    # Kiểm tra giờ giới nghiêm (Bedtime Mode: Vô hiệu hóa sau bedtime_str đến wakeup_str sáng)
    time_limit_record = db.query(models.TimeLimit).first()
    bedtime_str = time_limit_record.bedtime if time_limit_record and time_limit_record.bedtime else "22:00"
    wakeup_str = time_limit_record.wakeup_time if time_limit_record and time_limit_record.wakeup_time else "06:00"
    
    is_bedtime = is_within_curfew(bedtime_str, wakeup_str)

    # Chỉ thống kê dữ liệu thực tế từ telemetry (AI gán nhãn phân loại)
    real_usage_sec_map = {}

    db_logs = db.query(
        models.MinimalTelemetryLog.app_name,
        func.sum(models.MinimalTelemetryLog.duration_seconds).label("total_sec")
    ).group_by(models.MinimalTelemetryLog.app_name).all()

    for app_name, total_sec in db_logs:
        if is_system_process(app_name):
            continue
        clean_n = extract_target_name(app_name) or app_name
        if clean_n and not is_system_process(clean_n):
            real_usage_sec_map[clean_n] = real_usage_sec_map.get(clean_n, 0) + int(total_sec or 0)

    total_actual_sec = sum(real_usage_sec_map.values()) or 0
    total_minutes = total_actual_sec // 60

    real_usage_map = {}
    for clean_n, sec in real_usage_sec_map.items():
        mins = sec // 60 if sec >= 60 else (1 if sec > 0 else 0)
        real_usage_map[clean_n] = mins

    rules = db.query(models.AppWebRule).all()
    rule_limits = {}
    for r in rules:
        rule_limits[r.target_value.lower()] = r.time_limit_minutes

    items: List[schemas.UsageItemResponse] = []
    learning_minutes = 0
    entertainment_minutes = 0
    social_minutes = 0
    utilities_minutes = 0

    for name, minutes in sorted(real_usage_map.items(), key=lambda x: x[1], reverse=True):
        info = classify_item(name)
        cat = info["category"]
        tag = info["tag"]
        
        limit_m = info["default_limit"]
        clean_k = extract_target_name(name).lower()
        for rk, rlimit in rule_limits.items():
            if rk in clean_k or clean_k in rk:
                limit_m = rlimit
                break

        rem_m, rem_str, is_exp = format_remaining(limit_m, minutes)

        if tag == "LEARNING":
            learning_minutes += minutes
        elif tag == "ENTERTAINMENT":
            entertainment_minutes += minutes
        elif tag == "SOCIAL":
            social_minutes += minutes
        else:
            utilities_minutes += minutes

        pct = round((minutes / total_minutes) * 100, 1) if total_minutes > 0 else 0

        items.append(schemas.UsageItemResponse(
            app_name=name,
            duration_minutes=minutes,
            duration_formatted=format_duration(minutes),
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

    active_child = db.query(models.ChildProfile).filter(models.ChildProfile.is_active == True).first()
    child_name = active_child.name if active_child else "Chưa có hồ sơ"
    child_daily_limit = active_child.daily_limit_minutes if active_child and active_child.daily_limit_minutes else 120
    child_remaining_seconds = max(0, (child_daily_limit * 60) - total_actual_sec)
    child_remaining = max(0, child_daily_limit - total_minutes)

    last_approved_ext = db.query(models.ChildRequest).filter(
        models.ChildRequest.request_type == "TIME_EXTENSION",
        models.ChildRequest.status == "APPROVED"
    ).order_by(models.ChildRequest.id.desc()).first()
    ext_label = last_approved_ext.target_detail if last_approved_ext else None

    return schemas.UsageStatsResponse(
        total_minutes=total_minutes,
        total_formatted=format_duration(total_minutes),
        learning_minutes=learning_minutes,
        learning_formatted=format_duration(learning_minutes),
        entertainment_minutes=entertainment_minutes,
        entertainment_formatted=format_duration(entertainment_minutes),
        social_minutes=social_minutes,
        social_formatted=format_duration(social_minutes),
        utilities_minutes=utilities_minutes,
        utilities_formatted=format_duration(utilities_minutes),
        is_bedtime=is_bedtime,
        bedtime_hour=bedtime_str,
        wakeup_hour=wakeup_str,
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
    """Lấy thông tin khung giờ giới nghiêm hiện tại."""
    tl = db.query(models.TimeLimit).first()
    b_hour = tl.bedtime if tl and tl.bedtime else "22:00"
    w_hour = tl.wakeup_time if tl and tl.wakeup_time else "06:00"
    return schemas.CurfewResponse(
        bedtime=b_hour,
        wakeup_time=w_hour,
        is_within_curfew=is_within_curfew(b_hour, w_hour)
    )

@app.post("/curfew/", response_model=schemas.CurfewResponse)
async def update_curfew(req: schemas.CurfewUpdateRequest, db: Session = Depends(database.get_db)):
    """Cập nhật khung giờ giới nghiêm do phụ huynh tùy chỉnh."""
    limits = db.query(models.TimeLimit).all()
    if not limits:
        tl = models.TimeLimit(bedtime=req.bedtime, wakeup_time=req.wakeup_time)
        db.add(tl)
    else:
        for tl in limits:
            tl.bedtime = req.bedtime
            tl.wakeup_time = req.wakeup_time
    db.commit()

    active_curfew = is_within_curfew(req.bedtime, req.wakeup_time)
    await manager.broadcast_json({
        "type": "CURFEW_UPDATED",
        "bedtime": req.bedtime,
        "wakeup_time": req.wakeup_time,
        "is_within_curfew": active_curfew
    })

    return schemas.CurfewResponse(
        bedtime=req.bedtime,
        wakeup_time=req.wakeup_time,
        is_within_curfew=active_curfew
    )

# ==========================================
# QUẢN LÝ HỒ SƠ CON CÁI (CHILD PROFILES) & ĐĂNG NHẬP
# ==========================================
@app.get("/children/", response_model=List[schemas.ChildProfileResponse])
def get_children(db: Session = Depends(database.get_db)):
    """Lấy danh sách tất cả hồ sơ trẻ em (trống nếu phụ huynh chưa thêm)."""
    return db.query(models.ChildProfile).order_by(models.ChildProfile.id.asc()).all()

@app.post("/children/", response_model=schemas.ChildProfileResponse)
async def create_child(child: schemas.ChildProfileCreate, db: Session = Depends(database.get_db)):
    """Thêm một hồ sơ trẻ mới từ phụ huynh."""
    count = db.query(models.ChildProfile).count()
    new_profile = models.ChildProfile(
        name=child.name.strip(),
        avatar=child.avatar or "🧒",
        age=child.age or 10,
        pin=child.pin or "1234",
        daily_limit_minutes=child.daily_limit_minutes or 120,
        is_active=(count == 0)
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)

    await manager.broadcast_json({
        "type": "PROFILES_UPDATED"
    })
    return new_profile

@app.delete("/children/{child_id}")
async def delete_child(child_id: int, db: Session = Depends(database.get_db)):
    """Xóa hồ sơ trẻ."""
    profile = db.query(models.ChildProfile).filter(models.ChildProfile.id == child_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ trẻ")
    was_active = profile.is_active
    db.delete(profile)
    db.commit()

    if was_active:
        remaining = db.query(models.ChildProfile).first()
        if remaining:
            remaining.is_active = True
            db.commit()

    await manager.broadcast_json({"type": "PROFILES_UPDATED"})
    return {"message": "Đã xóa hồ sơ trẻ thành công"}

@app.post("/children/select/{child_id}")
async def select_child(child_id: int, db: Session = Depends(database.get_db)):
    """Chọn hồ sơ trẻ đang hoạt động."""
    profiles = db.query(models.ChildProfile).all()
    target = None
    for p in profiles:
        if p.id == child_id:
            p.is_active = True
            target = p
        else:
            p.is_active = False
    db.commit()
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ trẻ")

    await manager.broadcast_json({
        "type": "CHILD_SWITCHED",
        "child": {
            "id": target.id,
            "name": target.name,
            "avatar": target.avatar,
            "age": target.age,
            "daily_limit_minutes": target.daily_limit_minutes
        }
    })
    return {"message": f"Đã chuyển sang hồ sơ {target.name}", "child": target}

@app.post("/children/login")
async def login_child(req: schemas.ChildLoginRequest, db: Session = Depends(database.get_db)):
    """Đăng nhập máy với tư cách trẻ (kiểm tra mã PIN nếu có)."""
    target = db.query(models.ChildProfile).filter(models.ChildProfile.id == req.child_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ trẻ")

    if not req.pin or req.pin != target.pin:
        raise HTTPException(
            status_code=401,
            detail="PIN không chính xác."
        )

    profiles = db.query(models.ChildProfile).all()
    for p in profiles:
        p.is_active = (p.id == req.child_id)
    db.commit()

    await manager.broadcast_json({
        "type": "CHILD_SWITCHED",
        "child": {
            "id": target.id,
            "name": target.name,
            "avatar": target.avatar,
            "age": target.age,
            "daily_limit_minutes": target.daily_limit_minutes
        }
    })
    return {"success": True, "message": f"Đăng nhập thành công với tư cách {target.name}!", "child": target}

@app.get("/children/active", response_model=Optional[schemas.ChildProfileResponse])
def get_active_child(db: Session = Depends(database.get_db)):
    """Lấy hồ sơ trẻ đang đăng nhập (hoặc None nếu chưa có hồ sơ)."""
    active = db.query(models.ChildProfile).filter(models.ChildProfile.is_active == True).first()
    if not active:
        active = db.query(models.ChildProfile).first()
        if active:
            active.is_active = True
            db.commit()
    return active

# ==========================================
# CẢNH BÁO TRUY CẬP WEB LẠ & APP CHƯA PHÉP
# ==========================================
@app.get("/alerts/", response_model=List[schemas.AlertLogResponse])
def get_alerts(db: Session = Depends(database.get_db)):
    """Lấy danh sách các cảnh báo truy cập gần đây."""
    return db.query(models.AlertLog).order_by(models.AlertLog.timestamp.desc()).limit(30).all()

@app.post("/alerts/", response_model=schemas.AlertLogResponse)
async def create_alert(alert: schemas.AlertLogCreate, db: Session = Depends(database.get_db)):
    """Ghi nhận cảnh báo khi trẻ cố tình truy cập web lạ hoặc ứng dụng bị cấm."""
    new_alert = models.AlertLog(
        target_value=alert.target_value.strip(),
        reason=alert.reason.strip(),
        category=alert.category or "UNAPPROVED_ACCESS",
        is_web=alert.is_web
    )
    db.add(new_alert)
    db.commit()
    db.refresh(new_alert)

    # Báo động tức thì tới toàn bộ phụ huynh qua WebSocket
    await manager.broadcast_json({
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

