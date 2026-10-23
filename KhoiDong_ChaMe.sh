#!/usr/bin/env bash
# ========================================================
#       MMT PARENTAL CONTROL - TRẠM ĐIỀU KHIỂN CHA MẸ
# ========================================================

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

echo "========================================================"
echo "      MMT PARENTAL CONTROL - TRẠM ĐIỀU KHIỂN CHA MẸ"
echo "========================================================"
echo ""

# 1. Kích hoạt môi trường ảo nếu có
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# 2. Kiểm tra thư viện
python3 -c "import fastapi, uvicorn, sqlalchemy, pydantic, websockets" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[*] Đang cài đặt thư viện cần thiết..."
    pip install -r requirements.txt
    echo ""
fi

# 3. Khởi động Backend
echo "[*] Đang khởi động Máy chủ Backend (Cổng 8008)..."
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8008 &
SERVER_PID=$!

sleep 2

# 4. Mở trình duyệt
echo "[*] Đang mở Trạm Phụ Huynh trên trình duyệt..."
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:8008/parent" >/dev/null 2>&1
elif command -v open >/dev/null 2>&1; then
    open "http://localhost:8008/parent" >/dev/null 2>&1
fi

echo ""
echo "========================================================"
echo " ✅ HỆ THỐNG ĐÃ SẴN SÀNG!"
echo " • Địa chỉ Trạm Cha Mẹ: http://localhost:8008/parent"
echo " • Địa chỉ Góc Con Cái: http://localhost:8008/child"
echo " (Nhấn Ctrl+C để dừng hệ thống)"
echo "========================================================"
echo ""

wait $SERVER_PID
