import os
import sys
import threading
import time
import urllib.request
import json
import webbrowser
from typing import Optional

_tray_thread: Optional[threading.Thread] = None
_tray_root = None
_backend_url = "http://127.0.0.1:8008"
_remaining_text = "Đang kết nối..."

def start_tray_companion(backend_url: str = "http://127.0.0.1:8008") -> Optional[threading.Thread]:
    """
    Khởi chạy tiện ích khay hệ thống / widget nhỏ ở góc dưới màn hình máy con.
    Hiển thị thời gian còn lại theo thời gian thực và cho phép con 1-click mở Góc Của Con.
    """
    global _tray_thread, _backend_url
    _backend_url = backend_url.rstrip("/")

    if sys.platform != "win32" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return None

    def _gui_loop():
        global _tray_root
        try:
            import tkinter as tk

            root = tk.Tk()
            _tray_root = root
            root.title("MMT Companion")
            root.overrideredirect(True) # Bỏ viền cửa sổ chuẩn để làm widget thanh mảnh
            root.attributes("-topmost", True)
            root.configure(bg="#0f172a")

            # Đặt tọa độ ở góc dưới bên phải (trên thanh Taskbar Windows)
            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()
            win_w = 230
            win_h = 38
            pos_x = screen_w - win_w - 20
            pos_y = screen_h - win_h - 55
            root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")

            # Khung widget bo viền
            frame = tk.Frame(root, bg="#1e293b", bd=1, relief="solid", padx=8, pady=4)
            frame.pack(fill="both", expand=True)

            status_var = tk.StringVar(value="🛡️ MMT: Đang nạp...")
            label = tk.Label(
                frame, 
                textvariable=status_var, 
                font=("Segoe UI" if sys.platform == "win32" else "Arial", 9, "bold"), 
                fg="#38bdf8", 
                bg="#1e293b",
                cursor="hand2"
            )
            label.pack(side="left", padx=2)

            # Nút thu gọn / mở nhanh
            btn_open = tk.Button(
                frame,
                text="Mở ↗",
                font=("Arial", 8, "bold"),
                bg="#2563eb",
                fg="white",
                bd=0,
                padx=6,
                pady=2,
                cursor="hand2",
                command=lambda: webbrowser.open(f"{_backend_url}/child")
            )
            btn_open.pack(side="right", padx=2)

            # Click vào nhãn cũng mở web
            label.bind("<Button-1>", lambda e: webbrowser.open(f"{_backend_url}/child"))

            # Menu chuột phải
            menu = tk.Menu(root, tearoff=0, bg="#1e293b", fg="white", font=("Arial", 9))
            menu.add_command(label="🌐 Mở Góc Của Con", command=lambda: webbrowser.open(f"{_backend_url}/child"))
            menu.add_separator()
            menu.add_command(label="Ẩn tiện ích", command=root.withdraw)

            def _show_menu(event):
                try:
                    menu.tk_popup(event.x_root, event.y_root)
                finally:
                    menu.grab_release()

            frame.bind("<Button-3>", _show_menu)
            label.bind("<Button-3>", _show_menu)

            # Vòng lặp cập nhật thời gian còn lại từ Backend mỗi 15s
            def _update_stats():
                try:
                    req = urllib.request.Request(f"{_backend_url}/usage-stats/")
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        rem_sec = data.get("remaining_seconds", 0)
                        rem_min = rem_sec // 60
                        if rem_sec <= 0:
                            status_var.set("⏰ MMT: Hết giờ!")
                            label.configure(fg="#f43f5e")
                        elif rem_min < 15:
                            status_var.set(f"🟡 MMT: Còn {rem_min} phút")
                            label.configure(fg="#fbbf24")
                        else:
                            hours = rem_min // 60
                            mins = rem_min % 60
                            time_str = f"{hours}h{mins}p" if hours > 0 else f"{mins}p"
                            status_var.set(f"🛡️ MMT: Còn {time_str}")
                            label.configure(fg="#38bdf8")
                except Exception:
                    pass
                root.after(15000, _update_stats)

            root.after(1000, _update_stats)
            root.mainloop()
        except Exception as e:
            print(f"⚠️ [TRAY COMPANION] Không thể khởi chạy tiện ích khay hệ thống: {e}")

    _tray_thread = threading.Thread(target=_gui_loop, daemon=True, name="Tray-Companion-Thread")
    _tray_thread.start()
    return _tray_thread

def stop_tray_companion():
    """Đóng tiện ích khay hệ thống khi tắt Agent."""
    global _tray_root
    if _tray_root:
        try:
            _tray_root.after(0, _tray_root.destroy)
        except Exception:
            pass
        _tray_root = None

if __name__ == "__main__":
    start_tray_companion("http://127.0.0.1:8008")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

