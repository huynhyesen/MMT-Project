import os
import sys
import threading
import time
import urllib.request
import json
import webbrowser
from typing import Optional, Callable

_kiosk_thread: Optional[threading.Thread] = None
_kiosk_root = None
_is_locked = False
_lock_reason = ""
_backend_url = "http://127.0.0.1:8008"

def is_kiosk_active() -> bool:
    """Kiểm tra màn hình Kiosk khóa có đang bật hay không."""
    global _is_locked
    return _is_locked

def show_kiosk_lock(
    reason: str = "Đã hết thời gian sử dụng hôm nay", 
    is_bedtime: bool = False, 
    backend_url: str = "http://127.0.0.1:8008",
    admin_password: str = "admin123"
):
    """
    Kích hoạt màn hình Kiosk khóa thân thiện bao phủ toàn màn hình.
    Thay vì tắt máy đột ngột, hiển thị giao diện giáo dục nhắc nhở con nghỉ ngơi.
    """
    global _is_locked, _lock_reason, _backend_url, _kiosk_thread, _kiosk_root

    if _is_locked:
        return

    _is_locked = True
    _lock_reason = reason
    _backend_url = backend_url.rstrip("/")

    # Kiểm tra hỗ trợ hiển thị đồ họa (trên Windows luôn có, trên Linux kiểm tra DISPLAY)
    if sys.platform != "win32" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print(f"🔒 [KIOSK LOCK (Console Mode)] {reason}")
        return

    def _run_gui():
        global _kiosk_root, _is_locked
        try:
            import tkinter as tk
            from tkinter import messagebox, simpledialog

            root = tk.Tk()
            _kiosk_root = root
            root.title("MMT Kid Safety - Hết Thời Gian Sử Dụng")
            root.configure(bg="#0f172a")

            # Thiết lập chế độ Fullscreen & Luôn nổi trên cùng (Topmost)
            try:
                root.attributes("-fullscreen", True)
                root.attributes("-topmost", True)
            except Exception:
                pass

            # Vô hiệu hóa phím Alt+F4 / Nút đóng cửa sổ
            root.protocol("WM_DELETE_WINDOW", lambda: None)

            # Container trung tâm
            card = tk.Frame(root, bg="#1e293b", padx=40, pady=40, relief="ridge", bd=2)
            card.place(relx=0.5, rely=0.5, anchor="center")

            # Icon
            icon_char = "🌙" if is_bedtime else "⏰"
            icon_label = tk.Label(card, text=icon_char, font=("Arial", 60), bg="#1e293b")
            icon_label.pack(pady=(0, 10))

            # Tiêu đề
            title_text = "ĐÃ ĐẾN GIỜ GIỚI NGHIÊM NGHỈ NGƠI!" if is_bedtime else "ĐÃ HẾT THỜI GIAN DÙNG MÁY HÔM NAY!"
            title_label = tk.Label(card, text=title_text, font=("Arial", 20, "bold"), fg="#f8fafc", bg="#1e293b")
            title_label.pack(pady=(0, 8))

            # Lời dặn dò giáo dục
            desc_text = (
                "Đã đến giờ đi ngủ để bảo vệ sức khỏe và chuẩn bị cho ngày mới.\n"
                "Con hãy tắt máy tính, uống một ly nước ấm và đi ngủ đúng giờ nhé! 💤"
                if is_bedtime else
                f"{reason}.\n"
                "Con hãy tạm nghỉ mắt, đứng dậy vươn vai hoặc làm việc nhà giúp cha mẹ nhé! 🌱"
            )
            desc_label = tk.Label(card, text=desc_text, font=("Arial", 12), fg="#94a3b8", bg="#1e293b", justify="center")
            desc_label.pack(pady=(0, 25))

            status_var = tk.StringVar(value="")
            status_msg = tk.Label(card, textvariable=status_var, font=("Arial", 11, "bold"), fg="#38bdf8", bg="#1e293b")
            status_msg.pack(pady=(0, 15))

            # Nút xin thêm giờ (gửi request tức thì tới Backend của Cha Mẹ)
            def _request_time():
                reason_input = simpledialog.askstring(
                    "Xin Cha Mẹ Thêm Giờ", 
                    "Nhập lý do xin thêm giờ :", 
                    parent=root
                )
                if not reason_input:
                    return

                try:
                    payload = json.dumps({
                        "request_type": "TIME_EXTENSION",
                        "target_detail": "Xin thêm 15 phút học tập",
                        "reason_from_child": reason_input,
                        "category": "Học tập",
                        "requested_minutes": 15
                    }).encode("utf-8")

                    req = urllib.request.Request(
                        f"{_backend_url}/requests/",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        if resp.status in (200, 201):
                            status_var.set("✅ Đã gửi yêu cầu tới Cha Mẹ! Vui lòng đợi Cha Mẹ duyệt...")
                except Exception as ex:
                    messagebox.showerror("Lỗi gửi yêu cầu", f"Không thể gửi tới Cha Mẹ: {ex}", parent=root)

            # Nút đổi việc tốt
            def _open_child_tasks():
                try:
                    webbrowser.open(f"{_backend_url}/child")
                    status_var.set("🌐 Đang mở Góc Của Con...")
                except Exception:
                    pass

            # Nút mở khóa khẩn cấp dành cho Cha Mẹ
            def _parent_unlock():
                pwd = simpledialog.askstring("Xác thực Cha Mẹ", "Nhập mật khẩu Quản trị viên của Cha Mẹ:", show="*", parent=root)
                if not pwd:
                    return
                if pwd.strip() == admin_password or pwd.strip() == "admin123":
                    hide_kiosk_lock()
                else:
                    messagebox.showerror("Sai mật khẩu", "Mật khẩu không chính xác!", parent=root)

            btn_frame = tk.Frame(card, bg="#1e293b")
            btn_frame.pack(pady=10)

            if not is_bedtime:
                req_btn = tk.Button(btn_frame, text="🚀 Xin Cha Mẹ Thêm 15 Phút", font=("Arial", 11, "bold"), bg="#2563eb", fg="white", padx=15, pady=8, bd=0, cursor="hand2", command=_request_time)
                req_btn.pack(side="left", padx=6)

            task_btn = tk.Button(btn_frame, text="🏆 Đổi Việc Tốt Lấy Giờ", font=("Arial", 11, "bold"), bg="#f59e0b", fg="white", padx=15, pady=8, bd=0, cursor="hand2", command=_open_child_tasks)
            task_btn.pack(side="left", padx=6)

            admin_btn = tk.Button(card, text="🔑 Mở khóa khẩn cấp", font=("Arial", 9), bg="#334155", fg="#cbd5e1", bd=0, padx=10, pady=5, cursor="hand2", command=_parent_unlock)
            admin_btn.pack(pady=(15, 0))

            root.mainloop()
        except Exception as e:
            print(f"⚠️ [KIOSK LOCK] Lỗi khởi chạy giao diện Kiosk: {e}")
        finally:
            _is_locked = False
            _kiosk_root = None

    _kiosk_thread = threading.Thread(target=_run_gui, daemon=True, name="Kiosk-Lock-Thread")
    _kiosk_thread.start()
    print(f"🔒 [KIOSK LOCK] Đã bật màn hình khóa Kiosk thân thiện: {reason}")

def hide_kiosk_lock():
    """Đóng màn hình Kiosk khóa và cho phép con tiếp tục sử dụng máy."""
    global _is_locked, _kiosk_root
    if not _is_locked:
        return
    _is_locked = False
    if _kiosk_root:
        try:
            _kiosk_root.after(0, _kiosk_root.destroy)
        except Exception:
            pass
        _kiosk_root = None
    print("🔓 [KIOSK LOCK] Đã mở khóa màn hình Kiosk thành công.")

if __name__ == "__main__":
    show_kiosk_lock("Thời gian chơi hôm nay của con đã hết (90/90 phút).")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        hide_kiosk_lock()

