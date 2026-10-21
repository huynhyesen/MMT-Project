from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from datetime import datetime
import uuid
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False)
    role = Column(String(20), default="PARENT") # 'PARENT' hoặc 'CHILD'
    created_at = Column(DateTime, server_default=func.now(), default=datetime.utcnow)

class Device(Base):
    __tablename__ = "devices"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    device_name = Column(String(100), nullable=False)
    device_hwid = Column(String(100), unique=True, index=True, nullable=True) # Mã phần cứng độc nhất
    pairing_code = Column(String(20), unique=True, index=True, nullable=True) # Mã ghép nối (VD: MMT-8842)
    pairing_token = Column(String(100), nullable=True) # Token xác thực phiên
    is_paired = Column(Boolean, default=False) # Đã hoàn tất ghép nối hay chưa
    status = Column(String(20), default='OFFLINE') # 'ONLINE_LAN', 'ONLINE_WAN', 'OFFLINE'
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    child_profile_id = Column(Integer, ForeignKey("child_profiles.id"), nullable=True)
    platform = Column(String(50), default="Linux") # 'Windows', 'Linux'
    ip_address = Column(String(50), nullable=True)
    anti_tamper_active = Column(Boolean, default=True) # Chống tắt qua Task Manager / Systemd
    content_filter_active = Column(Boolean, default=True) # Bộ lọc AI văn bản & hình ảnh
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), default=datetime.utcnow)

class TimeLimit(Base):
    __tablename__ = "time_limits"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = Column(String, ForeignKey("devices.id"), nullable=True)
    category = Column(String(50), nullable=False, default="OVERALL") # 'LEARNING', 'ENTERTAINMENT', 'OVERALL'
    daily_limit_minutes = Column(Integer, default=120)
    bedtime = Column(String(10), default="22:00") # Khung giờ bắt đầu giới nghiêm
    wakeup_time = Column(String(10), default="06:00") # Khung giờ mở khóa lại buổi sáng

class AppWebRule(Base):
    __tablename__ = "app_web_rules"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = Column(String, ForeignKey("devices.id"), nullable=True)
    rule_type = Column(String(10), nullable=False) # 'APP' hoặc 'WEBSITE'
    target_value = Column(String(255), nullable=False) # VD: 'game.exe', 'youtube.com'
    action = Column(String(10), default='BLOCK') # 'BLOCK' hoặc 'ALLOW'
    time_limit_minutes = Column(Integer, default=60) # Giới hạn thời gian (phút), 0 = không giới hạn
    used_minutes = Column(Integer, default=0) # Thời gian đã dùng (phút)

class MinimalTelemetryLog(Base):
    __tablename__ = "minimal_telemetry_logs"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    app_name = Column(String(100), nullable=False)
    domain = Column(String(255), nullable=True)
    duration_seconds = Column(Integer, nullable=False, default=0)
    timestamp = Column(DateTime, server_default=func.now(), default=datetime.utcnow)

# Alias tương thích cho usage_logs
UsageLog = MinimalTelemetryLog

class ChildRequest(Base):
    __tablename__ = "child_requests"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    request_type = Column(String(50), nullable=False) # 'TIME_EXTENSION', 'PERMISSION_WEB', 'PERMISSION_APP'
    target_detail = Column(String(255), nullable=False, default="")
    reason_from_child = Column(Text, nullable=False)
    status = Column(String(20), default="PENDING")    # PENDING, APPROVED, REJECTED
    parent_feedback = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), default=datetime.utcnow)

TimeRequest = ChildRequest

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    reward_minutes = Column(Integer, default=15) # Số phút thưởng khi hoàn thành
    status = Column(String(30), default="TODO") # 'TODO', 'COMPLETED_WAITING_APPROVAL', 'APPROVED'
    created_at = Column(DateTime, server_default=func.now(), default=datetime.utcnow)

class ChildProfile(Base):
    """Hồ sơ cá nhân của trẻ để đăng nhập và áp dụng cài đặt riêng"""
    __tablename__ = "child_profiles"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String(100), nullable=False)
    avatar = Column(String(50), default="🧒")
    age = Column(Integer, default=10)
    pin = Column(String(10), default="1234") # Mã PIN đăng nhập
    daily_limit_minutes = Column(Integer, default=120)
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now(), default=datetime.utcnow)

class AlertLog(Base):
    """Nhật ký cảnh báo khi trẻ cố truy cập web lạ hoặc app bị cấm"""
    __tablename__ = "alert_logs"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    target_value = Column(String(255), nullable=False)
    reason = Column(String(255), nullable=False)
    category = Column(String(50), default="UNAPPROVED_ACCESS") # 'AI_CONTENT_TEXT', 'AI_CONTENT_IMAGE', 'ANTI_TAMPER_ATTEMPT', 'UNAPPROVED_ACCESS'
    is_web = Column(Boolean, default=True)
    timestamp = Column(DateTime, server_default=func.now(), default=datetime.utcnow)
