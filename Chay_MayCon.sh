#!/usr/bin/env bash
# ========================================================
#       MMT PARENTAL CONTROL - TRỢ LÝ AN TOÀN MÁY CON
# ========================================================

set -u

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR" || exit 1

# 0. Tự động nâng quyền sudo (giữ nguyên biến môi trường GUI DISPLAY/XAUTHORITY)
if [ "$EUID" -ne 0 ]; then
    echo "[*] Đang yêu cầu quyền Quản trị viên (sudo) để quản lý /etc/hosts và hệ thống..."
    exec sudo -E bash "$0" "$@"
fi

# Xác định user thực tế (tránh tạo file .venv thuộc quyền sở hữu của root)
REAL_USER="${SUDO_USER:-$USER}"
VENV_PYTHON="$BASE_DIR/.venv/bin/python3"
VENV_PIP="$BASE_DIR/.venv/bin/pip"

clear
echo "========================================================"
echo "      MMT PARENTAL CONTROL - TRỢ LÝ AN TOÀN MÁY CON"
echo "========================================================"
echo ""

# 1. Kiểm tra Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[LỖI] Không tìm thấy Python 3 trên hệ thống!"
    echo "Hãy cài đặt bằng lệnh: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi

# 2. Tạo môi trường ảo nếu chưa có (kiểm tra trực tiếp file thực thi python trong .venv)
if [ ! -x "$VENV_PYTHON" ]; then
    echo "[*] Đang tạo môi trường ảo Python (.venv)..."
    rm -rf "$BASE_DIR/.venv"
    sudo -u "$REAL_USER" python3 -m venv "$BASE_DIR/.venv"
    if [ $? -ne 0 ] \vert{}\vert{} [ ! -x "$VENV_PYTHON" ]; then
        echo "[LỖI] Không thể tạo môi trường ảo (.venv)!"
        echo "Hãy chạy lệnh sau rồi thử lại: sudo apt update && sudo apt install -y python3-venv"
        rm -rf "$BASE_DIR/.venv"
        exit 1
    fi
fi

# 3. Kiểm tra và cài đặt thư viện cần thiết (lọc bỏ pywin32 nếu có trong requirements.txt)
if ! "$VENV_PYTHON" -c "import websockets, psutil, requests" >/dev/null 2>&1; then
    echo "[*] Đang cài đặt thư viện cần thiết cho Agent..."
    sudo -u "$REAL_USER" "$VENV_PIP" install --upgrade pip >/dev/null 2>&1
    if [ -f "requirements.txt" ]; then
        # Tránh lỗi nếu requirements.txt có chứa thư viện chỉ dành cho Windows như pywin32
        grep -v -iE "^pywin32" requirements.txt > .req_linux.tmp
        sudo -u "$REAL_USER" "$VENV_PIP" install -r .req_linux.tmp
        rm -f .req_linux.tmp
    else
        sudo -u "$REAL_USER" "$VENV_PIP" install websockets psutil requests
    fi

    if [ $? -ne 0 ]; then
        echo "[LỖI] Cài đặt thư viện thất bại! Vui lòng kiểm tra kết nối mạng."
        exit 1
    fi
    echo "[OK] Hoàn tất cài đặt thư viện."
    echo ""
fi

# 4. Cơ chế tự động gỡ bỏ danh sách chặn /etc/hosts khi tắt app (chỉ chạy đúng 1 lần)
CLEANED_UP=0
cleanup() {
    if [ "$CLEANED_UP" -eq 1 ]; then
        return
    fi
    CLEANED_UP=1

    echo ""
    echo "[*] Đang gỡ bỏ toàn bộ danh sách chặn trên /etc/hosts..."
    "$VENV_PYTHON" -c "import sys; sys.path.insert(0, 'agent'); from blocker import unblock_all_websites; unblock_all_websites()" 2>/dev/null || true

    # Xóa cache DNS trên Linux (nếu hệ thống dùng systemd-resolved hoặc resolvectl)
    if command -v resolvectl >/dev/null 2>&1; then
        resolvectl flush-caches 2>/dev/null || true
    elif command -v systemd-resolve >/dev/null 2>&1; then
        systemd-resolve --flush-caches 2>/dev/null || true
    fi

    # Đảm bảo config.json không bị khóa quyền bởi root
    if [ -f "agent/config.json" ] && [ -n "$REAL_USER" ]; then
        chown "$REAL_USER:$REAL_USER" "agent/config.json" 2>/dev/null || true
    fi

    echo "[OK] Đã hoàn tất dọn dẹp và trả lại trạng thái mạng ban đầu!"
}

# Chỉ bắt EXIT và xử lý INT/TERM chuyển về exit chuẩn để không bị chạy lặp 2 lần
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 5. Tự động nhận diện máy chủ Cha Mẹ trong mạng Wi-Fi/LAN
echo "[*] Đang tự động dò tìm máy tính Cha Mẹ trong mạng Wi-Fi/LAN..."
pserver=$("$VENV_PYTHON" -c "import sys; sys.path.insert(0, 'agent'); from lan_discovery import discover_parent_server; res = discover_parent_server(timeout=2.5); print(res.strip() if res else '')" 2>/dev/null || true)

if [ -n "$pserver" ]; then
    echo "[OK] Đã tìm thấy Trạm Cha Mẹ: $pserver"
else
    echo "[!] Không tìm thấy Trạm Cha Mẹ tự động qua LAN."
    read -r -p "Nhập địa chỉ Server Cha Mẹ (Nhấn Enter để dùng mặc định http://127.0.0.1:8008): " input_server
    if [ -z "$input_server" ]; then
        pserver="http://127.0.0.1:8008"
    else
        pserver="$input_server"
    fi
    echo "[*] Sử dụng địa chỉ Server: $pserver"
fi

# 6. Ghép nối thiết bị hoặc khởi chạy Agent (đã có quyền root để sửa /etc/hosts)
if [ ! -f "agent/config.json" ]; then
    echo ""
    echo "[*] Thiết bị chưa ghép nối với máy Cha Mẹ."
    while true; do
        read -r -p "Nhập mã ghép nối từ Cha Mẹ (VD: MMT-8842): " pcode