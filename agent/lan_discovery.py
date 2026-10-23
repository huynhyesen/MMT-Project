import socket
import json
import threading
import time
from typing import Optional, Dict, Any

DISCOVERY_PORT = 8889
MAGIC_REQUEST = b"DISCOVER_MMT_PARENT_SERVER"

def start_discovery_responder(http_port: int = 8008) -> threading.Thread:
    """
    Khởi chạy dịch vụ UDP Responder ngầm trên máy Cha Mẹ.
    Tự động lắng nghe và phản hồi khi máy con trong mạng Wi-Fi/LAN dò tìm máy chủ.
    """
    def _responder_loop():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Lắng nghe trên tất cả các card mạng (Wi-Fi, Ethernet, Loopback)
            sock.bind(("", DISCOVERY_PORT))
            print(f"📡 [LAN DISCOVERY] Đã kích hoạt lắng nghe tự động nhận diện trên cổng UDP {DISCOVERY_PORT}")

            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                    if MAGIC_REQUEST in data:
                        # Phản hồi thông tin máy chủ cha mẹ về máy con
                        reply_payload = json.dumps({
                            "service": "MMT_PARENT_SERVER",
                            "http_port": http_port,
                            "server_name": socket.gethostname(),
                            "timestamp": time.time()
                        }).encode("utf-8")
                        sock.sendto(reply_payload, addr)
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ [LAN DISCOVERY] Không thể mở cổng lắng nghe UDP {DISCOVERY_PORT}: {e}")

    thread = threading.Thread(target=_responder_loop, daemon=True, name="LAN-Discovery-Responder")
    thread.start()
    return thread

def discover_parent_server(timeout: float = 2.0) -> Optional[str]:
    """
    Chạy trên máy con: Phát sóng UDP Broadcast để tự động tìm IP máy Cha Mẹ trong mạng Wi-Fi.
    Trả về URL máy chủ (VD: 'http://192.168.1.15:8008') hoặc None nếu không tìm thấy.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)

    # Gửi gói tin broadcast tới cả mạng LAN lẫn localhost
    targets = [
        ("255.255.255.255", DISCOVERY_PORT),
        ("127.0.0.1", DISCOVERY_PORT)
    ]
    for target in targets:
        try:
            sock.sendto(MAGIC_REQUEST, target)
        except Exception:
            pass

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            data, (ip, _) = sock.recvfrom(2048)
            info = json.loads(data.decode("utf-8"))
            if info.get("service") == "MMT_PARENT_SERVER":
                server_ip = ip
                # Nếu là loopback/0.0.0.0
                if server_ip in ("0.0.0.0", "127.0.0.1"):
                    server_ip = "127.0.0.1"
                port = info.get("http_port", 8008)
                sock.close()
                return f"http://{server_ip}:{port}"
        except socket.timeout:
            break
        except Exception:
            pass

    sock.close()
    return None

if __name__ == "__main__":
    import sys
    if "--server" in sys.argv:
        start_discovery_responder(8008)
        print("Đang phát dịch vụ... Nhấn Ctrl+C để dừng.")
        while True:
            time.sleep(1)
    else:
        print("🔍 Đang dò tìm máy tính Cha Mẹ trong mạng Wi-Fi...")
        found = discover_parent_server(timeout=3.0)
        if found:
            print(f"🎉 TÌM THẤY TRẠM CHA MẸ: {found}")
        else:
            print("❌ Không tìm thấy máy chủ trong mạng LAN/Wi-Fi.")

