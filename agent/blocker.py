import platform
import os
import psutil

# Cấu hình IP chuyển hướng cho cả IPv4 và IPv6
REDIRECT_IP_V4 = "127.0.0.1"
REDIRECT_IP_V6 = "::1"

# Xác định đường dẫn file hosts tùy theo hệ điều hành hoặc biến môi trường tùy chỉnh
HOSTS_PATH = os.environ.get("MMT_HOSTS_PATH") or (
    r"C:\Windows\System32\drivers\etc\hosts" if platform.system() == "Windows" else "/etc/hosts"
)

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

def kill_blocked_process(process_target: str):
    """
    Tìm và buộc dừng (kill) tiến trình nếu phát hiện ứng dụng bị cấm đang chạy qua psutil.
    Hỗ trợ kiểm tra cả tên tiến trình (name) và dòng lệnh khởi chạy (cmdline).
    """
    killed = False
    target = process_target.lower().strip()
    if not target:
        return False

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            p_name = (proc.info.get('name') or "").lower()
            cmdline = " ".join(proc.info.get('cmdline') or []).lower()

            # Không bao giờ diệt nhầm các tiến trình hệ điều hành / runtime
            safe_system = ["python", "uvicorn", "bash", "systemd", "xorg", "gnome", "code", "vscode", "ssh", "agent"]
            if any(s in p_name for s in safe_system) and not any(target == s for s in [target]):
                continue

            target_clean = target.replace(".exe", "")
            matches = (
                p_name == target or 
                p_name == f"{target_clean}.exe" or 
                target_clean in p_name or 
                target_clean in cmdline
            )

            if matches:
                p = psutil.Process(proc.info['pid'])
                p.terminate()
                try:
                    p.wait(timeout=1)
                except psutil.TimeoutExpired:
                    p.kill()
                killed = True
                print(f"🛑 [BLOCKER] Đã đóng tiến trình vi phạm (PID {proc.info['pid']}): {p_name}")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return killed

def block_websites(website_list: list):
    """
    Thêm các trang web bị cấm vào file hosts để chặn truy cập (bao gồm IPv4 và IPv6).
    """
    clean_domains = set()
    for website in website_list:
        domain = extract_domain(website)
        if domain:
            clean_domains.add(domain)

    if not clean_domains:
        return

    try:
        if not os.path.exists(HOSTS_PATH):
            return
        with open(HOSTS_PATH, "r") as file:
            content = file.read()
            
        entries_to_add = []
        for domain in clean_domains:
            if f" {domain}" not in content:
                entries_to_add.append(f"{REDIRECT_IP_V4} {domain}")
                entries_to_add.append(f"{REDIRECT_IP_V4} www.{domain}")
                entries_to_add.append(f"{REDIRECT_IP_V6} {domain}")
                entries_to_add.append(f"{REDIRECT_IP_V6} www.{domain}")

        if entries_to_add:
            with open(HOSTS_PATH, "a") as file:
                file.write("\n" + "\n".join(entries_to_add) + "\n")
            print(f"🛑 [HOSTS] Đã chặn website mức mạng qua hosts: {', '.join(clean_domains)}")
    except PermissionError:
        print(f"⚠️ [HOSTS] Không đủ quyền chỉnh sửa file {HOSTS_PATH}. Cần quyền Root/Sudo để ghi hosts trực tiếp.")
    except Exception as e:
        print(f"⚠️ [HOSTS] Không thể cập nhật file hosts: {e}")

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

    if not clean_domains:
        return

    try:
        if not os.path.exists(HOSTS_PATH):
            return
        with open(HOSTS_PATH, "r") as file:
            lines = file.readlines()
            
        modified = False
        new_lines = []
        for line in lines:
            parts = [p.lower() for p in line.strip().split()]
            if any(d in parts for d in clean_domains):
                modified = True
                continue
            new_lines.append(line)

        if modified:
            with open(HOSTS_PATH, "w") as file:
                file.writelines(new_lines)
            print(f"✅ [HOSTS] Đã gỡ chặn file hosts cho: {', '.join(clean_domains)}")
    except PermissionError:
        print(f"⚠️ [HOSTS] Cần quyền Administrator/Root để chỉnh sửa file {HOSTS_PATH} gỡ chặn: {', '.join(clean_domains)}")
    except Exception as e:
        print(f"⚠️ [HOSTS] Không thể gỡ chặn file hosts: {e}")

def lock_system():
    """
    Khóa màn hình máy tính khi nhận lệnh khẩn cấp hoặc giờ giới nghiêm.
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
