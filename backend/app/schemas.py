from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class TelemetryCreate(BaseModel):
    app_name: str
    domain: Optional[str] = None
    duration_seconds: int

class ChildRequestCreate(BaseModel):
    request_type: str # 'PERMISSION_WEB', 'PERMISSION_APP', 'TIME_EXTENSION'
    target_detail: Optional[str] = None
    reason_from_child: str
    category: Optional[str] = None
    requested_minutes: Optional[int] = 0

class ChildRequestResponse(BaseModel):
    id: int
    request_type: str
    target_detail: Optional[str] = None
    reason_from_child: str
    status: str
    parent_feedback: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class RequestActionUpdate(BaseModel):
    status: str # "APPROVED" hoặc "REJECTED"
    parent_feedback: Optional[str] = None

# Schemas cho Thống kê thời gian sử dụng & Giới hạn thời gian
class UsageItemResponse(BaseModel):
    app_name: str
    duration_minutes: int
    duration_formatted: str
    category: str
    tag: str # 'LEARNING', 'ENTERTAINMENT', 'SOCIAL', 'UTILITIES'
    icon: str
    badge_color: str
    percentage: float
    time_limit_minutes: int # Giới hạn do phụ huynh đặt (0 = Không giới hạn)
    remaining_minutes: int # Thời gian còn lại có thể dùng (phút)
    remaining_formatted: str # "Còn 35 phút" hoặc "Không giới hạn" hoặc "Đã hết giờ"
    is_expired: bool # True nếu đã dùng hết giờ giới hạn

class UsageStatsResponse(BaseModel):
    total_minutes: int
    total_formatted: str
    learning_minutes: int
    learning_formatted: str
    entertainment_minutes: int
    entertainment_formatted: str
    social_minutes: int
    social_formatted: str
    utilities_minutes: int
    utilities_formatted: str
    is_bedtime: bool = False
    bedtime_hour: str = "22:00"
    wakeup_hour: str = "06:00"
    child_name: Optional[str] = "Bé An"
    daily_limit_minutes: Optional[int] = 120
    remaining_minutes: Optional[int] = 120
    total_seconds: Optional[int] = 0
    remaining_seconds: Optional[int] = 7200
    extension_label: Optional[str] = None
    items: List[UsageItemResponse]

# Schemas cho Quy tắc cho phép / chặn Web và App
class AppWebRuleCreate(BaseModel):
    rule_type: str # 'APP' hoặc 'WEBSITE'
    target_value: str
    action: Optional[str] = "ALLOW" # 'ALLOW' hoặc 'BLOCK'
    time_limit_minutes: Optional[int] = 60 # Giới hạn thời gian mặc định

class SetLimitRequest(BaseModel):
    target_name: str
    time_limit_minutes: int

class AppWebRuleResponse(BaseModel):
    id: str
    device_id: Optional[str] = None
    rule_type: str
    target_value: str
    action: str
    time_limit_minutes: int
    used_minutes: int
    remaining_minutes: int
    remaining_formatted: str
    is_expired: bool

    class Config:
        from_attributes = True

# Schemas cho Gamification: Đổi việc tốt lấy giờ chơi
class TaskInitial(BaseModel):
    title: str
    description: Optional[str] = None
    reward_minutes: int = 15

# Schemas cho Thiết lập lần đầu (Onboarding Setup)
class OnboardingSetupRequest(BaseModel):
    learning_limit_minutes: int = 180
    entertainment_limit_minutes: int = 45
    bedtime: str = "22:00"
    wakeup_time: str = "06:00"
    allowed_sites: List[str] = ["khanacademy.org", "wikipedia.org", "duolingo.com"]
    blocked_sites: List[str] = ["youtube.com", "facebook.com", "discord.com", "tiktok.com", "roblox"]
    initial_tasks: Optional[List[TaskInitial]] = None

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    reward_minutes: int = 15

class TaskResponse(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    reward_minutes: int
    status: str # 'TODO', 'COMPLETED_WAITING_APPROVAL', 'APPROVED'
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# Schemas cho Hồ sơ trẻ em & Đăng nhập máy
class ChildProfileCreate(BaseModel):
    name: str
    avatar: Optional[str] = "🧒"
    age: Optional[int] = 10
    pin: Optional[str] = "1234"
    daily_limit_minutes: Optional[int] = 120

class ChildProfileResponse(BaseModel):
    id: int
    name: str
    avatar: str
    age: int
    pin: str
    daily_limit_minutes: int
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ChildLoginRequest(BaseModel):
    child_id: int
    pin: Optional[str] = None

# Schemas cho Cảnh báo truy cập web lạ / chưa phép
class AlertLogCreate(BaseModel):
    target_value: str
    reason: Optional[str] = "Truy cập web lạ chưa được cha mẹ cho phép"
    is_web: Optional[bool] = True

class AlertLogResponse(BaseModel):
    id: int
    target_value: str
    reason: str
    is_web: bool
    timestamp: datetime

    class Config:
        from_attributes = True

# Schemas cho Cập nhật Khung giờ giới nghiêm
class CurfewUpdateRequest(BaseModel):
    bedtime: str = "22:00"
    wakeup_time: str = "06:00"

class CurfewResponse(BaseModel):
    bedtime: str
    wakeup_time: str
    is_within_curfew: bool
