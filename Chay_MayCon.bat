@echo off
title MMT Parental Control - Client Agent May Con
chcp 65001 >nul
cls

echo ========================================================
echo       MMT PARENTAL CONTROL - TRỢ LÝ AN TOÀN MÁY CON
echo ========================================================
echo.

:: 1. Kiểm tra Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [LỖI] Không tìm thấy Python trên máy tính của bạn!
    echo Vui lòng cài đặt Python và tích chọn "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

:: 2. Kích hoạt môi trường ảo nếu có
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

:: 3. Kiểm tra cài đặt thư viện
python -c "import websockets, psutil" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Đang cài đặt thư viện Agent...
    pip install -r requirements.txt
    echo.
)

:: 4. Tự động nhận diện Trạm Cha Mẹ trong mạng Wi-Fi
echo [*] Đang tự động dò tìm máy tính Cha Mẹ trong mạng Wi-Fi/LAN...
for /f "delims=" %%i in ('python -c "import sys; sys.path.insert(0, 'agent'); from lan_discovery import discover_parent_server; print(discover_parent_server(timeout=2.0) or '')"') do set pserver=%%i

if not "%pserver%"=="" (
    echo [OK] Đã tìm thấy Trạm Cha Mẹ: %pserver%
) else (
    set pserver=http://127.0.0.1:8008
)

if not exist agent\config.json (
    echo.
    echo [*] Thiết bị chưa ghép nối với máy cha mẹ.
    set /p pcode="Nhập mã ghép nối từ Cha Mẹ (VD: MMT-8842): "
    echo [*] Đang tiến hành ghép nối thiết bị...
    python agent\agent_main.py --pair-code %pcode% --server %pserver%
) else (
    echo [*] Đang khởi chạy Trợ lý An toàn ngầm...
    python agent\agent_main.py --server %pserver%
)

:: Tự động dọn dẹp và gỡ bỏ toàn bộ danh sách chặn file hosts khi tắt app
echo.
echo [*] Đang gỡ bỏ toàn bộ danh sách chặn file hosts trên máy con...
python -c "import sys; sys.path.insert(0, 'agent'); from blocker import unblock_all_websites; unblock_all_websites()" >nul 2>nul
echo [OK] Đã hoàn tất dọn dẹp và trả lại trạng thái mạng ban đầu!

echo.
pause
