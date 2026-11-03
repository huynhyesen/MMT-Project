#!/usr/bin/env bash
# ========================================================
#       MMT PARENTAL CONTROL - TRẠM ĐIỀU KHIỂN CHA MẸ
# ========================================================

set -u

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR" || exit 1

VENV_PYTHON="$BASE_DIR/.venv/bin/python3"
VENV_PIP="$BASE_DIR/.venv/bin/pip"
PORT=8008
SERVER_PID=""

clear
echo "========================================================"
echo "      MMT PARENTAL CONTROL - TRẠM ĐIỀU KHIỂN CHA MẸ"
echo "========================================================"
echo ""

# 1. Kiểm tra Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[LỖI] Không tìm thấy Python 3 trên hệ thống!"
    echo "Hãy cài đặt bằng lệnh: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi

# 2. Tạo môi trường ảo nếu chưa có hoặc bị hỏng (ví dụ copy nhầm .venv từ Windows sang)
if [ ! -x "$VENV_PYTHON" ]; then
    echo "[*] Đang tạo môi trường ảo Python (.venv)..."
    rm -rf "$BASE_DIR/.venv"
    python3 -m venv "$BASE_DIR/.venv"
    if [ $? -ne 0 ] || [ ! -x "$VENV_PYTHON" ]; then
        echo "[LỖI] Không thể tạo venv! Hãy cài đặt: sudo apt update && sudo apt install -y python3-venv"
        rm -rf "$BASE_DIR/.venv"
        exit 1
    fi
fi

# 3. Kiểm tra và cài đặt thư viện (tự động lọc bỏ pywin32 trên Linux)
if ! "$VENV_PYTHON" -c "import fastapi, uvicorn, sqlalchemy, pydantic, websockets" >/dev/null 2>&1; then
    echo "[*] Đang cài đặt thư viện cần thiết cho Server..."
    "$VENV_PIP" install --upgrade pip >/dev/null 2>&1
    if [ -f "requirements.txt" ]; then
        grep -v -iE "^pywin32" requirements.txt > .req_server_linux.tmp
        "$VENV_PIP" install -r .req_server_linux.tmp
        rm -f .req_server_linux.tmp
    else
        "$VENV_PIP" install "fastapi" "uvicorn[standard]" "sqlalchemy" "pydantic" "websockets"
    fi

    if [ $? -ne 0 ]; then
        echo "[LỖI] Cài đặt thư viện thất bại! Vui lòng kiểm tra kết nối mạng."
        exit 1
    fi
    echo "[OK] Hoàn tất cài đặt thư viện."
    echo ""
fi

# 4. Giải phóng cổng 8008 nếu đang bị chiếm bởi phiên chạy cũ
OLD_PID=$(lsof -ti :"$PORT" 2>/dev/null || fuser "$PORT"/tcp 2>/dev/null || true)
if [ -n "$OLD_PID" ]; then
    echo "[*] Đang giải phóng cổng $PORT từ phiên chạy trước (PID: $OLD_PID)..."
    kill -9 $OLD_PID 2>/dev/null || true
    sleep 1
fi

# 5. Cơ chế dọn dẹp và tắt Backend sạch sẽ khi nhấn Ctrl+C hoặc đóng cửa sổ
STOPPED=0
cleanup() {
    if [ "$STOPPED" -eq 1 ]; then
        return
    fi
    STOPPED=1

    echo ""
    echo "[*] Đang dừng Máy chủ Backend (Cổng $PORT)..."
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill -TERM "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    echo "[OK] Hệ thống đã dừng hoàn toàn."
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 6. Tự động lấy địa chỉ IP LAN của máy Cha Mẹ
LAN_IP=$("$VENV_PYTHON" -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0]); s.close()" 2>/dev/null || echo "127.0.0.1")

# 7. Khởi động Backend
echo "[*] Đang khởi động Máy chủ Backend (Cổng $PORT)..."
"$VENV_PYTHON" -m uvicorn backend.app.main:app --host 0.0.0.0 --port "$PORT" &
SERVER_PID=$!

# 8. Chờ máy chủ thực sự sẵn sàng nhận kết nối (tối đa 15 lần x 0.5s)
echo "[*] Đang chờ máy chủ phản hồi..."
SERVER_READY=0
for _ in {1..15}; do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "[LỖI] Máy chủ Backend bị dừng đột ngột khi khởi động! Hãy kiểm tra log lỗi phía trên."
        exit 1
    fi
    if "$VENV_PYTHON" -c "import socket; s = socket.create_connection(('127.0.0.1', $PORT), timeout=0.5); s.close()" 2>/dev/null; then
        SERVER_READY=1
        break
    fi
    sleep 0.5
done

if [ "$SERVER_READY" -eq 0 ]; then
    echo "[!] Cảnh báo: Máy chủ khởi động chậm hơn dự kiến, vui lòng tải lại trình duyệt nếu chưa thấy trang."
fi

# 9. Mở trình duyệt (Hỗ trợ cả khi đang chạy dưới quyền sudo hoặc user thường)
echo "[*] Đang mở Trạm Phụ Huynh trên trình duyệt..."
TARGET_URL="http://localhost:$PORT/parent"
if [ "${EUID:-$(id -u)}" -eq 0 ] && [ -n "${SUDO_USER:-}" ]; then
    sudo -u "$SUDO_USER" xdg-open "$TARGET_URL" >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$TARGET_URL" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
    open "$TARGET_URL" >/dev/null 2>&1 &
fi

echo ""
echo "========================================================"
echo " ✅ HỆ THỐNG ĐÃ SẴN SÀNG!"
echo " • Địa chỉ trên máy này : http://localhost:$PORT/parent"
echo " • Địa chỉ LAN Cha Mẹ   : http://$LAN_IP:$PORT/parent"
echo " • Địa chỉ Góc Con Cái  : http://$LAN_IP:$PORT/child"
echo " (Nhấn Ctrl+C để dừng hệ thống)"
echo "========================================================"
echo ""

# Giữ script chạy và theo dõi tiến trình Uvicorn
wait "$SERVER_PID"