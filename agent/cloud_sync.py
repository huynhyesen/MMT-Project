import os
import sys
import json
import hmac
import tempfile
import urllib.request
from typing import Optional, Dict, Any

from hwid import get_device_hwid, get_machine_info

CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), "config.local.json")
LEGACY_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_agent_config() -> Dict[str, Any]:
    """Đọc cấu hình định danh và ghép nối của Agent."""
    hwid = get_device_hwid()
    default_config = {
        "hwid": hwid,
        "device_name": f"PC-{hwid.split('-')[-1]}",
        "is_paired": False,
        "pairing_code": "",
        "backend_url": "http://127.0.0.1:8008",
        "cloud_relay_ws": "ws://127.0.0.1:8008",
        "last_sync": None
    }
    path = CONFIG_FILE_PATH if os.path.exists(CONFIG_FILE_PATH) else LEGACY_CONFIG_PATH
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_config.update(saved)
        except Exception:
            pass
    return default_config

def save_agent_config(cfg: Dict[str, Any]):
    """Lưu cấu hình Agent vào file cục bộ."""
    directory = os.path.dirname(CONFIG_FILE_PATH)
    fd, temporary = tempfile.mkstemp(prefix=".config-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(temporary, CONFIG_FILE_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def device_headers(config=None):
    if config is None:
        config = load_agent_config()
    credential = config.get("device_credential")
    return {"Authorization": f"Bearer {credential}"} if credential else {}


def dashboard_enrollment(config=None):
    if config is None:
        config = load_agent_config()
    device_id, _, token = config.get("device_credential", "").partition(".")
    if not token:
        return None
    key = hmac.digest(token.encode(), b"mmt-dashboard-enrollment", "sha256").hex()
    return f"{device_id}.{key}"


def child_dashboard_url(backend_http):
    base = f"{backend_http.rstrip('/')}/child/"
    enrollment = dashboard_enrollment()
    return f"{base}#device={enrollment}" if enrollment else base


def pair_with_backend(pairing_code: str, backend_http: str = "http://127.0.0.1:8008") -> Optional[Dict[str, Any]]:
    """
    Thực hiện ghép nối thiết bị với Backend bằng mã ghép nối (Pairing Code) của Cha Mẹ.
    Tự động lấy HWID phần cứng và gửi yêu cầu đăng ký.
    """
    backend_http = backend_http.rstrip("/")
    machine_info = get_machine_info()
    payload = json.dumps({
        "device_hwid": machine_info["hwid"],
        "pairing_code": pairing_code.strip().upper(),
        "device_name": machine_info["hostname"],
        "platform": machine_info["platform"]
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{backend_http}/devices/pair",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"🎉 Ghép nối thành công với máy chủ của Cha Mẹ!")
            print(f"• Thiết bị: {data.get('device_name')} ({data.get('device_hwid')})")
            print(f"• Quản lý cho: {data.get('child_name')}")
            print(f"• Hạn mức: {data.get('daily_limit_minutes')} phút | Giới nghiêm: {data.get('bedtime')}")

            # Lưu trạng thái ghép nối
            cfg = load_agent_config()
            cfg["is_paired"] = True
            cfg.pop("pairing_code", None)
            cfg["device_credential"] = data["device_credential"]
            cfg["backend_url"] = backend_http
            save_agent_config(cfg)
            return data
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode()
        print(f"❌ Lỗi ghép nối ({e.code}): {err_msg}")
    except Exception as e:
        print(f"❌ Không thể kết nối tới máy chủ Backend ({backend_http}): {e}")
    return None

def fetch_parent_config(hwid: str, backend_http: str = "http://127.0.0.1:8008") -> Optional[Dict[str, Any]]:
    """Tải cấu hình quy tắc mới nhất từ Phụ huynh."""
    try:
        req = urllib.request.Request(f"{backend_http}/devices/{hwid}/config", headers=device_headers())
        with urllib.request.urlopen(req, timeout=4) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--pair":
        code = sys.argv[2] if len(sys.argv) > 2 else input("Nhập mã ghép nối từ Phụ huynh (VD: MMT-8842): ")
        server = sys.argv[3] if len(sys.argv) > 3 else "http://127.0.0.1:8008"
        pair_with_backend(code, server)
    else:
        cfg = load_agent_config()
        cfg.pop("device_credential", None)
        cfg.pop("pairing_code", None)
        print("Cấu hình thiết bị hiện tại:", json.dumps(cfg, indent=2))
