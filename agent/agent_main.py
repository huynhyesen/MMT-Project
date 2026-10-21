import asyncio
import websockets
import json
import time
import urllib.request
from monitor import get_active_app_metadata
from blocker import enforce_block_policy, kill_blocked_process, block_websites, unblock_websites, lock_system, extract_domain

def get_backend_port():
    for p in [8008, 8000, 8001, 8080]:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{p}/", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    return p
        except Exception:
            pass
    return 8008

BACKEND_PORT = get_backend_port()
URI = f"ws://127.0.0.1:{BACKEND_PORT}/ws/agent/device_001"
BACKEND_HTTP = f"http://127.0.0.1:{BACKEND_PORT}"

BLOCKED_KEYWORDS = ["discord", "youtube", "facebook", "tiktok", "roblox"] 
BLOCKED_DOMAINS = ["youtube.com", "facebook.com", "discord.com", "tiktok.com"]

# Danh sách ứng dụng/web được phụ huynh cho phép
ALLOWED_TARGETS = set()

IGNORE_SYSTEM_PROCS = {
    "system", "registry", "svchost.exe", "systemd", "kworker", "dbus-daemon", 
    "pipewire", "pulseaudio", "xorg", "gnome-shell", "bash", "python3", "python",
    "kthreadd", "pool_workqueue", "rcu_", "irq/", "ksoftirqd", "migration"
}

active_ws = None

def sync_allowed_rules():
    """Tải danh sách các quy tắc ALLOW từ server về Agent."""
    global ALLOWED_TARGETS, BACKEND_HTTP
    for p in [8008, 8000, 8001, 8080]:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{p}/rules/")
            with urllib.request.urlopen(req, timeout=2) as resp:
                rules = json.loads(resp.read().decode())
                BACKEND_HTTP = f"http://127.0.0.1:{p}"
                for r in rules:
                    if r.get("action") == "ALLOW":
                        val = extract_domain(r.get("target_value", ""))
                        if val:
                            ALLOWED_TARGETS.add(val.lower())
                print(f"🔄 [AGENT] Đã đồng bộ {len(ALLOWED_TARGETS)} mục được phép: {ALLOWED_TARGETS}")
                return
        except Exception:
            continue

def send_telemetry(app_name: str, duration_sec: int = 10):
    """Gửi dữ liệu thời lượng hoạt động của ứng dụng về Backend."""
    try:
        payload = json.dumps({
            "app_name": app_name,
            "duration_seconds": duration_sec
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{BACKEND_HTTP}/telemetry/", 
            data=payload, 
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

async def monitor_apps_task():
    """Tác vụ chạy ngầm: Định kỳ quét, tắt ứng dụng bị cấm và gửi telemetry."""
    while True:
        metadata_list = get_active_app_metadata() 
        reported_count = 0
        
        for app in metadata_list:
            app_name = app.get("app_name", "")
            app_lower = app_name.lower()
            window_title = app.get("window_title", "").lower()

            # Nếu ứng dụng hoặc tiêu đề cửa sổ nằm trong danh sách đã được phép -> Bỏ qua không chặn
            is_allowed = any(allowed in app_lower or allowed in window_title for allowed in ALLOWED_TARGETS)
            if is_allowed:
                # Gửi telemetry thời gian học tập / sử dụng
                if reported_count < 3 and not any(ign in app_lower for ign in IGNORE_SYSTEM_PROCS):
                    send_telemetry(app_name, duration_sec=5)
                    reported_count += 1
                continue
            
            # Kiểm tra ứng dụng bị cấm / cần xin phép
            if any(keyword in app_lower or keyword in window_title for keyword in BLOCKED_KEYWORDS):
                enforce_block_policy(app_name, "Cần xin phép phụ huynh trước khi sử dụng ứng dụng này", "Phụ huynh")
                kill_blocked_process(app_name)
                
                # Ghi nhận cảnh báo về máy chủ Backend
                try:
                    alert_payload = json.dumps({
                        "target_value": app_name,
                        "reason": f"Cố mở ứng dụng/web '{app_name}' chưa được cha mẹ cho phép",
                        "is_web": False
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        f"{BACKEND_HTTP}/alerts/",
                        data=alert_payload,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    urllib.request.urlopen(req, timeout=1)
                except Exception:
                    pass

                if active_ws:
                    try:
                        await active_ws.send(json.dumps({
                            "type": "UNAPPROVED_ATTEMPT",
                            "app_name": app_name,
                            "message": f"Con vừa cố mở '{app_name}' nhưng chưa được phép."
                        }))
                    except Exception:
                        pass
                continue

            # Gửi telemetry ứng dụng bình thường
            if reported_count < 3 and not any(ign in app_lower for ign in IGNORE_SYSTEM_PROCS):
                send_telemetry(app_name, duration_sec=5)
                reported_count += 1
                
        await asyncio.sleep(5)

async def listen_to_server():
    """Tác vụ kết nối WebSocket: Lắng nghe lệnh điều khiển từ xa."""
    global active_ws, ALLOWED_TARGETS
    while True:
        try:
            active_port = get_backend_port()
            active_uri = f"ws://127.0.0.1:{active_port}/ws/agent/device_001"
            async with websockets.connect(active_uri) as websocket:
                active_ws = websocket
                print("✅ [WEBSOCKET] Đã kết nối tới Backend thành công!")
                await websocket.send("Hello from Client Agent (Online)")
                
                # Đồng bộ các rule được phép ngay khi kết nối
                sync_allowed_rules()

                while True:
                    response = await websocket.recv()
                    print(f"🔔 [LỆNH TỪ SERVER]: {response}")
                    
                    if "LOCK_MACHINE" in response:
                        print("🔒 [AGENT] Nhận lệnh khóa máy từ Phụ huynh! Đang khóa...")
                        lock_system()

                    try:
                        data = json.loads(response)
                        msg_type = data.get("type", "")
                        
                        if msg_type == "REQUEST_DECIDED":
                            req_info = data.get("data", {})
                            if req_info.get("status") == "APPROVED":
                                raw_target = req_info.get("clean_target") or req_info.get("target_detail", "")
                                clean_target = extract_domain(raw_target)
                                if clean_target:
                                    print(f"🔓 [AGENT] Phụ huynh đã duyệt cho phép: {clean_target}!")
                                    ALLOWED_TARGETS.add(clean_target.lower())
                                    unblock_websites([clean_target])
                                    
                                    # Gỡ từ khóa cấm nếu có
                                    for kw in list(BLOCKED_KEYWORDS):
                                        if kw in clean_target.lower() or clean_target.lower() in kw:
                                            BLOCKED_KEYWORDS.remove(kw)
                                            print(f"✅ Đã gỡ từ khóa cấm: {kw}")

                        elif msg_type in ["RULES_RESET", "FULL_RESET"]:
                            print("🔄 [AGENT] Nhận tín hiệu reset rules từ Phụ huynh!")
                            sync_allowed_rules()

                    except Exception:
                        pass
        except Exception as e:
            active_ws = None
            print(f"⚠️ Mất kết nối tới Server. Thử lại sau 5 giây... ({e})")
            await asyncio.sleep(5)

bedtime_locked = False

async def check_bedtime_task():
    """Tác vụ kiểm tra định kỳ khung giờ giới nghiêm (Bedtime Mode).
    Vô hiệu hóa máy tính sau bedtime (mặc định 22:00) và tự động mở lại vào wakeup (mặc định 06:00).
    """
    global bedtime_locked, BACKEND_HTTP
    while True:
        try:
            req = urllib.request.Request(f"{BACKEND_HTTP}/usage-stats/")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                is_bedtime = data.get("is_bedtime", False)
                b_hour = data.get("bedtime_hour", "22:00")
                w_hour = data.get("wakeup_hour", "06:00")

                if is_bedtime and not bedtime_locked:
                    bedtime_locked = True
                    print(f"🌙 [AGENT] Đã vào giờ giới nghiêm ({b_hour} -> {w_hour})! Tự động vô hiệu hóa máy tính để con nghỉ ngơi...")
                    lock_system()
                elif not is_bedtime and bedtime_locked:
                    bedtime_locked = False
                    print(f"🌅 [AGENT] Đã đến {w_hour} sáng! Kết thúc giờ giới nghiêm, mở lại hệ thống cho con.")
        except Exception:
            pass
        await asyncio.sleep(20)

async def main():
    print("🚀 [NT1] Trợ lý an toàn máy tính đã khởi động.")
    sync_allowed_rules()
    block_websites(BLOCKED_DOMAINS)
    await asyncio.gather(
        monitor_apps_task(),
        listen_to_server(),
        check_bedtime_task()
    )

if __name__ == "__main__":
    asyncio.run(main())
