@echo off
title MMT Parental Control - Khoi Dong May Cha Me
chcp 65001 >nul
cls

echo ========================================================
echo       MMT PARENTAL CONTROL - TRẠM ĐIỀU KHIỂN CHA MẸ
echo ========================================================
echo.

:: 1. Kiểm tra Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [LỖI] Không tìm thấy Python trên máy tính của bạn!
    echo Vui lòng tải và cài đặt Python từ https://www.python.org/
    echo Lưu ý: Nhớ tích chọn "Add python.exe to PATH" khi cài đặt.
    echo.
    pause
    exit /b 1
)

:: 2. Kích hoạt môi trường ảo nếu có
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

:: 3. Kiểm tra và cài đặt thư viện nếu thiếu
python -c "import fastapi, uvicorn, sqlalchemy, pydantic, websockets" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Đang tự động kiểm tra và cài đặt thư viện cần thiết...
    pip install -r requirements.txt
    echo.
)

echo [*] Đang khởi động Máy chủ Backend (Cổng 8008)...
start "MMT Backend Server" /min python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8008

:: Chờ 2 giây để server sẵn sàng
timeout /t 2 /nobreak >nul

echo [*] Đang mở Trạm Phụ Huynh trên trình duyệt...
start "" "http://localhost:8008/parent"

echo.
echo ========================================================
echo  ✅ HỆ THỐNG ĐÃ SẴN SÀNG!
echo.
echo  • Địa chỉ trên máy này: http://localhost:8008/parent
echo  • Địa chỉ cho máy con : http://[IP_MAY_TINH]:8008/child
echo.
echo  (Đóng cửa sổ này hoặc cửa sổ Backend để dừng hệ thống)
echo ========================================================
echo.
pause
