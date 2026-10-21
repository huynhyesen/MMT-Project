import os
import asyncio
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from datetime import datetime
from typing import List
import json
import uuid
from . import database, models, schemas
from fastapi.middleware.cors import CORSMiddleware

# Tự động tạo bảng database nếu chưa tồn tại
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Parental Control Backend", version="1.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Đường dẫn thư mục static UI
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PARENT_APP_DIR = os.path.join(BASE_DIR, "parent-app")
CHILD_APP_DIR = os.path.join(BASE_DIR, "child-app")

if os.path.exists(PARENT_APP_DIR):
    app.mount("/parent", StaticFiles(directory=PARENT_APP_DIR, html=True), name="parent-app")
if os.path.exists(CHILD_APP_DIR):
    app.mount("/child", StaticFiles(directory=CHILD_APP_DIR, html=True), name="child-app")

# Biến theo dõi ngày để tự động reset mỗi ngày (Daily Rollover)
current_day_str = datetime.now().strftime("%Y-%m-%d")

def check_and_perform_daily_reset(db: Session):
    """Tự động kiểm tra chuyển ngày: nếu bước sang ngày mới, tự động reset thời gian và danh sách việc tốt."""
    global current_day_str
    today_str = datetime.now().strftime("%Y-%m-%d")
    if today_str != current_day_str:
        current_day_str = today_str
        # Đặt lại thời gian sử dụng về 0
        for rule in db.query(models.AppWebRule).all():
            rule.used_minutes = 0
        # Đặt lại trạng thái việc tốt về TODO để con làm lại vào ngày mới
        for task in db.query(models.Task).all():
            task.status = "TODO"
        # Xóa nhật ký telemetry cũ của ngày hôm trước
        db.query(models.MinimalTelemetryLog).delete()
        db.commit()

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
                                <div class="text-[11px] text-emerald-200 font-normal">Xem đếm ngược, web mở & việc tốt</div>
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
# CÁC HÀM TIỆN ÍCH PHÂN LOẠI & ĐỊNH DẠNG
# ==========================================
def extract_target_name(target: str) -> str:
    """Trích xuất tên miền hoặc tên phần mềm sạch (bỏ giao thức, www, nhãn...)."""
    if not target:
        return ""
    t = target.split("[")[0].strip()
    if "://" in t:
        t = t.split("://")[1]
    t = t.split("/")[0].split("?")[0].split(":")[0]
    if t.lower().startswith("www."):
        t = t[4:]
    return t

def is_system_process(name: str) -> bool:
    nl = name.lower().strip()
    if any(nl.startswith(prefix) for prefix in ['kworker', 'kthread', 'rcu', 'pool_', 'irq/', 'ksoftirqd', 'systemd', 'migration', 'auditd']):
        return True
    return nl in {
        'system', 'registry', 'svchost.exe', 'dbus-daemon', 'pipewire', 'pulseaudio', 
        'xorg', 'gnome-shell', 'bash', 'sh', 'python', 'python3', 'uvicorn', 'idle',
        'kthreadd', 'pool_workqueue_release', 'rcu_tasks_kthread'
    }

def classify_item(name: str) -> dict:
    """Hệ thống AI phân loại và gán nhãn tự động cho website & ứng dụng."""
    if not name or is_system_process(name):
        return {
            'category': 'Ứng dụng khác',
            'tag': 'OTHER',
            'icon': '💻',
            'badge_color': 'bg-slate-100 text-slate-800 border-slate-300',
            'default_limit': 60,
            'is_educational': False
        }

    nl = name.lower().strip()
    
    # 1. Học tập & Giáo dục (LEARNING)
    learning_keywords = [
        'khanacademy', 'wikipedia', 'duolingo', 'scratch', 'coursera', 'edx', 'udemy', 'quizlet', 
        'canvas', 'blackboard', 'hocmai', 'vioedu', 'vnedu', 'olm', 'k12online', 'vietjack', 
        'tuyensinh247', 'geogebra', 'code.org', 'w3schools', 'leetcode', 'hackerrank', 'stackoverflow', 
        'github', 'gitlab', 'python', 'sachmem', 'violet.vn', 'word', 'excel', 'powerpoint', 
        'onenote', 'acrobat', 'reader', 'pdf', 'zoom', 'teams', 'classroom', 'meet',
        '.edu', 'school', 'portal', 'lophoc', 'trithuc', 'tienganh', 'toan', 'vatly', 
        'hoahoc', 'lichsu', 'dialy', 'ielts', 'toeic', 'learn', 'study', 'math'
    ]
    if any(k in nl for k in learning_keywords):
        return {
            'category': 'Học tập & Giáo dục',
            'tag': 'LEARNING',
            'icon': '📚',
            'badge_color': 'bg-emerald-100 text-emerald-800 border-emerald-300',
            'default_limit': 180,
            'is_educational': True
        }
    
    # 2. Giải trí & Game (ENTERTAINMENT)
    entertainment_keywords = [
        'youtube', 'youtu.be', 'netflix', 'spotify', 'roblox', 'minecraft', 'steam', 'epicgames', 
        'league', 'valorant', 'genshin', 'fifa', 'pubg', 'game', 'friv', 'poki', 'bilibili', 
        'twitch', 'anime', 'manga', 'truyen', 'comic', 'zingmp3', 'nhaccuatui', 'fptplay', 
        'vieon', 'movie', 'film', 'cinema', 'chess', 'cotuong', 'caro', 'webtoon', 'soundcloud',
        'apple music', 'zing', 'vtvgo', 'clip', 'video'
    ]
    if any(k in nl for k in entertainment_keywords):
        return {
            'category': 'Giải trí & Game',
            'tag': 'ENTERTAINMENT',
            'icon': '🎮',
            'badge_color': 'bg-rose-100 text-rose-800 border-rose-300',
            'default_limit': 45,
            'is_educational': False
        }
        
    # 3. Mạng xã hội & Chat (SOCIAL)
    social_keywords = [
        'discord', 'facebook', 'fb.com', 'messenger', 'zalo', 'telegram', 'tiktok', 'instagram', 
        'threads', 'twitter', 'x.com', 'skype', 'viber', 'whatsapp', 'wechat', 'reddit', 
        'pinterest', 'snapchat', 'tumblr', 'chat', 'direct'
    ]
    if any(k in nl for k in social_keywords):
        return {
            'category': 'Mạng xã hội & Chat',
            'tag': 'SOCIAL',
            'icon': '💬',
            'badge_color': 'bg-blue-100 text-blue-800 border-blue-300',
            'default_limit': 30,
            'is_educational': False
        }
        
    # 4. Công cụ & Tiện ích (UTILITY)
    utility_keywords = [
        'google', 'bing', 'chrome', 'edge', 'firefox', 'safari', 'brave', 'coccoc', 'opera', 
        'calc', 'calculator', 'paint', 'notepad', 'notes', 'canva', 'figma', 'photoshop', 
        'gimp', 'audacity', 'vlc', 'terminal', 'cmd', 'calendar', 'clock'
    ]
    if any(k in nl for k in utility_keywords):
        return {
            'category': 'Công cụ & Tiện ích',
            'tag': 'UTILITY',
            'icon': '🛠️',
            'badge_color': 'bg-amber-100 text-amber-800 border-amber-300',
            'default_limit': 60,
            'is_educational': False
        }

    # 5. Ứng dụng khác (OTHER)
    return {
        'category': 'Ứng dụng khác',
        'tag': 'OTHER',
        'icon': '💻',
        'badge_color': 'bg-slate-100 text-slate-800 border-slate-300',
        'default_limit': 60,
        'is_educational': False
    }

def format_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} phút"
    hours = minutes // 60
    rem = minutes % 60
    return f"{hours} giờ {rem} phút" if rem else f"{hours} giờ"

def format_remaining(limit_mins: int, used_mins: int) -> tuple[int, str, bool]:
    if limit_mins <= 0:
        return (9999, "Không giới hạn", False)
    rem = limit_mins - used_mins
    if rem <= 0:
        return (0, "Đã hết giờ (0 phút)", True)
    return (rem, f"Còn {format_duration(rem)}", False)

def is_within_curfew(bedtime_str: str, wakeup_str: str, now: datetime = None) -> bool:
    """Kiểm tra thời điểm hiện tại có nằm trong khung giờ giới nghiêm (sau bedtime đến wakeup sáng) hay không."""
    if not bedtime_str or not wakeup_str:
        return False
    if now is None:
        now = datetime.now()
    try:
        from datetime import time as dtime
        b_hour, b_min = map(int, bedtime_str.split(":"))
        w_hour, w_min = map(int, wakeup_str.split(":"))
        now_time = now.time()
        b_time = dtime(b_hour, b_min)
        w_time = dtime(w_hour, w_min)

        if b_time > w_time:
            # Ví dụ: 22:00 tối đến 06:00 sáng hôm sau
            # Bị khóa nếu >= 22:00 HOẶC < 06:00
            return now_time >= b_time or now_time < w_time
        elif b_time < w_time:
            # Khung giờ trong cùng 1 ngày
            return b_time <= now_time < w_time
        else:
            return False
    except Exception:
        return False

# ==========================================
# QUẢN LÝ KẾT NỐI WEBSOCKET THỜI GIAN THỰC
# ==========================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[WebSocket, str] = {}

    async def connect(self, device_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = device_id

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            del self.active_connections[websocket]

    async def broadcast_text(self, message: str, sender_ws: WebSocket = None):
        dead_connections = []
        for ws in list(self.active_connections.keys()):
            if ws != sender_ws:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead_connections.append(ws)
        for ws in dead_connections:
            self.disconnect(ws)

    async def broadcast_json(self, data: dict, sender_ws: WebSocket = None):
        msg = json.dumps(data)
        await self.broadcast_text(msg, sender_ws=sender_ws)

manager = ConnectionManager()

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

    tasks = db.query(models.Task).all()
    initial_tasks = [
        {"title": t.title, "description": t.description, "reward_minutes": t.reward_minutes}
        for t in tasks
    ]

    return {
        "learning_limit_minutes": learn_limit.daily_limit_minutes if learn_limit else 180,
        "entertainment_limit_minutes": ent_limit.daily_limit_minutes if ent_limit else 45,
        "bedtime": learn_limit.bedtime if learn_limit else "22:00",
        "wakeup_time": learn_limit.wakeup_time if learn_limit and learn_limit.wakeup_time else "06:00",
        "allowed_sites": allowed or [],
        "blocked_sites": blocked or ["youtube.com", "facebook.com", "discord.com", "tiktok.com"],
        "initial_tasks": initial_tasks or []
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

    # Cập nhật danh sách việc tốt ban đầu (initial_tasks) nếu có
    if config.initial_tasks is not None and len(config.initial_tasks) > 0:
        db.query(models.Task).delete()
        for t in config.initial_tasks:
            if t.title and t.title.strip():
                db.add(models.Task(
                    title=t.title.strip(),
                    description=t.description or "Nhiệm vụ hàng ngày",
                    reward_minutes=t.reward_minutes or 15,
                    status="TODO"
                ))

    db.commit()

    await manager.broadcast_json({
        "type": "ONBOARDING_UPDATED",
        "message": "Cấu hình gốc của hệ thống đã được cập nhật thành công!"
    })

    return {"status": "success", "message": "Đã lưu cấu hình gốc thành công!"}

# ==========================================
# 2. GAMIFICATION: ĐỔI VIỆC TỐT LẤY GIỜ CHƠI
# ==========================================
@app.get("/tasks/", response_model=List[schemas.TaskResponse])
def get_tasks(db: Session = Depends(database.get_db)):
    """Lấy danh sách việc tốt / bài tập nhận thưởng. Mặc định trống, phụ huynh tự thêm."""
    return db.query(models.Task).order_by(models.Task.id.desc()).all()

@app.post("/tasks/", status_code=201, response_model=schemas.TaskResponse)
async def create_task(task_data: schemas.TaskCreate, db: Session = Depends(database.get_db)):
    """Phụ huynh tạo việc tốt / bài tập mới."""
    new_task = models.Task(
        title=task_data.title.strip(),
        description=task_data.description,
        reward_minutes=task_data.reward_minutes,
        status="TODO"
    )
    db.add(new_task)
    db.commit()
    db.refresh(new_task)

    await manager.broadcast_json({
        "type": "NEW_TASK",
        "title": new_task.title,
        "reward_minutes": new_task.reward_minutes
    })
    return new_task

@app.patch("/tasks/{task_id}/complete", response_model=schemas.TaskResponse)
async def complete_task(task_id: int, db: Session = Depends(database.get_db)):
    """Trẻ em báo cáo đã hoàn thành việc tốt."""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy việc tốt")
    
    task.status = "COMPLETED_WAITING_APPROVAL"
    db.commit()
    db.refresh(task)

    await manager.broadcast_json({
        "type": "TASK_WAITING_APPROVAL",
        "task_id": task.id,
        "title": task.title,
        "reward_minutes": task.reward_minutes
    })
    return task

@app.patch("/tasks/{task_id}/approve", response_model=schemas.TaskResponse)
async def approve_task(task_id: int, db: Session = Depends(database.get_db)):
    """Phụ huynh duyệt và thưởng thêm phút sử dụng cho con."""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy việc tốt")
    
    task.status = "APPROVED"
    
    # Tự động cộng thưởng số phút vào quy tắc hoặc giảm used_minutes
    for rule in db.query(models.AppWebRule).filter(models.AppWebRule.action == "ALLOW").all():
        rule.time_limit_minutes = (rule.time_limit_minutes or 60) + task.reward_minutes

    db.commit()
    db.refresh(task)

    await manager.broadcast_json({
        "type": "TASK_APPROVED_REWARD",
        "task_id": task.id,
        "title": task.title,
        "reward_minutes": task.reward_minutes,
        "message": f"🎉 Chúc mừng con! Cha mẹ đã duyệt '{task.title}' và thưởng thêm +{task.reward_minutes} phút!"
    })
    return task

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(database.get_db)):
    """Xóa một nhiệm vụ / việc tốt."""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Không tìm thấy việc tốt")
    db.delete(task)
    db.commit()
    return {"status": "success", "message": "Đã xóa việc tốt thành công"}

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
@app.post("/reset/usage")
async def reset_usage_time(db: Session = Depends(database.get_db)):
    """Reset toàn bộ thời gian sử dụng hôm nay về 0."""
    db.query(models.MinimalTelemetryLog).delete()
    for r in db.query(models.AppWebRule).all():
        r.used_minutes = 0
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

@app.post("/reset/daily")
async def trigger_daily_reset(db: Session = Depends(database.get_db)):
    """Tự động hoặc chủ động kích hoạt reset sang ngày mới: thời gian về 0, việc tốt về TODO."""
    for rule in db.query(models.AppWebRule).all():
        rule.used_minutes = 0
    for task in db.query(models.Task).all():
        task.status = "TODO"
    db.query(models.MinimalTelemetryLog).delete()
    db.commit()

    await manager.broadcast_json({
        "type": "DAILY_RESET_TRIGGERED",
        "message": "🌅 Đã thực hiện reset ngày mới: Thời gian sử dụng về 0 và danh sách việc tốt đã được làm mới!"
    })
    return {"status": "success", "message": "Đã reset toàn bộ cho ngày mới!"}

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
    child_name = active_child.name if active_child else "Bé An"
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
    """Lấy danh sách tất cả hồ sơ trẻ em. Tự khởi tạo hồ sơ mặc định nếu chưa có."""
    profiles = db.query(models.ChildProfile).order_by(models.ChildProfile.id.asc()).all()
    if not profiles:
        default_child = models.ChildProfile(
            name="Bé An",
            avatar="🧒",
            age=10,
            pin="1234",
            daily_limit_minutes=120,
            is_active=True
        )
        db.add(default_child)
        db.commit()
        db.refresh(default_child)
        profiles = [default_child]
    return profiles

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

    if target.pin and req.pin and req.pin != target.pin:
        raise HTTPException(status_code=400, detail="Mã PIN không chính xác!")

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

@app.get("/children/active", response_model=schemas.ChildProfileResponse)
def get_active_child(db: Session = Depends(database.get_db)):
    """Lấy hồ sơ trẻ đang đăng nhập."""
    active = db.query(models.ChildProfile).filter(models.ChildProfile.is_active == True).first()
    if not active:
        all_children = get_children(db)
        if all_children:
            active = all_children[0]
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
        is_web=alert.is_web
    )
    db.add(new_alert)
    db.commit()
    db.refresh(new_alert)

    # Báo động tức thì tới toàn bộ phụ huynh qua WebSocket
    await manager.broadcast_json({
        "type": "UNAPPROVED_ATTEMPT",
        "app_name": alert.target_value,
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

# ==========================================
# TỰ ĐỘNG ĐIỀN HẠN MỨC KHUYÊN DÙNG (AUTO-FILL)
# ==========================================
@app.post("/rules/auto-fill-defaults")
async def auto_fill_default_limits(db: Session = Depends(database.get_db)):
    """Tự động điền hạn mức khuyên dùng cho các web và app."""
    rules = db.query(models.AppWebRule).all()
    updated_count = 0
    for r in rules:
        info = classify_item(r.target_value)
        r.time_limit_minutes = info["default_limit"]
        updated_count += 1
    db.commit()

    await manager.broadcast_json({"type": "RULES_UPDATED"})
    return {"message": f"Đã tự động điền hạn mức khuyên dùng cho {updated_count} mục!", "count": updated_count}
