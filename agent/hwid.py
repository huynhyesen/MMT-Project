import platform
import os
import uuid
import hashlib
import subprocess

def get_device_hwid() -> str:
    """
    Tạo hoặc truy xuất mã định danh phần cứng độc nhất (Hardware ID - HWID) của máy tính.
    Đảm bảo tính nhất quán qua các lần khởi động lại máy trên cả Windows và Linux.
    """
    system_type = platform.system()
    raw_id = ""

    if system_type == "Linux":
        # 1. Thử lấy từ /etc/machine-id hoặc /var/lib/dbus/machine-id
        for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        content = f.read().strip()
                        if content:
                            raw_id = f"LINUX-{content}"
                            break
                except Exception:
                    pass

    elif system_type == "Windows":
        # 1. Thử lấy MachineGuid từ Windows Registry
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            if guid:
                raw_id = f"WIN-{guid}"
        except Exception:
            pass

    # 2. Phương án dự phòng: Kết hợp MAC address của card mạng chính + Hostname + Kiến trúc CPU
    if not raw_id:
        try:
            mac_node = uuid.getnode()
            host_name = platform.node()
            proc_info = platform.processor() or platform.machine()
            raw_id = f"FALLBACK-{mac_node}-{host_name}-{proc_info}"
        except Exception:
            raw_id = f"GENERIC-{platform.node()}-{uuid.uuid4()}"

    # Băm SHA-256 và định dạng thành chuỗi HWID-XXXX-XXXX-XXXX-XXXX
    hashed = hashlib.sha256(raw_id.encode("utf-8")).hexdigest().upper()
    hwid = f"HWID-{hashed[0:4]}-{hashed[4:8]}-{hashed[8:12]}-{hashed[12:16]}"
    return hwid

def get_machine_info() -> dict:
    """Trả về thông tin chi tiết về phần cứng và hệ điều hành của thiết bị."""
    return {
        "hwid": get_device_hwid(),
        "hostname": platform.node(),
        "platform": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "mac_address": ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff) for ele in range(0, 8*6, 8)][::-1])
    }

if __name__ == "__main__":
    info = get_machine_info()
    print("Mã phần cứng (HWID):", info["hwid"])
    print("Hệ điều hành:", info["platform"], info["release"])
    print("Hostname:", info["hostname"])
    print("MAC Address:", info["mac_address"])
