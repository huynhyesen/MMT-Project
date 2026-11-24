import asyncio
from websockets.asyncio.client import connect
import json
import time
import sys
import os
import atexit
import signal
import urllib.request

# Nạp các module thành phần cốt lõi của Agent
from monitor import (
    elapsed_foreground_seconds, get_active_app_metadata, get_foreground_app, tracked_app,
)
from web_policy import (
    ADULT_BLOCK_DOMAINS, DEFAULT_BLOCKED_HOSTS, blocked_hosts_for_agent, is_adult_host, normalize_host,
)
from blocker import (
    enforce_block_policy, kill_blocked_process, block_websites, unblock_websites, unblock_all_websites,
    lock_system, extract_domain, matches_app_rule,
)
from hwid import get_device_hwid, get_machine_info
from cloud_sync import load_agent_config, device_headers, pair_with_backend, fetch_parent_config
from lan_discovery import discover_parent_server
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

DEFAULT_BLOCKED_KEYWORDS = {"discord", "youtube", "facebook", "tiktok", "roblox"}
BLOCKED_KEYWORDS = DEFAULT_BLOCKED_KEYWORDS.copy()
BLOCKED_DOMAINS = DEFAULT_BLOCKED_HOSTS | ADULT_BLOCK_DOMAINS

# Danh sách ứng dụng/web được phụ huynh cho phép
ALLOWED_TARGETS = set()

def sync_allowed_rules():
    """Apply the latest complete rule set and keep the current policy if the server is offline."""
    global ALLOWED_TARGETS, BLOCKED_DOMAINS, BLOCKED_KEYWORDS
    try:
        req = urllib.request.Request(f"{BACKEND_HTTP}/rules/", headers=device_headers(DEVICE_CONFIG))
        with urllib.request.urlopen(req, timeout=2) as response:
            rules = json.load(response)
    except (OSError, ValueError):
        return False
    if not isinstance(rules, list):
        return False

    blocked_domains = blocked_hosts_for_agent(rules)
    allowed_targets = set()
    allowed_domains = set()
    blocked_apps = set()
    for rule in rules:
        if rule["rule_type"] == "WEBSITE":
            host = normalize_host(rule["target_value"])
            if rule["action"] == "ALLOW" and host and not is_adult_host(host):
                allowed_domains.add(host)
        elif target := extract_domain(rule["target_value"]):
            if rule["action"] == "ALLOW":
                allowed_targets.add(target)
            elif rule["action"] == "BLOCK":
                blocked_apps.add(target)

    unblock_websites((BLOCKED_DOMAINS | allowed_domains) - blocked_domains)
    block_websites(blocked_domains)
    ALLOWED_TARGETS = allowed_targets
    BLOCKED_DOMAINS = blocked_domains
    BLOCKED_KEYWORDS = DEFAULT_BLOCKED_KEYWORDS | blocked_apps
    print(f"🔄 [AGENT] Đã đồng bộ {len(ALLOWED_TARGETS)} mục được phép.")
    return True


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
            headers={"Content-Type": "application/json", **device_headers(DEVICE_CONFIG)},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=1)
    except Exception:
        pass

async def monitor_apps_task():
    """Áp dụng quy tắc ứng dụng và ghi thời gian sử dụng ở tiền cảnh."""
    poll_interval = 5
    previous_app = None
    previous_sample = time.monotonic()
    while True:
        foreground_app = get_foreground_app()
        now = time.monotonic()
        metadata_list = get_active_app_metadata()
        blocked = set()
        
        for app in metadata_list:
            app_name = app.get("app_name", "")
            if not app_name or any(matches_app_rule(app_name, rule) for rule in ALLOWED_TARGETS):
                continue

            if any(matches_app_rule(app_name, rule) for rule in BLOCKED_KEYWORDS):
                if not kill_blocked_process(app_name):
                    continue
                enforce_block_policy(app_name, "Ứng dụng nằm trong quy tắc chặn.", "Phụ huynh")
                blocked.add(app_name.lower())

                # Ghi nhận cảnh báo về máy chủ Backend
                try:
                    alert_payload = json.dumps({
                        "target_value": app_name,
                        "reason": "Ứng dụng nằm trong danh sách chặn.",
                        "category": "BLOCKED_APP",
                        "is_web": False
                    }).encode("utf-8")
                    req = urllib.request.Request(
                        f"{BACKEND_HTTP}/alerts/",
                        data=alert_payload,
                        headers={"Content-Type": "application/json", **device_headers(DEVICE_CONFIG)},
                        method="POST"
                    )
                    urllib.request.urlopen(req, timeout=1)
                except Exception:
                    pass

        foreground_app = tracked_app(foreground_app)
        if foreground_app and foreground_app.lower() in blocked:
            foreground_app = None
        seconds = elapsed_foreground_seconds(previous_app, foreground_app, now - previous_sample, poll_interval)
        previous_app, previous_sample = foreground_app, now
        if seconds:
            send_telemetry(foreground_app, duration_sec=seconds)

        await asyncio.sleep(poll_interval)

async def listen_to_server(curfew_changed):
    """Tác vụ kết nối WebSocket / Cloud Relay (Hỗ trợ cả LAN và WAN)."""
    global time_limit_locked
    while True:
        try:
            active_uri = get_ws_url(BACKEND_HTTP)
            async with connect(active_uri, additional_headers=device_headers(DEVICE_CONFIG)) as websocket:
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
                    
                    try:
                        data = json.loads(response)
                        msg_type = data.get("type", "") if isinstance(data, dict) else ""
                    except (ValueError, TypeError):
                        continue

                    if msg_type == "LOCK_MACHINE":
                        print("🔒 [AGENT] Nhận lệnh khóa máy từ Phụ huynh! Đang khóa...")
                        show_kiosk_lock(
                            reason="Phụ huynh đã tạm khóa máy tính từ xa",
                            is_bedtime=False,
                            backend_url=BACKEND_HTTP
                        )
                        lock_system()
                    elif msg_type == "UNLOCK_MACHINE":
                        print("🔓 [AGENT] Nhận lệnh mở khóa máy từ Phụ huynh!")
                        time_limit_locked = False
                        hide_kiosk_lock()
                    elif msg_type == "CURFEW_UPDATED":
                        curfew_changed.set()

                    try:
                        
                        if msg_type == "REQUEST_DECIDED":
                            req_info = data.get("data", {})
                            req_status = req_info.get("status")
                            req_type = req_info.get("request_type", "")
                            
                            if req_status == "APPROVED":
                                if "TIME" in req_type:
                                    limit_m = req_info.get("time_limit_minutes", 30)
                                    print(f"⏳ [AGENT] Phụ huynh đã duyệt cộng thêm {limit_m} phút sử dụng máy tính cho con!")
                                    time_limit_locked = False
                                    if not bedtime_locked:
                                        hide_kiosk_lock()
                                    sync_allowed_rules()
                                else:
                                    sync_allowed_rules()

                        elif msg_type in ["RULES_RESET", "FULL_RESET", "RULES_UPDATED", "LIMIT_UPDATED", "ONBOARDING_UPDATED", "DAILY_RESET_TRIGGERED", "DAILY_RESET", "USAGE_RESET"]:
                            print(f"🔄 [AGENT] Nhận tín hiệu cập nhật / làm mới từ máy chủ ({msg_type})!")
                            if msg_type in ["RULES_RESET", "FULL_RESET", "LIMIT_UPDATED", "DAILY_RESET_TRIGGERED", "DAILY_RESET", "USAGE_RESET"]:
                                time_limit_locked = False
                                if not bedtime_locked:
                                    hide_kiosk_lock()
                            sync_allowed_rules()

                    except Exception:
                        pass
        except Exception as e:
            print(f"⚠️ Mất kết nối tới Server. Thử lại sau 5 giây... ({e})")
            await asyncio.sleep(5)

bedtime_locked = False
time_limit_locked = False

async def check_bedtime_task(curfew_changed):
    """Tác vụ kiểm tra định kỳ khung giờ giới nghiêm (Bedtime Mode) & Hạn mức giờ sử dụng."""
    global bedtime_locked, time_limit_locked, BACKEND_HTTP
    while True:
        try:
            req = urllib.request.Request(f"{BACKEND_HTTP}/usage-stats/", headers=device_headers(DEVICE_CONFIG))
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
                    elif rem_sec > 0 and time_limit_locked:
                        time_limit_locked = False
                        print("⏳ [AGENT] Thời gian đã được cộng thêm. Đóng Kiosk khóa.")
                        hide_kiosk_lock()
        except Exception:
            pass
        try:
            await asyncio.wait_for(curfew_changed.wait(), timeout=15)
        except TimeoutError:
            pass
        curfew_changed.clear()

async def main():
    try:
        global DEVICE_CONFIG, BACKEND_HTTP
        DEVICE_CONFIG = load_agent_config()
        if DEVICE_CONFIG.get("backend_url"):
            BACKEND_HTTP = DEVICE_CONFIG["backend_url"].rstrip("/")
        print(f"🚀 [AGENT] Trợ lý an toàn máy tính đã khởi động (HWID: {DEVICE_HWID})")
        
        if not DEVICE_CONFIG.get("device_credential"):
            print("Hãy tạo mã ghép nối trong hồ sơ trẻ và dùng --pair-code để đăng ký máy.")
            return

        start_tray_companion(BACKEND_HTTP)
        p_cfg = fetch_parent_config(DEVICE_HWID, BACKEND_HTTP)
        if p_cfg:
            print(f"📥 [ĐỒNG BỘ]: Hạn mức: {p_cfg.get('daily_limit_minutes')}p | Giới nghiêm: {p_cfg.get('bedtime')}")

        if not sync_allowed_rules():
            block_websites(BLOCKED_DOMAINS)
        curfew_changed = asyncio.Event()
        await asyncio.gather(
            monitor_apps_task(),
            listen_to_server(curfew_changed),
            check_bedtime_task(curfew_changed)
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
            if not pair_with_backend(p_code, BACKEND_HTTP):
                sys.exit(1)
    
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
