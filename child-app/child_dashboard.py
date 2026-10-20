import tkinter as tk
from tkinter import ttk, messagebox
import json
import urllib.request
import webbrowser

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

def open_url(target):
    """Mở trang web trong trình duyệt mặc định."""
    clean = target.strip()
    if not clean:
        return
    url = clean if clean.startswith("http") else f"https://{clean}"
    try:
        webbrowser.open_new_tab(url)
    except Exception as e:
        messagebox.showerror("Lỗi mở web", f"Không thể mở trình duyệt: {e}")

# ==========================================
# CÁC HÀM XỬ LÝ DỮ LIỆU
# ==========================================
def refresh_all():
    """Tải lại toàn bộ dữ liệu: thời gian, web được phép, việc tốt."""
    load_usage_stats()
    load_allowed_rules()
    load_tasks()

def load_usage_stats():
    data, err = send_api("/usage-stats/")
    if err or not data:
        time_status_label.config(text="Không thể kết nối máy chủ", fg="#ef4444")
        return

    used_str = data.get("total_formatted", "0 phút")
    bedtime = data.get("is_bedtime", False)
    bedtime_hour = data.get("bedtime_hour", "22:00")

    if bedtime:
        time_status_label.config(
            text=f"🌙 ĐÃ ĐẾN GIỜ ĐI NGỦ (Sau {bedtime_hour}) - Đã dùng: {used_str}", 
            fg="#dc2626"
        )
    else:
        time_status_label.config(
            text=f"🟢 Hôm nay đã dùng: {used_str} • Đang kết nối an toàn", 
            fg="#059669"
        )

def load_allowed_rules():
    for item in rules_tree.get_children():
        rules_tree.delete(item)

    data, err = send_api("/rules/")
    if err or not data:
        return

    for r in data:
        if r.get("action") == "ALLOW":
            val = r.get("target_value", "")
            rem = r.get("remaining_formatted", "")
            rtype = "🌐 Website" if r.get("rule_type") == "WEBSITE" or "." in val else "💻 Ứng dụng"
            rules_tree.insert("", "end", values=(val, rtype, rem))

def open_selected_web():
    selected = rules_tree.selection()
    if not selected:
        messagebox.showwarning("Chưa chọn", "Vui lòng chọn một trang web trong bảng để mở!")
        return
    val = rules_tree.item(selected[0])["values"][0]
    open_url(val)

def load_tasks():
    for item in tasks_tree.get_children():
        tasks_tree.delete(item)

    data, err = send_api("/tasks/")
    if err or not data:
        return

    for t in data:
        status_str = "Chưa làm"
        if t.get("status") == "COMPLETED_WAITING_APPROVAL":
            status_str = "⏳ Chờ cha mẹ duyệt"
        elif t.get("status") == "APPROVED":
            status_str = "🎉 Đã nhận thưởng"

        tasks_tree.insert("", "end", values=(
            t.get("id"),
            t.get("title", ""),
            f"+{t.get('reward_minutes', 0)} phút",
            status_str
        ))

def complete_selected_task():
    selected = tasks_tree.selection()
    if not selected:
        messagebox.showwarning("Chưa chọn", "Vui lòng chọn việc tốt bạn đã làm xong!")
        return

    task_id = tasks_tree.item(selected[0])["values"][0]
    res, err = send_api(f"/tasks/{task_id}/complete", method="PATCH")
    if err:
        messagebox.showerror("Lỗi", f"Không thể gửi báo cáo: {err}")
    else:
        messagebox.showinfo("Thành công", "🎉 Giỏi lắm! Đã gửi thông báo cho Cha Mẹ để nhận thưởng thêm giờ!")
        load_tasks()

def submit_time_request():
    minutes = time_var.get()
    reason = time_reason_text.get("1.0", tk.END).strip()
    
    if not reason:
        messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập lý do xin thêm giờ!")
        return

    payload = {
        "request_type": "TIME_EXTENSION",
        "target_detail": f"Xin thêm {minutes} phút",
        "category": "Học tập & Giáo dục",
        "requested_minutes": int(minutes),
        "reason_from_child": reason
    }
    
    res, err = send_api("/requests/", payload, method="POST")
    if err:
        messagebox.showerror("Lỗi kết nối", f"Không thể gửi yêu cầu: {err}")
    else:
        messagebox.showinfo("Thành công", f"Đã gửi yêu cầu xin thêm {minutes} phút cho cha mẹ!\nVui lòng chờ phản hồi.")
        time_reason_text.delete("1.0", tk.END)

def submit_unlock_request():
    target_type = type_var.get()
    detail = detail_entry.get().strip()
    reason = unlock_reason_text.get("1.0", tk.END).strip()
    cat = cat_var.get()
    
    if not detail or not reason:
        messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập đầy đủ tên Web/App và lý do!")
        return
        
    payload = {
        "request_type": f"PERMISSION_{target_type}",
        "target_detail": detail,
        "category": cat,
        "requested_minutes": 30,
        "reason_from_child": reason
    }
    
    res, err = send_api("/requests/", payload, method="POST")
    if err:
        messagebox.showerror("Lỗi kết nối", f"Không thể gửi yêu cầu: {err}")
    else:
        messagebox.showinfo("Thành công", f"Đã gửi yêu cầu xin phép mở '{detail}' tới cha mẹ!\nVui lòng chờ phê duyệt.")
        detail_entry.delete(0, tk.END)
        unlock_reason_text.delete("1.0", tk.END)

# ==========================================
# KHỞI TẠO GIAO DIỆN CHÍNH
# ==========================================
root = tk.Tk()
root.title("Child Dashboard - Góc Của Con")
root.geometry("640x720")
root.configure(padx=16, pady=12)
root.resizable(False, False)

# Tiêu đề & Status bar
tk.Label(root, text="🚀 GÓC HỌC TẬP & GIẢI TRÍ CỦA CON", font=("Segoe UI", 14, "bold"), fg="#1e293b").pack(pady=(0, 2))
time_status_label = tk.Label(root, text="Đang tải thông tin...", font=("Segoe UI", 9, "bold"), fg="#2563eb")
time_status_label.pack(pady=(0, 10))

# Tabs
notebook = ttk.Notebook(root)
notebook.pack(fill="both", expand=True)

# TAB 1: WEB & PHẦN MỀM ĐƯỢC PHÉP
tab1 = ttk.Frame(notebook, padding=10)
notebook.add(tab1, text="🌐 Web Cho Phép")

tk.Label(tab1, text="Danh sách các trang web & ứng dụng cha mẹ đã cho phép:", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 5))

rules_columns = ("Tên", "Loại", "Thời gian còn lại")
rules_tree = ttk.Treeview(tab1, columns=rules_columns, show="headings", height=10)
rules_tree.heading("Tên", text="Tên Web / App")
rules_tree.heading("Loại", text="Loại")
rules_tree.heading("Thời gian còn lại", text="Thời gian còn lại")
rules_tree.column("Tên", width=260)
rules_tree.column("Loại", width=120)
rules_tree.column("Thời gian còn lại", width=160)
rules_tree.pack(fill="both", expand=True, pady=(0, 8))

rules_btn_frame = tk.Frame(tab1)
rules_btn_frame.pack(fill="x")
tk.Button(rules_btn_frame, text="↗ Mở Trang Web Trong Trình Duyệt", bg="#2563eb", fg="white", font=("Segoe UI", 9, "bold"), command=open_selected_web).pack(side="left", padx=(0, 5), expand=True, fill="x")
tk.Button(rules_btn_frame, text="🔄 Làm mới", bg="#64748b", fg="white", font=("Segoe UI", 9, "bold"), command=refresh_all).pack(side="left", padx=5)

# TAB 2: ĐỔI VIỆC TỐT LẤY GIỜ CHƠI (GAMIFICATION)
tab2 = ttk.Frame(notebook, padding=10)
notebook.add(tab2, text="🏆 Việc Tốt Nhận Thưởng")

tk.Label(tab2, text="Làm việc nhà hoặc bài tập để nhận thêm giờ dùng máy tính:", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 5))

tasks_columns = ("ID", "Việc tốt", "Thưởng", "Trạng thái")
tasks_tree = ttk.Treeview(tab2, columns=tasks_columns, show="headings", height=10)
tasks_tree.heading("ID", text="ID")
tasks_tree.heading("Việc tốt", text="Việc tốt / Bài tập")
tasks_tree.heading("Thưởng", text="Thưởng")
tasks_tree.heading("Trạng thái", text="Trạng thái")
tasks_tree.column("ID", width=35, anchor="center")
tasks_tree.column("Việc tốt", width=280)
tasks_tree.column("Thưởng", width=90, anchor="center")
tasks_tree.column("Trạng thái", width=140, anchor="center")
tasks_tree.pack(fill="both", expand=True, pady=(0, 8))

tasks_btn_frame = tk.Frame(tab2)
tasks_btn_frame.pack(fill="x")
tk.Button(tasks_btn_frame, text="🏆 Báo Đã Làm Xong", bg="#d97706", fg="white", font=("Segoe UI", 9, "bold"), command=complete_selected_task).pack(side="left", padx=(0, 5), expand=True, fill="x")
tk.Button(tasks_btn_frame, text="🔄 Cập nhật", bg="#64748b", fg="white", font=("Segoe UI", 9, "bold"), command=load_tasks).pack(side="left", padx=5)

# TAB 3: XIN PHÉP CHA MẸ
tab3 = ttk.Frame(notebook, padding=10)
notebook.add(tab3, text="📩 Xin Phép Cha Mẹ")

# Xin thêm giờ
frame_time = tk.LabelFrame(tab3, text=" ⏳ Xin thêm thời gian ", font=("Segoe UI", 10, "bold"), padx=10, pady=8, fg="#2563eb")
frame_time.pack(fill="x", pady=(0, 10))

time_var = tk.IntVar(value=15)
frame_radios = tk.Frame(frame_time)
frame_radios.pack(fill="x", pady=(0, 5))
tk.Radiobutton(frame_radios, text="+15 Phút", variable=time_var, value=15).pack(side="left", expand=True)
tk.Radiobutton(frame_radios, text="+30 Phút", variable=time_var, value=30).pack(side="left", expand=True)
tk.Radiobutton(frame_radios, text="+60 Phút", variable=time_var, value=60).pack(side="left", expand=True)

tk.Label(frame_time, text="Lý do xin thêm giờ:", font=("Segoe UI", 8)).pack(anchor="w")
time_reason_text = tk.Text(frame_time, height=2, font=("Segoe UI", 9))
time_reason_text.pack(fill="x", pady=(2, 6))
tk.Button(frame_time, text="Gửi yêu cầu xin giờ ⏱️", bg="#2563eb", fg="white", font=("Segoe UI", 9, "bold"), command=submit_time_request).pack(fill="x", ipady=2)

# Xin mở Web/App
frame_unlock = tk.LabelFrame(tab3, text=" 🔓 Xin mở khóa Website / Ứng dụng ", font=("Segoe UI", 10, "bold"), padx=10, pady=8, fg="#059669")
frame_unlock.pack(fill="x")

tk.Label(frame_unlock, text="Loại mục:", font=("Segoe UI", 8)).pack(anchor="w")
type_var = tk.StringVar(value="WEBSITE")
type_dropdown = ttk.Combobox(frame_unlock, textvariable=type_var, state="readonly", font=("Segoe UI", 8))
type_dropdown['values'] = ("WEBSITE", "APP")
type_dropdown.pack(fill="x", pady=(1, 5))

tk.Label(frame_unlock, text="Gắn nhãn mục đích:", font=("Segoe UI", 8)).pack(anchor="w")
cat_var = tk.StringVar(value="Học tập & Giáo dục")
cat_dropdown = ttk.Combobox(frame_unlock, textvariable=cat_var, state="readonly", font=("Segoe UI", 8))
cat_dropdown['values'] = ("Học tập & Giáo dục", "Giải trí & Game", "Mạng xã hội & Chat", "Công cụ & Tiện ích")
cat_dropdown.pack(fill="x", pady=(1, 5))

tk.Label(frame_unlock, text="Địa chỉ Web hoặc tên App (VD: quizlet.com):", font=("Segoe UI", 8)).pack(anchor="w")
detail_entry = tk.Entry(frame_unlock, font=("Segoe UI", 9))
detail_entry.pack(fill="x", pady=(1, 5))

tk.Label(frame_unlock, text="Lý do muốn mở khóa:", font=("Segoe UI", 8)).pack(anchor="w")
unlock_reason_text = tk.Text(frame_unlock, height=2, font=("Segoe UI", 9))
unlock_reason_text.pack(fill="x", pady=(1, 6))

tk.Button(frame_unlock, text="Gửi yêu cầu xin phép 📩", bg="#059669", fg="white", font=("Segoe UI", 9, "bold"), command=submit_unlock_request).pack(fill="x", ipady=2)

# Tự động load dữ liệu sau khi mở
root.after(400, refresh_all)

if __name__ == "__main__":
    root.mainloop()
