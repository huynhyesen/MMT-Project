import asyncio
import websockets
import json
import time
import sys
import os
import atexit
import signal
import urllib.request

# Nạp các module thành phần cốt lõi của Agent
from monitor import get_active_app_metadata
from blocker import enforce_block_policy, kill_blocked_process, block_websites, unblock_websites, unblock_all_websites, lock_system, extract_domain
from hwid import get_device_hwid, get_machine_info
from cloud_sync import load_agent_config, save_agent_config, pair_with_backend, fetch_parent_config
from lan_discovery import discover_parent_server
from ai_filter.content_guard import AIContentGuard
from anti_tamper.supervisor import AntiTamperSupervisor, report_tamper_attempt
from kiosk_lock import show_kiosk_lock, hide_kiosk_lock, is_kiosk_active
from tray_companion import start_tray_companion, stop_tray_companion

_cleaned_up = False

def cleanup_agent():
    """
    Dọn dẹp hệ thống khi tắt ứng dụng trên máy con:
    - Xóa toàn bộ danh sách chặn trong file hosts (trả lại quyền truy cập mạng bình thường)
    - Đóng màn hình Kiosk khóa nếu đang hiển thị
    - Đóng tiện ích khay hệ thống (System Tray companion)
    """
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True
    print("\n🧹 [DỌN DẸP] Đang tắt ứng dụng và dọn dẹp hệ thống máy con...")
    try:
        unblock_all_websites()
    except Exception as e:
        print(f"⚠️ [DỌN DẸP] Lỗi khi gỡ chặn hosts: {e}")

    try:
        hide_kiosk_lock()
    except Exception:
        pass

    try:
        stop_tray_companion()
    except Exception:
        pass
    print("✅ [DỌN DẸP] Đã gỡ bỏ toàn bộ danh sách chặn và hoàn tất dọn dẹp.")

# Đăng ký dọn dẹp khi tiến trình kết thúc
atexit.register(cleanup_agent)

def _sig_handler(signum, frame):
    cleanup_agent()
    sys.exit(0)

try:
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
except Exception:
    pass

# Đăng ký bắt sự kiện đóng cửa sổ Console trên Windows
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
        def _console_ctrl_handler(ctrl_type):
            cleanup_agent()
            return False
        _global_handler_ref = HandlerRoutine(_console_ctrl_handler)
        kernel32.SetConsoleCtrlHandler(_global_handler_ref, True)
    except Exception:
        pass

DEVICE_HWID = get_device_hwid()
DEVICE_CONFIG = load_agent_config()

def resolve_backend_url():
    # 1. Nhận từ cờ dòng lệnh --server
    if "--server" in sys.argv:
        idx = sys.argv.index("--server")
        if idx + 1 < len(sys.argv):
            url = sys.argv[idx + 1].rstrip("/")
            if not url.startswith("http"):
                url = "http://" + url
            return url

    # 2. Đọc từ cấu hình đã lưu sau khi ghép nối thành công (nếu là IP mạng ngoài hoặc LAN)
    cfg_url = DEVICE_CONFIG.get("backend_url")
    if cfg_url and "127.0.0.1" not in cfg_url and "localhost" not in cfg_url:
        return cfg_url.rstrip("/")

    # 3. Quét cổng cục bộ 127.0.0.1 (khi test trên cùng 1 máy tính)
    for p in [8008, 8000, 8001, 8080]:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{p}/", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    return f"http://127.0.0.1:{p}"
        except Exception:
            pass

    # 4. Tự động nhận diện Trạm Cha Mẹ qua UDP Wi-Fi Broadcast (Zero-Configuration)
    discovered = discover_parent_server(timeout=1.5)
    if discovered:
        print(f"📡 [LAN DISCOVERY] Tự động tìm thấy Trạm Cha Mẹ trong mạng Wi-Fi: {discovered}")
        return discovered

    return cfg_url or "http://127.0.0.1:8008"

def get_ws_url(http_url: str):
    ws_base = http_url.replace("http://", "ws://").replace("https://", "wss://")
    return f"{ws_base}/ws/relay/{DEVICE_HWID}"

BACKEND_HTTP = resolve_backend_url()
URI = get_ws_url(BACKEND_HTTP)

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

def forward_ws_alert(alert_data: dict):
    """Callback chuyển tiếp cảnh báo AI qua WebSocket thời gian thực."""
    global active_ws
    if active_ws:
        try:
            asyncio.create_task(active_ws.send(json.dumps(alert_data)))
        except Exception:
            pass

ai_guard = AIContentGuard(backend_url=BACKEND_HTTP, ws_callback=forward_ws_alert)

def sync_allowed_rules():
    """Tải danh sách các quy tắc ALLOW và BLOCK từ server về Agent."""
    global ALLOWED_TARGETS, BLOCKED_DOMAINS, BLOCKED_KEYWORDS, BACKEND_HTTP
    urls_to_try = [f"{BACKEND_HTTP}/rules/"]
    if "127.0.0.1" in BACKEND_HTTP or "localhost" in BACKEND_HTTP:
        for p in [8008, 8000, 8001, 8080]:
            u = f"http://127.0.0.1:{p}/rules/"
            if u not in urls_to_try:
                urls_to_try.append(u)

    for u in urls_to_try:
        try:
            req = urllib.request.Request(u)
            with urllib.request.urlopen(req, timeout=2) as resp:
                rules = json.loads(resp.read().decode())
                base_u = u.replace("/rules/", "")
                BACKEND_HTTP = base_u
                ai_guard.backend_url = BACKEND_HTTP
                for r in rules:
                    val = extract_domain(r.get("target_value", ""))
                    if not val:
                        continue
                    val_lower = val.lower()
                    if r.get("action") == "ALLOW":
                        ALLOWED_TARGETS.add(val_lower)
                        # Gỡ khỏi danh sách cấm
                        for kw in list(BLOCKED_KEYWORDS):
                            if kw in val_lower or val_lower in kw:
                                BLOCKED_KEYWORDS.remove(kw)
                        unblock_websites([val])
                    elif r.get("action") == "BLOCK":
                        if "." in val_lower:
                            if val_lower not in BLOCKED_DOMAINS:
                                BLOCKED_DOMAINS.append(val_lower)
                            block_websites([val])
                        else:
                            if val_lower not in BLOCKED_KEYWORDS:
                                BLOCKED_KEYWORDS.append(val_lower)
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
    """Tác vụ chạy ngầm: Định kỳ quét, tắt ứng dụng bị cấm, lọc nội dung AI và gửi telemetry."""
    while True:
        metadata_list = get_active_app_metadata() 
        reported_count = 0
        
        for app in metadata_list:
            app_name = app.get("app_name", "")
            app_lower = app_name.lower()
            window_title = app.get("window_title", "")

            # 1. AI CONTENT FILTERING: Kiểm tra tiêu đề cửa sổ theo thời gian thực
            if window_title and not any(ign in app_lower for ign in IGNORE_SYSTEM_PROCS):
                filter_res = ai_guard.inspect_text(window_title, source_name=app_name)
                if filter_res and not filter_res.get("is_safe", True):
                    print(f"🛑 [AI CONTENT FILTER] Đã chặn cửa sổ vi phạm: '{window_title}' ({filter_res.get('label')})")
                    enforce_block_policy(app_name, filter_res.get("reason", "Nội dung độc hại"), "AI Content Filter")
                    kill_blocked_process(app_name)
                    continue

            # Nếu ứng dụng hoặc tiêu đề cửa sổ nằm trong danh sách đã được phép -> Bỏ qua không chặn
            is_allowed = any(allowed in app_lower or (window_title and allowed in window_title.lower()) for allowed in ALLOWED_TARGETS)
            if is_allowed:
                # Gửi telemetry thời gian học tập / sử dụng
                if reported_count < 3 and not any(ign in app_lower for ign in IGNORE_SYSTEM_PROCS):
                    send_telemetry(app_name, duration_sec=5)
                    reported_count += 1
                continue
            
            # Kiểm tra ứng dụng bị cấm / cần xin phép
            if any(keyword in app_lower or (window_title and keyword in window_title.lower()) for keyword in BLOCKED_KEYWORDS):
                enforce_block_policy(app_name, "Cần xin phép phụ huynh trước khi sử dụng ứng dụng này", "Phụ huynh")
                kill_blocked_process(app_name)
                
                # Ghi nhận cảnh báo về máy chủ Backend
                try:
                    alert_payload = json.dumps({
                        "target_value": app_name,
                        "reason": f"Cố mở ứng dụng/web '{app_name}' chưa được cha mẹ cho phép",
                        "category": "BLOCKED_APP",
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
    """Tác vụ kết nối WebSocket / Cloud Relay (Hỗ trợ cả LAN và WAN)."""
    global active_ws, ALLOWED_TARGETS
    while True:
        try:
            active_uri = get_ws_url(BACKEND_HTTP)
            async with websockets.connect(active_uri) as websocket:
                active_ws = websocket
                print(f"✅ [CLOUD RELAY] Đã kết nối kênh từ xa ({active_uri}) cho thiết bị: {DEVICE_HWID}")
                await websocket.send(json.dumps({
                    "type": "AGENT_ONLINE",
                    "device_hwid": DEVICE_HWID,
                    "machine_info": get_machine_info()
                }))
                
                # Đồng bộ cấu hình quy tắc ban đầu từ Phụ huynh
                sync_allowed_rules()

                while True:
                    response = await websocket.recv()
                    print(f"🔔 [LỆNH TỪ SERVER]: {response}")
                    
                    if "LOCK_MACHINE" in response:
                        print("🔒 [AGENT] Nhận lệnh khóa máy từ Phụ huynh! Đang khóa...")
                        show_kiosk_lock(
                            reason="Phụ huynh đã tạm khóa máy tính từ xa",
                            is_bedtime=False,
                            backend_url=BACKEND_HTTP
                        )
                        lock_system()
                    elif "UNLOCK_MACHINE" in response:
                        print("🔓 [AGENT] Nhận lệnh mở khóa máy từ Phụ huynh!")
                        time_limit_locked = False
                        hide_kiosk_lock()

                    try:
                        data = json.loads(response)
                        msg_type = data.get("type", "")
                        
                        if msg_type == "REQUEST_DECIDED":
                            req_info = data.get("data", {})
                            req_status = req_info.get("status")
                            req_type = req_info.get("request_type", "")
                            
                            if req_status == "APPROVED":
                                if "TIME" in req_type:
                                    limit_m = req_info.get("time_limit_minutes", 30)
                                    print(f"⏳ [AGENT] Phụ huynh đã duyệt cộng thêm {limit_m} phút sử dụng máy tính cho con!")
                                    time_limit_locked = False
                                    hide_kiosk_lock()
                                    sync_allowed_rules()
                                else:
                                    raw_target = req_info.get("clean_target") or req_info.get("target_detail", "")
                                    clean_target = extract_domain(raw_target)
                                    print(f"🔓 [AGENT] Phụ huynh đã duyệt cho phép: {clean_target or raw_target}!")
                                    if clean_target:
                                        ALLOWED_TARGETS.add(clean_target.lower())
                                        unblock_websites([clean_target])
                                        
                                        # Gỡ từ khóa cấm nếu có
                                        for kw in list(BLOCKED_KEYWORDS):
                                            if kw in clean_target.lower() or clean_target.lower() in kw:
                                                BLOCKED_KEYWORDS.remove(kw)
                                                print(f"✅ [AGENT] Đã gỡ từ khóa cấm: {kw}")
                                    sync_allowed_rules()

                        elif msg_type in ["RULES_RESET", "FULL_RESET", "RULES_UPDATED", "LIMIT_UPDATED", "ONBOARDING_UPDATED"]:
                            print("🔄 [AGENT] Nhận tín hiệu cập nhật cấu hình quy tắc từ Phụ huynh!")
                            if msg_type in ["RULES_RESET", "FULL_RESET", "LIMIT_UPDATED"]:
                                time_limit_locked = False
                                hide_kiosk_lock()
                            sync_allowed_rules()

                    except Exception:
                        pass
        except Exception as e:
            active_ws = None
            print(f"⚠️ Mất kết nối tới Server. Thử lại sau 5 giây... ({e})")
            await asyncio.sleep(5)

bedtime_locked = False
time_limit_locked = False

async def check_bedtime_task():
    """Tác vụ kiểm tra định kỳ khung giờ giới nghiêm (Bedtime Mode) & Hạn mức giờ sử dụng."""
    global bedtime_locked, time_limit_locked, BACKEND_HTTP
    while True:
        try:
            req = urllib.request.Request(f"{BACKEND_HTTP}/usage-stats/")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                is_bedtime = data.get("is_bedtime", False)
                b_hour = data.get("bedtime_hour", "22:00")
                w_hour = data.get("wakeup_hour", "06:00")
                rem_sec = data.get("remaining_seconds", 3600)
                daily_limit = data.get("daily_limit_minutes", 120)

                # 1. Kiểm tra giới nghiêm (Bedtime)
                if is_bedtime and not bedtime_locked:
                    bedtime_locked = True
                    print(f"🌙 [AGENT] Đã vào giờ giới nghiêm ({b_hour} -> {w_hour})! Tự động bật Kiosk khóa để con nghỉ ngơi...")
                    show_kiosk_lock(
                        reason=f"Đã đến giờ giới nghiêm nghỉ ngơi ({b_hour} - {w_hour})",
                        is_bedtime=True,
                        backend_url=BACKEND_HTTP
                    )
                    lock_system()
                elif not is_bedtime and bedtime_locked:
                    bedtime_locked = False
                    print(f"🌅 [AGENT] Đã đến {w_hour} sáng! Kết thúc giờ giới nghiêm, mở lại hệ thống cho con.")
                    hide_kiosk_lock()

                # 2. Kiểm tra hết thời gian sử dụng trong ngày (Daily Limit)
                if not is_bedtime:
                    if rem_sec <= 0 and not time_limit_locked:
                        time_limit_locked = True
                        print(f"⏰ [AGENT] Đã hết thời gian sử dụng hôm nay ({daily_limit} phút)! Bật Kiosk khóa...")
                        show_kiosk_lock(
                            reason=f"Đã hết thời gian sử dụng hôm nay ({daily_limit} phút)",
                            is_bedtime=False,
                            backend_url=BACKEND_HTTP
                        )
                    elif rem_sec > 60 and time_limit_locked:
                        time_limit_locked = False
                        print("⏳ [AGENT] Thời gian đã được cộng thêm. Đóng Kiosk khóa.")
                        hide_kiosk_lock()
        except Exception:
            pass
        await asyncio.sleep(15)

async def main():
    try:
        global DEVICE_CONFIG, BACKEND_HTTP
        DEVICE_CONFIG = load_agent_config()
        if DEVICE_CONFIG.get("backend_url"):
            BACKEND_HTTP = DEVICE_CONFIG["backend_url"].rstrip("/")
            ai_guard.backend_url = BACKEND_HTTP
        print(f"🚀 [AGENT] Trợ lý an toàn máy tính đã khởi động (HWID: {DEVICE_HWID})")
        
        # Khởi chạy tiện ích khay hệ thống (System Tray Companion)
        start_tray_companion(BACKEND_HTTP)

        # Kiểm tra trạng thái ghép nối
        if not DEVICE_CONFIG.get("is_paired"):
            print("💡 [HƯỚNG DẪN GHÉP NỐI]: Thiết bị chưa ghép nối với Phụ huynh.")
            print(f"   Mã phần cứng: {DEVICE_HWID}")
            print("   Để ghép nối, chạy: python agent_main.py --pair-code <MÃ_GHÉP_NỐI>")
        else:
            print(f"🔗 [GHÉP NỐI]: Đã ghép nối an toàn với máy chủ Phụ huynh.")
            p_cfg = fetch_parent_config(DEVICE_HWID, BACKEND_HTTP)
            if p_cfg:
                print(f"📥 [ĐỒNG BỘ]: Hạn mức: {p_cfg.get('daily_limit_minutes')}p | Giới nghiêm: {p_cfg.get('bedtime')}")

        sync_allowed_rules()
        block_websites(BLOCKED_DOMAINS)
        await asyncio.gather(
            monitor_apps_task(),
            listen_to_server(),
            check_bedtime_task()
        )
    finally:
        cleanup_agent()

if __name__ == "__main__":
    if "--unblock-all" in sys.argv:
        cleanup_agent()
        sys.exit(0)

    # Xử lý các cờ dòng lệnh
    if "--pair-code" in sys.argv:
        idx = sys.argv.index("--pair-code")
        if idx + 1 < len(sys.argv):
            p_code = sys.argv[idx + 1]
            pair_with_backend(p_code, BACKEND_HTTP)
    
    try:
        if "--supervisor" in sys.argv:
            # Khởi chạy dưới cơ chế chống tắt kép Anti-Tamper
            supervisor = AntiTamperSupervisor(target_script=os.path.abspath(__file__))
            supervisor.run_forever()
        else:
            asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup_agent()
