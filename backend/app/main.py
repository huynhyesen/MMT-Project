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

def classify_item(name: str) -> dict:
    nl = name.lower()
    
    # Học tập & Giáo dục
    if any(k in nl for k in [
        'code', 'word', 'excel', 'powerpoint', 'zoom', 'teams', 'classroom', 
        'portal', 'edu', 'duolingo', 'wikipedia', 'calc', 'scratch', 'notepad', 
        'chrome', 'edge', 'khan', 'coursera', 'hocmai', 'quizlet', 'canvas'
    ]):
        return {
            'category': 'Học tập & Giáo dục',
            'tag': 'LEARNING',
            'icon': '📚',
            'badge_color': 'bg-emerald-100 text-emerald-800 border-emerald-300',
            'default_limit': 120
        }
    
    # Giải trí & Game
    elif any(k in nl for k in [
        'game', 'minecraft', 'roblox', 'steam', 'league', 'valorant', 'genshin', 
        'fifa', 'pubg', 'netflix', 'spotify', 'tiktok', 'youtube', 'friv', 'poki'
    ]):
        return {
            'category': 'Giải trí & Game',
            'tag': 'ENTERTAINMENT',
            'icon': '🎮',
            'badge_color': 'bg-rose-100 text-rose-800 border-rose-300',
            'default_limit': 45
        }
        
    # Mạng xã hội & Chat
    elif any(k in nl for k in [
        'discord', 'facebook', 'messenger', 'zalo', 'telegram', 'instagram', 'twitter', 'threads', 'skype'
    ]):
        return {
            'category': 'Mạng xã hội & Chat',
            'tag': 'SOCIAL',
            'icon': '💬',
            'badge_color': 'bg-blue-100 text-blue-800 border-blue-300',
            'default_limit': 30
        }
        
    # Công cụ & Tiện ích
    else:
        return {
            'category': 'Công cụ & Tiện ích',
            'tag': 'UTILITIES',
            'icon': '🛠️',
            'badge_color': 'bg-purple-100 text-purple-800 border-purple-300',
            'default_limit': 60
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
        "allowed_sites": allowed or ["khanacademy.org", "wikipedia.org", "duolingo.com", "code.exe"],
        "blocked_sites": blocked or ["youtube.com", "facebook.com", "discord.com", "tiktok.com", "roblox"],
        "initial_tasks": initial_tasks or [
            {"title": "Làm xong bài tập Toán", "description": "Hoàn thành vở bài tập Toán", "reward_minutes": 20},
            {"title": "Dọn dẹp góc học tập", "description": "Sắp xếp sách vở ngăn nắp", "reward_minutes": 15},
            {"title": "Đọc 10 trang sách tiếng Anh", "description": "Đọc và học từ mới", "reward_minutes": 25}
        ]
    }

@app.post("/onboarding/setup")
async def save_onboarding_setup(config: schemas.OnboardingSetupRequest, db: Session = Depends(database.get_db)):
    """Lưu cấu hình quy chuẩn gốc từ Onboarding Setup Wizard."""
    # Cập nhật hoặc tạo TimeLimit
    learn_limit = db.query(models.TimeLimit).filter(models.TimeLimit.category == "LEARNING").first()
    if not learn_limit:
        learn_limit = models.TimeLimit(category="LEARNING", daily_limit_minutes=config.learning_limit_minutes, bedtime=config.bedtime)
        db.add(learn_limit)
    else:
        learn_limit.daily_limit_minutes = config.learning_limit_minutes
        learn_limit.bedtime = config.bedtime

    ent_limit = db.query(models.TimeLimit).filter(models.TimeLimit.category == "ENTERTAINMENT").first()
    if not ent_limit:
        ent_limit = models.TimeLimit(category="ENTERTAINMENT", daily_limit_minutes=config.entertainment_limit_minutes, bedtime=config.bedtime)
        db.add(ent_limit)
    else:
        ent_limit.daily_limit_minutes = config.entertainment_limit_minutes
        ent_limit.bedtime = config.bedtime

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
    """Lấy danh sách việc tốt / bài tập nhận thưởng."""
    count = db.query(models.Task).count()
    if count == 0:
        default_tasks = [
            models.Task(title="Làm xong bài tập Toán", description="Hoàn thành các bài tập trong vở bài tập Toán trang 45", reward_minutes=20, status="TODO"),
            models.Task(title="Dọn dẹp góc học tập", description="Sắp xếp sách vở ngăn nắp và lau bàn học", reward_minutes=15, status="TODO"),
            models.Task(title="Đọc 10 trang sách tiếng Anh", description="Đọc to và tra từ mới bài học", reward_minutes=25, status="TODO"),
        ]
        db.add_all(default_tasks)
        db.commit()

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
    """Nhận siêu dữ liệu thời lượng hoạt động từ Agent."""
    check_and_perform_daily_reset(db)
    db_log = models.MinimalTelemetryLog(
        app_name=data.app_name,
        domain=data.domain,
        duration_seconds=data.duration_seconds
    )
    db.add(db_log)

    mins_add = max(1, data.duration_seconds // 60) if data.duration_seconds >= 60 else 0
    if mins_add > 0:
        clean = extract_target_name(data.app_name)
        matched_rule = db.query(models.AppWebRule).filter(
            models.AppWebRule.target_value.ilike(f"%{clean}%")
        ).first()
        if matched_rule:
            matched_rule.used_minutes = (matched_rule.used_minutes or 0) + mins_add

    db.commit()
    return {"status": "success", "message": "Telemetry logged safely."}

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
    limit_mins = 60
    if "Xin:" in req.target_detail:
        try:
            part = req.target_detail.split("Xin:")[1].split("phút")[0].strip()
            limit_mins = int(part)
        except Exception:
            pass

    if action.status == "APPROVED" and any(k in req.request_type for k in ["PERMISSION", "UNLOCK"]):
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
            models.AppWebRule(rule_type="WEBSITE", target_value="khanacademy.org", action="ALLOW", time_limit_minutes=120, used_minutes=25),
            models.AppWebRule(rule_type="WEBSITE", target_value="wikipedia.org", action="ALLOW", time_limit_minutes=60, used_minutes=15),
            models.AppWebRule(rule_type="WEBSITE", target_value="duolingo.com", action="ALLOW", time_limit_minutes=45, used_minutes=10),
            models.AppWebRule(rule_type="APP", target_value="code.exe", action="ALLOW", time_limit_minutes=180, used_minutes=65),
            models.AppWebRule(rule_type="WEBSITE", target_value="youtube.com", action="BLOCK", time_limit_minutes=30, used_minutes=0),
            models.AppWebRule(rule_type="WEBSITE", target_value="discord.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
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
        models.AppWebRule(rule_type="WEBSITE", target_value="khanacademy.org", action="ALLOW", time_limit_minutes=120, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="wikipedia.org", action="ALLOW", time_limit_minutes=60, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="duolingo.com", action="ALLOW", time_limit_minutes=45, used_minutes=0),
        models.AppWebRule(rule_type="APP", target_value="code.exe", action="ALLOW", time_limit_minutes=180, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="youtube.com", action="BLOCK", time_limit_minutes=30, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="discord.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
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
        models.AppWebRule(rule_type="WEBSITE", target_value="khanacademy.org", action="ALLOW", time_limit_minutes=120, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="wikipedia.org", action="ALLOW", time_limit_minutes=60, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="duolingo.com", action="ALLOW", time_limit_minutes=45, used_minutes=0),
        models.AppWebRule(rule_type="APP", target_value="code.exe", action="ALLOW", time_limit_minutes=180, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="youtube.com", action="BLOCK", time_limit_minutes=30, used_minutes=0),
        models.AppWebRule(rule_type="WEBSITE", target_value="discord.com", action="BLOCK", time_limit_minutes=20, used_minutes=0),
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
    
    # Kiểm tra giờ giới nghiêm (Bedtime Mode)
    time_limit_record = db.query(models.TimeLimit).first()
    bedtime_str = time_limit_record.bedtime if time_limit_record and time_limit_record.bedtime else "22:00"
    
    is_bedtime = False
    try:
        now = datetime.now()
        b_hour, b_min = map(int, bedtime_str.split(":"))
        if (now.hour > b_hour) or (now.hour == b_hour and now.minute >= b_min) or (now.hour < 6):
            is_bedtime = True
    except Exception:
        pass

    baseline_map = {
        "Google Chrome": 55,
        "Visual Studio Code": 45,
        "Zoom Meeting": 30,
        "Minecraft": 25,
        "Roblox": 20,
        "Discord": 15,
        "Microsoft Word": 20,
        "Tiện ích & Explorer": 10,
    }

    db_logs = db.query(
        models.MinimalTelemetryLog.app_name,
        func.sum(models.MinimalTelemetryLog.duration_seconds).label("total_sec")
    ).group_by(models.MinimalTelemetryLog.app_name).all()

    for app_name, total_sec in db_logs:
        mins = max(1, round(total_sec / 60))
        clean_n = extract_target_name(app_name)
        matched = False
        for base_name in baseline_map:
            if base_name.lower() in clean_n.lower() or clean_n.lower() in base_name.lower():
                baseline_map[base_name] += mins
                matched = True
                break
        if not matched and clean_n:
            baseline_map[clean_n] = mins

    rules = db.query(models.AppWebRule).all()
    rule_limits = {}
    for r in rules:
        rule_limits[r.target_value.lower()] = r.time_limit_minutes

    total_minutes = sum(baseline_map.values()) or 1

    items: List[schemas.UsageItemResponse] = []
    learning_minutes = 0
    entertainment_minutes = 0
    social_minutes = 0
    utilities_minutes = 0

    for name, minutes in sorted(baseline_map.items(), key=lambda x: x[1], reverse=True):
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

        pct = round((minutes / total_minutes) * 100, 1)

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
        items=items
    )
