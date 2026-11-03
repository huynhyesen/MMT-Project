@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title MMT Parental Control - Client Agent May Con

:: ========================================================
:: 0. CỐ ĐỊNH THƯ MỤC LÀM VIỆC & TỰ ĐỘNG YÊU CẦU QUYỀN ADMIN
:: ========================================================
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Đang yêu cầu quyền Quản trị viên ^(Administrator^) để quản lý hệ thống và file hosts...
    powershell -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
    exit /b
)

cls
echo ========================================================
echo       MMT PARENTAL CONTROL - TRỢ LÝ AN TOÀN MÁY CON
echo ========================================================
echo.

:: ========================================================
:: 1. KIỂM TRA PYTHON (Tránh bẫy Microsoft Store Alias)
:: ========================================================
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LỖI] Không tìm thấy Python hợp lệ trên máy tính của bạn!
    echo Vui lòng cài đặt Python 3.11+ và tích chọn "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

:: ========================================================
:: 2. TẠO MÔI TRƯỜNG ẢO NẾU CHƯA CÓ (Hoặc bị lỗi)
:: ========================================================
if not exist ".venv\Scripts\python.exe" (
    echo [*] Đang tạo môi trường ảo Python ^(.venv^)...
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo [LỖI] Không thể tạo môi trường ảo! Hãy kiểm tra lại bộ cài Python.
        pause
        exit /b 1
    )
)

:: ========================================================
:: 3. KÍCH HOẠT MÔI TRƯỜNG ẢO
:: ========================================================
call ".venv\Scripts\activate.bat"

:: ========================================================
:: 4. KIỂM TRA VÀ CÀI ĐẶT THƯ VIỆN ĐẦY ĐỦ
:: ========================================================
python -c "import websockets, psutil, win32api, requests" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Đang cài đặt / cập nhật thư viện cho Agent...
    python -m pip install --upgrade pip >nul 2>&1
    if exist "requirements.txt" (
        pip install -r requirements.txt
    ) else (
        pip install websockets psutil pywin32 requests
    )
    if !errorlevel! neq 0 (
        echo [LỖI] Cài đặt thư viện thất bại! Vui lòng kiểm tra kết nối Internet.
        pause
        exit /b 1
    )
    echo [OK] Hoàn tất cài đặt thư viện.
    echo.
)

:: ========================================================
:: 5. TỰ ĐỘNG DÒ TÌM TRẠM CHA MẸ TRONG MẠNG LAN
:: ========================================================
set "pserver="
echo [*] Đang tự động dò tìm máy tính Cha Mẹ trong mạng Wi-Fi/LAN...

for /f "usebackq delims=" %%i in (`python -c "import sys; sys.path.insert(0, 'agent'); from lan_discovery import discover_parent_server; res = discover_parent_server(timeout=2.5); print(res.strip() if res else '')" 2^>nul`) do (
    set "pserver=%%i"
)

if defined pserver (
    echo [OK] Đã tìm thấy Trạm Cha Mẹ: !pserver!
) else (
    echo [!] Không tìm thấy Trạm Cha Mẹ tự động qua LAN.
    set /p "input_server=Nhập địa chỉ Server Cha Mẹ (Nhấn Enter để dùng mặc định http://127.0.0.1:8008): "
    if "!input_server!"=="" (
        set "pserver=http://127.0.0.1:8008"
    ) else (
        set "pserver=!input_server!"
    )
    echo [*] Sử dụng địa chỉ Server: !pserver!
)

:: ========================================================
:: 6. GHÉP NỐI THIẾT BỊ HOẶC KHỞI CHẠY AGENT
:: ========================================================
if not exist "agent\config.json" (
    echo.
    echo [*] Thiết bị chưa ghép nối với máy Cha Mẹ.
    :ask_pair_code
    set "pcode="
    set /p "pcode=Nhập mã ghép nối từ Cha Mẹ: "
    if "!pcode!"=="" (
        echo [!] Mã ghép nối không được để trống!
        goto ask_pair_code
    )
    echo [*] Đang tiến hành ghép nối thiết bị với mã !pcode!...
    python "agent\agent_main.py" --pair-code "!pcode!" --server "!pserver!"
) else (
    echo.
    echo [*] Đang khởi chạy Trợ lý An toàn...
    python "agent\agent_main.py" --server "!pserver!"
)

:: ========================================================
:: 7. DỌN DẸP FILE HOSTS KHI TẮT APP
:: ========================================================
echo.
echo [*] Đang gỡ bỏ danh sách chặn trên file hosts và làm mới DNS...
python -c "import sys; sys.path.insert(0, 'agent'); from blocker import unblock_all_websites; unblock_all_websites()" >nul 2>&1
ipconfig /flushdns >nul 2>&1
echo [OK] Đã hoàn tất dọn dẹp và trả lại trạng thái mạng ban đầu!

echo.
pause
endlocal