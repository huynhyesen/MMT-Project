import os
import sys
import platform

WINDOWS_SERVICE_NAME = "MMTAgentService"
WINDOWS_DISPLAY_NAME = "MMT Parental Control Client Agent"

def generate_windows_install_script(working_dir: str = "", python_path: str = "") -> str:
    """Tạo lệnh PowerShell để đăng ký Windows Service và cấu hình chống tắt (Auto-Restart)."""
    base_dir = working_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    py_bin = python_path or sys.executable
    agent_script = os.path.join(base_dir, "agent", "agent_main.py")

    ps_script = f"""# ========================================================
# Script Cài đặt MMT Windows Service với cơ chế Chống Tắt
# Chạy script này bằng PowerShell (Run as Administrator)
# ========================================================

$ServiceName = "{WINDOWS_SERVICE_NAME}"
$DisplayName = "{WINDOWS_DISPLAY_NAME}"
$BinaryPath = '"{py_bin}" "{agent_script}"'

Write-Host "1. Đang tạo Windows Service: $ServiceName..." -ForegroundColor Cyan

# Kiểm tra nếu dịch vụ đã tồn tại
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {{
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    sc.exe delete $ServiceName
    Start-Sleep -Seconds 1
}}

# Tạo dịch vụ với tài khoản Hệ thống (NT AUTHORITY\\SYSTEM)
# Khi chạy dưới SYSTEM, người dùng chuẩn không thể tắt qua Task Manager!
sc.exe create $ServiceName binPath= "$BinaryPath" DisplayName= "$DisplayName" start= auto

# Cấu hình Cơ chế Chống Tắt (Recovery Failure Actions):
# Nếu tiến trình bị tắt qua Task Manager hoặc gặp sự cố:
# Lần 1: Tự động khởi động lại sau 1 giây
# Lần 2: Tự động khởi động lại sau 2 giây
# Các lần sau: Tự động khởi động lại sau 5 giây
sc.exe failure $ServiceName reset= 86400 actions= restart/1000/restart/2000/restart/5000

# Khởi động dịch vụ ngay lập tức
Start-Service -Name $ServiceName
Write-Host "✅ Dịch vụ $DisplayName đã được cài đặt và đang chạy ngầm an toàn!" -ForegroundColor Green
"""
    return ps_script

def install_windows_service():
    """Tạo file script cài đặt Windows Service."""
    out_path = os.path.join(os.path.dirname(__file__), "install_windows_service.ps1")
    script_content = generate_windows_install_script()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(script_content)
    print(f"✅ Đã tạo file cài đặt Windows Service tại: {out_path}")
    print("👉 Hướng dẫn: Mở PowerShell với quyền Administrator và chạy:")
    print(f"   powershell -ExecutionPolicy Bypass -File \"{out_path}\"")

if __name__ == "__main__":
    install_windows_service()
