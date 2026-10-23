@echo off
title MMT Parental Control - Go Chan May Con
chcp 65001 >nul
cls

echo ========================================================
echo       MMT PARENTAL CONTROL - GỠ TOÀN BỘ CHẶN HOSTS
echo ========================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [LỖI] Không tìm thấy Python trên máy tính của bạn!
    pause
    exit /b 1
)

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo [*] Đang tiến hành xóa sạch toàn bộ quy tắc chặn trong file hosts...
python -c "import sys; sys.path.insert(0, 'agent'); from blocker import unblock_all_websites; unblock_all_websites()"

echo.
echo ========================================================
echo  ✅ ĐÃ KHÔI PHỤC TRẠNG THÁI MẠNG BÌNH THƯỜNG!
echo ========================================================
echo.
pause
