import psutil
import time

def get_active_app_metadata():
    """
    Thực thi NT2: Chỉ thu thập tên ứng dụng, thời lượng và dấu thời gian.
    Tuyệt đối không thu thập URL đầy đủ, nội dung gõ phím hay chụp ảnh màn hình.
    """
    active_apps = []
    for proc in psutil.process_iter(['name']):
        try:
            p_name = proc.info.get('name')
            if p_name:
                active_apps.append({
                    "app_name": p_name,
                    "domain": None,  # Nếu là trình duyệt, chỉ lọc tên miền (domain) qua extension nếu cần
                    "duration_seconds": 5
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return active_apps