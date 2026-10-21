import os
import sys
import platform
import subprocess

SERVICE_NAME = "mmt-agent.service"
SYSTEMD_PATH = f"/etc/systemd/system/{SERVICE_NAME}"

SYSTEMD_TEMPLATE = """[Unit]
Description=MMT Parental Control & Digital Well-being Client Agent
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory={working_dir}
ExecStart={python_path} {agent_script}
Restart=always
RestartSec=2s
KillMode=control-group
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

# Lớp bảo vệ bổ sung chống can thiệp từ người dùng thường
ProtectSystem=full
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
"""

def generate_service_file(working_dir: str = "", python_path: str = "") -> str:
    """Tạo nội dung file cấu hình Systemd unit."""
    base_dir = working_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    py_bin = python_path or sys.executable
    agent_script = os.path.join(base_dir, "agent", "agent_main.py")

    return SYSTEMD_TEMPLATE.format(
        working_dir=base_dir,
        python_path=py_bin,
        agent_script=agent_script
    )

def install_systemd_daemon() -> bool:
    """
    Cài đặt Agent thành Systemd Daemon chạy ngầm trên Linux.
    Yêu cầu quyền root.
    """
    if platform.system() != "Linux":
        print("⚠️ Tính năng Systemd Daemon chỉ khả dụng trên hệ điều hành Linux.")
        return False

    if os.geteuid() != 0:
        print("⚠️ Vui lòng chạy lệnh với quyền Root (sudo) để cài đặt dịch vụ hệ thống.")
        return False

    content = generate_service_file()
    try:
        with open(SYSTEMD_PATH, "w") as f:
            f.write(content)
        print(f"✅ Đã tạo file dịch vụ tại: {SYSTEMD_PATH}")

        # Nạp lại daemon và kích hoạt
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", SERVICE_NAME], check=True)
        print(f"🚀 [SYSTEMD] Dịch vụ {SERVICE_NAME} đã được kích hoạt và đang chạy ngầm an toàn!")
        return True
    except Exception as e:
        print(f"❌ Lỗi cài đặt Systemd service: {e}")
        return False

def uninstall_systemd_daemon() -> bool:
    """Gỡ bỏ dịch vụ Systemd."""
    if platform.system() != "Linux" or os.geteuid() != 0:
        print("⚠️ Cần quyền Root để gỡ bỏ dịch vụ.")
        return False
    try:
        subprocess.run(["systemctl", "stop", SERVICE_NAME], check=False)
        subprocess.run(["systemctl", "disable", SERVICE_NAME], check=False)
        if os.path.exists(SYSTEMD_PATH):
            os.remove(SYSTEMD_PATH)
        subprocess.run(["systemctl", "daemon-reload"], check=False)
        print("✅ Đã gỡ bỏ dịch vụ Systemd thành công.")
        return True
    except Exception as e:
        print(f"❌ Lỗi khi gỡ dịch vụ: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--install":
        install_systemd_daemon()
    elif len(sys.argv) > 1 and sys.argv[1] == "--uninstall":
        uninstall_systemd_daemon()
    else:
        print("Mẫu file dịch vụ Systemd sẽ tạo:\n")
        print(generate_service_file())
