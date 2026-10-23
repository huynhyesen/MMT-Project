#!/usr/bin/env bash
# ========================================================
#       MMT PARENTAL CONTROL - TRỢ LÝ AN TOÀN MÁY CON
# ========================================================

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

echo "========================================================"
echo "      MMT PARENTAL CONTROL - TRỢ LÝ AN TOÀN MÁY CON"
echo "========================================================"
echo ""

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Tự động gỡ bỏ danh sách chặn khi tắt / thoát script
cleanup() {
    echo ""
    echo "[*] Đang gỡ bỏ toàn bộ danh sách chặn file hosts trên máy con..."
    python3 -c "import sys; sys.path.insert(0, 'agent'); from blocker import unblock_all_websites; unblock_all_websites()" 2>/dev/null || true
    echo "[OK] Đã hoàn tất dọn dẹp và trả lại trạng thái mạng ban đầu!"
}
trap cleanup EXIT INT TERM

# Tự động nhận diện máy chủ Cha Mẹ trong mạng Wi-Fi
echo "[*] Đang tự động dò tìm máy tính Cha Mẹ trong mạng Wi-Fi/LAN..."
pserver=$(python3 -c "import sys; sys.path.insert(0, 'agent'); from lan_discovery import discover_parent_server; print(discover_parent_server(timeout=2.0) or '')")

if [ -n "$pserver" ]; then
    echo "[OK] Đã tìm thấy Trạm Cha Mẹ: $pserver"
else
    pserver="http://127.0.0.1:8008"
fi

# Chạy Agent với quyền sudo nếu có thể (để ghi /etc/hosts)
if [ ! -f "agent/config.json" ]; then
    echo "[*] Thiết bị chưa ghép nối với máy cha mẹ."
    read -p "Nhập mã ghép nối từ Cha Mẹ (VD: MMT-8842): " pcode

    echo "[*] Đang tiến hành ghép nối..."
    python3 agent/agent_main.py --pair-code "$pcode" --server "$pserver"
else
    echo "[*] Đang khởi chạy Trợ lý An toàn ngầm..."
    python3 agent/agent_main.py --server "$pserver"
fi
