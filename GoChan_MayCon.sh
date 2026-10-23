#!/usr/bin/env bash
# ========================================================
#       MMT PARENTAL CONTROL - GỠ TOÀN BỘ CHẶN HOSTS
# ========================================================

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "========================================================"
echo "      MMT PARENTAL CONTROL - GỠ TOÀN BỘ CHẶN HOSTS"
echo "========================================================"
echo ""
echo "[*] Đang tiến hành xóa sạch toàn bộ quy tắc chặn trong file hosts..."
python3 -c "import sys; sys.path.insert(0, 'agent'); from blocker import unblock_all_websites; unblock_all_websites()"
echo ""
echo "========================================================"
echo "  ✅ ĐÃ KHÔI PHỤC TRẠNG THÁI MẠNG BÌNH THƯỜNG!"
echo "========================================================"
