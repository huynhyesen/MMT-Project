import platform
import os
import psutil

# Cấu hình IP chuyển hướng cho cả IPv4 và IPv6
REDIRECT_IP_V4 = "127.0.0.1"
REDIRECT_IP_V6 = "::1"

# Xác định đường dẫn file hosts tùy theo hệ điều hành
if platform.system() == "Windows":
    HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
else:
    HOSTS_PATH = "/etc/hosts"

def extract_domain(target: str) -> str:
    """Trích xuất tên miền sạch từ chuỗi URL bất kỳ."""
    if not target:
        return ""
    t = target.split("[")[0].strip().lower()
    if "://" in t:
        t = t.split("://")[1]
    t = t.split("/")[0].split("?")[0].split(":")[0]
    if t.startswith("www."):
        t = t[4:]
    return t

def enforce_block_policy(target_name: str, reason: str, author: str):
    """
    Thực thi NT4 & NT6: Kiểm tra whitelist và hiển thị thông báo an toàn.
    """
    whitelist = ["111.vn", "schoolportal.edu.vn", "emergency", "khanacademy.org", "wikipedia.org", "duolingo.com"]
    if any(item in target_name.lower() for item in whitelist):
        return True

    print("\n" + "="*50)
    print(f"[THÔNG BÁO TỪ HỆ THỐNG AN TOÀN - NT4]")
    print(f"• Mục bị chặn: {target_name}")
    print(f"• Lý do: {reason}")
    print("="*50 + "\n")
    return False

def kill_blocked_process(process_name: str):
    """
    Tìm và buộc dừng (kill) tiến trình nếu phát hiện ứng dụng bị cấm đang chạy.
    """
    killed = False
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
                psutil.Process(proc.info['pid']).kill()
                killed = True
                print(f"🛑 [BLOCKER] Đã đóng ứng dụng vi phạm: {process_name}")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return killed

def block_websites(website_list: list):
    """
    Thêm các trang web bị cấm vào file hosts để chặn truy cập (bao gồm IPv4 và IPv6).
    """
    try:
        with open(HOSTS_PATH, "r+") as file:
            content = file.read()
            for website in website_list:
                domain = extract_domain(website)
                if domain and domain not in content:
                    file.write(f"\n{REDIRECT_IP_V4} {domain}")
                    file.write(f"\n{REDIRECT_IP_V4} www.{domain}")
                    file.write(f"\n{REDIRECT_IP_V6} {domain}")
                    file.write(f"\n{REDIRECT_IP_V6} www.{domain}")
                    print(f"🛑 Đã chặn website mức mạng (IPv4 & IPv6): {domain}")
    except PermissionError:
        print("⚠️ [LỖI] Không đủ quyền để chỉnh sửa file hosts! Vui lòng chạy Agent bằng quyền Root/Admin.")
    except Exception as e:
        print(f"⚠️ [LỖI] Không thể cập nhật file hosts: {e}")

def unblock_websites(website_list: list):
    """
    Xóa các trang web khỏi file hosts để cho phép truy cập lại (khi cha mẹ duyệt).
    """
    clean_domains = set()
    for w in website_list:
        d = extract_domain(w)
        if d:
            clean_domains.add(d)
            clean_domains.add(f"www.{d}")

    try:
        with open(HOSTS_PATH, "r") as file:
            lines = file.readlines()
            
        with open(HOSTS_PATH, "w") as file:
            for line in lines:
                parts = [p.lower() for p in line.strip().split()]
                # Nếu dòng chứa tên miền cần gỡ chặn thì bỏ qua dòng đó
                if any(d in parts for d in clean_domains):
                    continue
                file.write(line)
        print(f"✅ Đã gỡ chặn file hosts cho: {', '.join(clean_domains)}")
    except PermissionError:
        print(f"⚠️ [LỖI] Cần quyền Administrator/Root để chỉnh sửa file hosts gỡ chặn: {', '.join(clean_domains)}")
    except Exception as e:
        print(f"⚠️ [LỖI] Không thể gỡ chặn file hosts: {e}")

def lock_system():
    """
    Khóa màn hình máy tính khi nhận lệnh khẩn cấp từ Phụ huynh.
    """
    try:
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            print("🔒 [BLOCKER] Đã khóa màn hình Windows.")
        elif platform.system() == "Linux":
            os.system("loginctl lock-session 2>/dev/null || xdg-screensaver lock 2>/dev/null")
            print("🔒 [BLOCKER] Đã gọi lệnh khóa màn hình Linux.")
    except Exception as e:
        print(f"⚠️ [BLOCKER] Không thể khóa hệ thống: {e}")
