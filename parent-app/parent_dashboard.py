import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import json
import urllib.request

API_BASE = "http://127.0.0.1:8008"

def send_api(endpoint, data=None, method="GET"):
    """Gửi HTTP request bằng urllib, tự động thử cổng 8008 và 8000."""
    global API_BASE
    for port in [8008, 8000, 8001, 8080]:
        base = f"http://127.0.0.1:{port}"
        try:
            url = f"{base}{endpoint}"
            payload = json.dumps(data).encode("utf-8") if data is not None else None
            req = urllib.request.Request(
                url, 
                data=payload, 
                headers={"Content-Type": "application/json"} if payload is not None else {}, 
                method=method
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                API_BASE = base
                return json.loads(resp.read().decode("utf-8")), None
        except Exception:
            continue
    return None, "Không thể kết nối Backend Server trên cổng 8008 hoặc 8000"

def save_settings():
    """Lưu cấu hình thời gian và danh sách web chặn"""
    limit = limit_var.get().strip()
    blocked_apps = blocked_text.get("1.0", tk.END).strip()
    
    if not limit or not limit.isdigit():
        messagebox.showwarning("Lỗi", "Vui lòng nhập số phút giới hạn hợp lệ!")
        return

    blocked_list = [k.strip() for k in blocked_apps.split(",") if k.strip()]
    payload = {
        "learning_limit_minutes": int(limit),
        "entertainment_limit_minutes": 45,
        "bedtime": "22:00",
        "allowed_sites": ["khanacademy.org", "wikipedia.org", "duolingo.com", "code.exe"],
        "blocked_sites": blocked_list
    }
    
    res, err = send_api("/onboarding/setup", payload, method="POST")
    if err:
        messagebox.showerror("Lỗi", f"Không thể lưu cấu hình: {err}")
    else:
        messagebox.showinfo("Thành công", "✅ Đã lưu cấu hình gốc thành công! Trẻ sẽ áp dụng quy tắc này.")

def load_requests():
    """Tải danh sách yêu cầu thực tế từ Backend"""
    for row in tree.get_children():
        tree.delete(row)
        
    data, err = send_api("/requests/")
    if err:
        return

    for req in data:
        tree.insert("", "end", values=(
            req["id"], 
            req["request_type"], 
            req.get("target_detail", ""), 
            req.get("reason_from_child", ""), 
            req["status"]
        ))

def approve_selected():
    """Phê duyệt yêu cầu đang chọn"""
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Chưa chọn", "Vui lòng chọn một yêu cầu trong bảng để duyệt!")
        return
    
    item = tree.item(selected[0])
    req_id = item["values"][0]

    payload = {
        "status": "APPROVED",
        "parent_feedback": "Cha mẹ đã đồng ý!"
    }
    res, err = send_api(f"/requests/{req_id}", payload, method="PATCH")
    if err:
        messagebox.showerror("Lỗi", f"Không thể duyệt: {err}")
    else:
        messagebox.showinfo("Thành công", f"✅ Đã phê duyệt yêu cầu #{req_id}!")
        load_requests()

def reject_selected():
    """Từ chối yêu cầu đang chọn"""
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("Chưa chọn", "Vui lòng chọn một yêu cầu để từ chối!")
        return
    
    item = tree.item(selected[0])
    req_id = item["values"][0]

    payload = {
        "status": "REJECTED",
        "parent_feedback": "Cha mẹ chưa thể đồng ý lúc này."
    }
    res, err = send_api(f"/requests/{req_id}", payload, method="PATCH")
    if err:
        messagebox.showerror("Lỗi", f"Không thể cập nhật: {err}")
    else:
        messagebox.showinfo("Đã từ chối", f"❌ Đã từ chối yêu cầu #{req_id}!")
        load_requests()

def lock_child_machine():
    """Gửi lệnh khóa máy tính con tức thì"""
    if messagebox.askyesno("Xác nhận", "Bạn có chắc chắn muốn KHÓA máy tính của con ngay bây giờ?"):
        res, err = send_api("/control/lock", {}, method="POST")
        if err:
            messagebox.showerror("Lỗi", f"Không thể gửi lệnh: {err}")
        else:
            messagebox.showinfo("Đã khóa", "🔒 Đã gửi lệnh khóa màn hình tới máy con!")

def unlock_child_machine():
    """Gửi lệnh mở khóa máy tính con"""
    res, err = send_api("/control/unlock", {}, method="POST")
    if err:
        messagebox.showerror("Lỗi", f"Không thể gửi lệnh: {err}")
    else:
        messagebox.showinfo("Đã mở khóa", "🔓 Đã gửi lệnh mở khóa màn hình cho con!")

def send_message_to_child():
    """Gửi lời nhắn tới máy con"""
    msg = simpledialog.askstring("Gửi lời nhắn", "Nhập thông điệp muốn hiển thị trên máy con:")
    if msg and msg.strip():
        res, err = send_api("/control/message", {"message": msg.strip()}, method="POST")
        if err:
            messagebox.showerror("Lỗi", f"Không thể gửi lời nhắn: {err}")
        else:
            messagebox.showinfo("Đã gửi", f"💬 Đã gửi lời nhắn: '{msg.strip()}' tới con!")

def reset_daily():
    """Reset sang ngày mới"""
    if messagebox.askyesno("Xác nhận", "Bắt đầu ngày mới? Thời gian đã dùng sẽ về 0 và danh sách việc tốt sẽ được mở lại."):
        res, err = send_api("/reset/daily", {}, method="POST")
        if err:
            messagebox.showerror("Lỗi", str(err))
        else:
            messagebox.showinfo("Thành công", "🌅 Đã reset sang ngày mới thành công!")

def reset_usage():
    """Reset thời gian sử dụng hôm nay về 0"""
    if messagebox.askyesno("Xác nhận Reset", "Đặt lại toàn bộ thời gian sử dụng hôm nay về 0 phút?"):
        res, err = send_api("/reset/usage", {}, method="POST")
        if err:
            messagebox.showerror("Lỗi", str(err))
        else:
            messagebox.showinfo("Thành công", "⏱️ Đã đặt lại thời gian sử dụng về 0!")

def reset_rules():
    """Reset danh sách quy tắc về mặc định"""
    if messagebox.askyesno("Xác nhận", "Khôi phục danh sách web/app về mặc định ban đầu?"):
        res, err = send_api("/reset/rules", {}, method="POST")
        if err:
            messagebox.showerror("Lỗi", str(err))
        else:
            messagebox.showinfo("Thành công", "🛡️ Đã đặt lại quy tắc về mặc định!")

def reset_all():
    """Khôi phục cài đặt gốc toàn diện"""
    if messagebox.askyesno("CẢNH BÁO", "Bạn có chắc muốn KHÔI PHỤC CÀI ĐẶT GỐC toàn bộ hệ thống?"):
        res, err = send_api("/reset/all", {}, method="POST")
        if err:
            messagebox.showerror("Lỗi", str(err))
        else:
            messagebox.showinfo("Thành công", "⚠️ Hệ thống đã được khôi phục về cài đặt gốc!")
            load_requests()

# ==========================================
# KHỞI TẠO GIAO DIỆN PHỤ HUYNH
# ==========================================
root = tk.Tk()
root.title("Trạm Điều Khiển - Phụ Huynh")
root.geometry("780x760")
root.configure(padx=20, pady=10)
root.resizable(False, False)

# Tiêu đề
tk.Label(root, text="🛡️ BẢNG ĐIỀU KHIỂN DÀNH CHO CHA MẸ", font=("Segoe UI", 15, "bold"), fg="#1e3a8a").pack(pady=(0, 8))

# --- KHU VỰC 1: ĐIỀU KHIỂN KHẨN CẤP & LỜI NHẮN ---
frame_ctrl = tk.LabelFrame(root, text=" ⚡ Điều khiển Khẩn cấp & Gửi Lời Nhắn ", font=("Segoe UI", 10, "bold"), fg="#dc2626", padx=12, pady=8)
frame_ctrl.pack(fill="x", pady=(0, 10))

ctrl_btn_frame = tk.Frame(frame_ctrl)
ctrl_btn_frame.pack(fill="x")
tk.Button(ctrl_btn_frame, text="🔒 Khóa máy ngay", bg="#dc2626", fg="white", font=("Segoe UI", 9, "bold"), command=lock_child_machine).pack(side="left", padx=4, expand=True, fill="x")
tk.Button(ctrl_btn_frame, text="🔓 Mở khóa máy", bg="#16a34a", fg="white", font=("Segoe UI", 9, "bold"), command=unlock_child_machine).pack(side="left", padx=4, expand=True, fill="x")
tk.Button(ctrl_btn_frame, text="💬 Gửi lời nhắn cho con", bg="#4f46e5", fg="white", font=("Segoe UI", 9, "bold"), command=send_message_to_child).pack(side="left", padx=4, expand=True, fill="x")

# --- KHU VỰC 2: CÀI ĐẶT CẤU HÌNH GỐC ---
frame_setup = tk.LabelFrame(root, text=" ⚙️ Thiết lập Quy tắc Gốc (Onboarding) ", font=("Segoe UI", 10, "bold"), fg="#d97706", padx=12, pady=8)
frame_setup.pack(fill="x", pady=(0, 10))

tk.Label(frame_setup, text="Thời gian dùng tối đa (phút/ngày):", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", pady=3)
limit_var = tk.StringVar(value="120")
tk.Entry(frame_setup, textvariable=limit_var, width=15, font=("Segoe UI", 9)).grid(row=0, column=1, sticky="w", pady=3, padx=10)

tk.Label(frame_setup, text="Danh sách cấm (cách nhau dấu phẩy):", font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=3)
blocked_text = tk.Text(frame_setup, height=2, width=45, font=("Segoe UI", 9))
blocked_text.insert("1.0", "youtube.com, facebook.com, discord, roblox")
blocked_text.grid(row=1, column=1, sticky="w", pady=3, padx=10)

tk.Button(frame_setup, text="💾 Lưu Cấu Hình Gốc", bg="#d97706", fg="white", font=("Segoe UI", 9, "bold"), command=save_settings).grid(row=2, column=0, columnspan=2, pady=5, sticky="we")

# --- KHU VỰC 3: YÊU CẦU TỪ CON CÁI ---
frame_req = tk.LabelFrame(root, text=" 📩 Yêu cầu từ máy con ", font=("Segoe UI", 10, "bold"), fg="#2563eb", padx=12, pady=8)
frame_req.pack(fill="both", expand=True, pady=(0, 10))

btn_frame = tk.Frame(frame_req)
btn_frame.pack(fill="x", pady=(0, 6))
tk.Button(btn_frame, text="🔄 Làm mới", bg="#3b82f6", fg="white", font=("Segoe UI", 9, "bold"), command=load_requests).pack(side="left", padx=(0, 5))
tk.Button(btn_frame, text="✅ Cho phép", bg="#10b981", fg="white", font=("Segoe UI", 9, "bold"), command=approve_selected).pack(side="left", padx=5)
tk.Button(btn_frame, text="❌ Từ chối", bg="#ef4444", fg="white", font=("Segoe UI", 9, "bold"), command=reject_selected).pack(side="left", padx=5)

# Bảng hiển thị (Treeview)
columns = ("ID", "Loại", "Mục tiêu", "Lý do", "Trạng thái")
tree = ttk.Treeview(frame_req, columns=columns, show="headings", height=6)
tree.heading("ID", text="ID")
tree.heading("Loại", text="Loại")
tree.heading("Mục tiêu", text="Mục tiêu")
tree.heading("Lý do", text="Lý do của con")
tree.heading("Trạng thái", text="Trạng thái")

tree.column("ID", width=35, anchor="center")
tree.column("Loại", width=130)
tree.column("Mục tiêu", width=140)
tree.column("Lý do", width=240)
tree.column("Trạng thái", width=95, anchor="center")
tree.pack(fill="both", expand=True)

# --- KHU VỰC 4: CÁC NÚT ĐẶT LẠI (RESET) ---
frame_reset = tk.LabelFrame(root, text=" 🔄 Cài Đặt Lại Hệ Thống (Reset) ", font=("Segoe UI", 10, "bold"), fg="#475569", padx=12, pady=8)
frame_reset.pack(fill="x")

reset_btn_frame = tk.Frame(frame_reset)
reset_btn_frame.pack(fill="x")
tk.Button(reset_btn_frame, text="🌅 Reset Ngày Mới", bg="#4f46e5", fg="white", font=("Segoe UI", 8, "bold"), command=reset_daily).pack(side="left", padx=3, expand=True, fill="x")
tk.Button(reset_btn_frame, text="⏱️ Reset Thời gian", bg="#64748b", fg="white", font=("Segoe UI", 8, "bold"), command=reset_usage).pack(side="left", padx=3, expand=True, fill="x")
tk.Button(reset_btn_frame, text="🛡️ Reset Quy tắc", bg="#64748b", fg="white", font=("Segoe UI", 8, "bold"), command=reset_rules).pack(side="left", padx=3, expand=True, fill="x")
tk.Button(reset_btn_frame, text="⚠️ Khôi phục gốc", bg="#b91c1c", fg="white", font=("Segoe UI", 8, "bold"), command=reset_all).pack(side="left", padx=3, expand=True, fill="x")

# Tự động load dữ liệu
root.after(500, load_requests)

if __name__ == "__main__":
    root.mainloop()
