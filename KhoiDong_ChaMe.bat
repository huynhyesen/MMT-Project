@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title MMT Parental Control - Khoi Dong May Cha Me

:: 0. Cố định thư mục làm việc về đúng thư mục chứa file .bat
cd /d "%~dp0"
cls

echo ========================================================
echo       MMT PARENTAL CONTROL - TRẠM ĐIỀU KHIỂN CHA MẸ
echo ========================================================
echo.

:: 1. Kiểm tra Python (Tránh bẫy Microsoft Store Alias trên Windows 10/11)
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LỖI] Không tìm thấy Python hợp lệ trên máy tính của bạn!
    echo Vui lòng tải và cài đặt Python 3.11+ từ https://www.python.org/
    echo Lưu ý: Nhớ tích chọn "Add python.exe to PATH" khi cài đặt.
    echo.
    pause
    exit /b 1
)

:: 2. Tạo môi trường ảo nếu chưa có (hoặc bị hỏng)
if not exist ".venv\Scripts\python.exe" (
    echo [*] Đang tạo môi trường ảo Python ^(.venv^)...
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo [LỖI] Không thể tạo môi trường ảo! Vui lòng kiểm tra lại bộ cài đặt Python.
        pause
        exit /b 1
    )
)

:: 3. Kích hoạt môi trường ảo
call ".venv\Scripts\activate.bat"

:: 4. Kiểm tra và cài đặt thư viện nếu thiếu
python -c "import fastapi, uvicorn, sqlalchemy, pydantic, websockets" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Đang tự động kiểm tra và cài đặt thư viện cần thiết...
    python -m pip install --upgrade pip >nul 2>&1
    if exist "requirements.txt" (
        pip install -r requirements.txt
    ) else (
        pip install fastapi uvicorn[standard] sqlalchemy pydantic websockets
    )
    if !errorlevel! neq 0 (
        echo [LỖI] Cài đặt thư viện thất bại! Vui lòng kiểm tra kết nối mạng.
        pause
        exit /b 1
    )
    echo [OK] Đã cài đặt xong thư viện.
    echo.
)

:: 5. Giải phóng cổng 8008 nếu có tiến trình cũ bị treo từ lần chạy trước
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8008" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" (
        echo [*] Đang giải phóng cổng 8008 từ phiên chạy trước ^(PID: %%a^)...
        taskkill /F /PID %%a >nul 2>&1
    )
)

:: 6. Tự động lấy địa chỉ IP LAN của máy Cha Mẹ
set "LAN_IP=127.0.0.1"
for /f "usebackq delims=" %%i in (`python -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8', 80)); print(s.getsockname()[0]); s.close()" 2^>nul`) do (
    set "LAN_IP=%%i"
)

:: 7. Khởi động Máy chủ Backend
echo [*] Đang khởi động Máy chủ Backend ^(Cổng 8008^)...
start "MMT Backend Server" /min ".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8008

:: 8. Chờ Server thực sự sẵn sàng nhận kết nối (tối đa 10 giây)
echo [*] Đang chờ máy chủ phản hồi...
for /l %%x in (1, 1, 10) do (
    timeout /t 1 /nobreak >nul
    netstat -an | findstr ":8008" | findstr "LISTENING" >nul 2>&1
    if !errorlevel! equ 0 goto server_ready
)

:server_ready
echo [*] Đang mở Trạm Phụ Huynh trên trình duyệt...
start "" "http://localhost:8008/parent"

echo.
echo ========================================================
echo  [OK] HỆ THỐNG ĐÃ SẴN SÀNG!
echo.
echo  - Địa chỉ trên máy này : http://localhost:8008/parent
echo  - Địa chỉ trong mạng LAN: http://!LAN_IP!:8008/parent
echo  - Địa chỉ cho máy con  : http://!LAN_IP!:8008/child
echo.
echo  ^(Nhấn phím bất kỳ tại cửa sổ này để DỪNG toàn bộ hệ thống^)
echo ========================================================
echo.
pause >nul

:: 9. Tự động tắt Backend Server khi người dùng nhấn phím thoát
echo [*] Đang dừng Máy chủ Backend ^(Cổng 8008^)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8008" ^| findstr "LISTENING"') do (
    if not "%%a"=="0" (
        taskkill /F /PID %%a >nul 2>&1
    )
)
echo [OK] Hệ thống đã dừng hoàn toàn.
timeout /t 1 /nobreak >nul
endlocal