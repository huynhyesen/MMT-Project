import secrets
from typing import List

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import database, models, schemas
from ..services.realtime import manager


router = APIRouter(prefix="/devices", tags=["Devices"])


PAIRING_CODE_TTL_MINUTES = 10


def generate_pairing_code() -> str:
    """Generate a short-lived, single-use enrollment code."""
    return f"MMT-{secrets.token_hex(6).upper()}"


def _generate_unique_pairing_code(db: Session) -> str:
    for _ in range(100):
        code = generate_pairing_code()

        exists = (
            db.query(models.Device)
            .filter(models.Device.pairing_code == code)
            .first()
        )

        if not exists:
            return code

    raise HTTPException(
        status_code=503,
        detail="Không thể tạo mã ghép nối. Vui lòng thử lại."
    )


def _build_device_config(
    db: Session,
    device: models.Device,
    hwid_fallback: str | None = None
) -> schemas.DeviceConfigResponse:

    child = None

    if device.child_profile_id:
        child = (
            db.query(models.ChildProfile)
            .filter(
                models.ChildProfile.id == device.child_profile_id
            )
            .first()
        )

    # Chỉ lấy time limit của thiết bị này.
    # device_id=None được xem là cấu hình dùng chung.
    time_limit = (
        db.query(models.TimeLimit)
        .filter(
            or_(
                models.TimeLimit.device_id == device.id,
                models.TimeLimit.device_id.is_(None)
            )
        )
        .order_by(
            models.TimeLimit.device_id.is_not(None).desc()
        )
        .first()
    )

    # Chỉ lấy rule riêng của thiết bị và rule dùng chung.
    rules = (
        db.query(models.AppWebRule)
        .filter(
            or_(
                models.AppWebRule.device_id == device.id,
                models.AppWebRule.device_id.is_(None)
            )
        )
        .order_by(models.AppWebRule.device_id.is_not(None).desc())
        .all()
    )
    by_target = {}
    for rule in rules:
        by_target.setdefault(rule.target_value, rule)
    rules = by_target.values()

    allowed_rules = [
        rule.target_value
        for rule in rules
        if rule.action == "ALLOW"
    ]

    blocked_rules = [
        rule.target_value
        for rule in rules
        if rule.action == "BLOCK"
    ]

    return schemas.DeviceConfigResponse(
        device_hwid=device.device_hwid or hwid_fallback or "",
        device_name=device.device_name,
        child_name=child.name if child else "Chưa gán",
        daily_limit_minutes=(
            child.daily_limit_minutes if child else 120
        ),
        bedtime=(
            time_limit.bedtime
            if time_limit and time_limit.bedtime
            else "22:00"
        ),
        wakeup_time=(
            time_limit.wakeup_time
            if time_limit and time_limit.wakeup_time
            else "06:00"
        ),
        allowed_rules=allowed_rules,
        blocked_rules=blocked_rules,
        anti_tamper_enabled=device.anti_tamper_active,
        content_filter_enabled=device.content_filter_active,
    )


def refresh_pairing_code(db, device):
    device.pairing_code = _generate_unique_pairing_code(db)
    device.pairing_expires_at = (
        datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=PAIRING_CODE_TTL_MINUTES)
    )


def register_child_device(db, child, device_name):
    device = models.Device(
        child_profile_id=child.id,
        device_name=device_name,
        status="PENDING_PAIR",
        is_paired=False,
    )
    refresh_pairing_code(db, device)
    db.add(device)
    return device


@router.post("/create", response_model=schemas.DeviceResponse)
def create_device_profile(
    dev_data: schemas.DeviceCreateRequest,
    db: Session = Depends(database.get_db),
):
    """Enroll a device for a legacy profile that has no device yet."""
    if dev_data.child_profile_id is None:
        raise HTTPException(422, "Cần chỉ định hồ sơ trẻ.")
    child = db.get(models.ChildProfile, dev_data.child_profile_id)
    if child is None:
        raise HTTPException(404, "Không tìm thấy hồ sơ trẻ.")
    if db.query(models.Device).filter_by(child_profile_id=child.id).first():
        raise HTTPException(409, "Hồ sơ này đã có thiết bị.")
    name = dev_data.device_name.strip()
    if not name or len(name) > 100:
        raise HTTPException(422, "Tên thiết bị phải có từ 1 đến 100 ký tự.")
    device = register_child_device(db, child, name)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Hồ sơ đã có thiết bị hoặc mã đang được sử dụng.") from exc
    return device


@router.post(
    "/pair",
    response_model=schemas.DevicePairResponse
)
async def pair_device(
    pair_data: schemas.DevicePairRequest,
    db: Session = Depends(database.get_db)
):
    code = pair_data.pairing_code.strip().upper()
    hwid = pair_data.device_hwid.strip()

    if not hwid or len(hwid) > 100 or hwid == "parent_dashboard":
        raise HTTPException(
            status_code=422,
            detail="device_hwid không được để trống."
        )

    device = (
        db.query(models.Device)
        .filter(
            func.upper(models.Device.pairing_code) == code
        )
        .first()
    )

    if not device:
        raise HTTPException(
            status_code=404,
            detail="Mã ghép nối không hợp lệ."
        )

    # Không cho sử dụng lại mã đã ghép nối.
    if device.is_paired:
        raise HTTPException(
            status_code=409,
            detail="Mã ghép nối đã được sử dụng."
        )

    # Kiểm tra thời hạn.
    if (
        not device.pairing_expires_at
        or device.pairing_expires_at < datetime.now(timezone.utc).replace(tzinfo=None)
    ):
        raise HTTPException(
            status_code=410,
            detail="Mã ghép nối đã hết hạn. Hãy tạo mã mới."
        )

    # Một HWID không được gắn với hai profile.
    existing_device = (
        db.query(models.Device)
        .filter(models.Device.device_hwid == hwid)
        .first()
    )

    if existing_device and existing_device.id != device.id:
        raise HTTPException(
            status_code=409,
            detail="Thiết bị này đã được đăng ký."
        )

    if not device.child_profile_id:
        raise HTTPException(409, "Thiết bị chưa được gán cho hồ sơ trẻ.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    token = secrets.token_urlsafe(32)
    try:
        claimed = db.execute(
            update(models.Device).where(
                models.Device.id == device.id,
                models.Device.pairing_code == code,
                models.Device.pairing_expires_at > now,
                models.Device.is_paired.is_(False),
            ).values(
                device_hwid=hwid,
                is_paired=True,
                status="OFFLINE",
                platform=pair_data.platform or "Linux",
                ip_address=pair_data.ip_address,
                last_seen=now,
                pairing_code=None,
                pairing_expires_at=None,
                pairing_token=token,
            )
        )
        if claimed.rowcount != 1:
            raise HTTPException(409, "Mã ghép nối đã thay đổi hoặc hết hạn.")
        db.commit()
        db.refresh(device)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Thiết bị này đã được đăng ký.") from exc

    config = _build_device_config(db, device)

    await manager.send_to_device("parent_dashboard", {
        "type": "DEVICE_PAIRED",
        "device_id": device.id,
        "device_name": device.device_name,
        "device_hwid": device.device_hwid,
        "platform": device.platform,
    })

    return schemas.DevicePairResponse(
        **config.model_dump(), device_credential=f"{device.id}.{token}"
    )


@router.get(
    "/",
    response_model=List[schemas.DeviceResponse]
)
def get_devices(
    db: Session = Depends(database.get_db)
):
    """Return all registered devices."""

    devices = (
        db.query(models.Device)
        .order_by(models.Device.created_at.desc())
        .all()
    )

    # ConnectionManager stores WebSocket -> device_id.
    # Therefore, connected IDs must be checked in .values().
    connected_device_ids = set(
        manager.active_connections.values()
    )

    results = []

    for device in devices:
        child_name = None

        if device.child_profile_id:
            child = (
                db.query(models.ChildProfile)
                .filter(
                    models.ChildProfile.id
                    == device.child_profile_id
                )
                .first()
            )

            if child:
                child_name = child.name

        current_status = device.status

        if (
            device.device_hwid in connected_device_ids
            or device.id in connected_device_ids
        ):
            current_status = "ONLINE_WAN"
        elif not device.is_paired:
            current_status = "PENDING_PAIR"

        results.append(
            schemas.DeviceResponse(
                id=device.id,
                device_name=device.device_name,
                device_hwid=device.device_hwid,
                pairing_code=device.pairing_code,
                is_paired=device.is_paired,
                status=current_status,
                child_profile_id=device.child_profile_id,
                child_name=child_name,
                platform=device.platform,
                anti_tamper_active=device.anti_tamper_active,
                content_filter_active=device.content_filter_active,
                last_seen=device.last_seen,
                created_at=device.created_at
            )
        )

    return results


@router.get(
    "/{hwid}/config",
    response_model=schemas.DeviceConfigResponse
)
def get_device_config(
    hwid: str,
    request: Request,
    db: Session = Depends(database.get_db)
):
    """Return the latest configuration for a device."""

    device = (
        db.query(models.Device)
        .filter(models.Device.device_hwid == hwid)
        .first()
    )

    if not device:
        device = (
            db.query(models.Device)
            .filter(models.Device.id == hwid)
            .first()
        )

    if not device:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy thiết bị"
        )

    caller = getattr(request.state, "device", None)
    if caller and caller.id != device.id:
        raise HTTPException(404, "Không tìm thấy thiết bị.")
    device.last_seen = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(device)

    return _build_device_config(
        db,
        device,
        hwid_fallback=hwid
    )


@router.delete("/{device_id}")
async def delete_device(
    device_id: str,
    db: Session = Depends(database.get_db)
):
    """Delete a device profile."""

    device = (
        db.query(models.Device)
        .filter(models.Device.id == device_id)
        .first()
    )

    if not device:
        device = (
            db.query(models.Device)
            .filter(models.Device.device_hwid == device_id)
            .first()
        )

    if not device:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy thiết bị"
        )

    if device.child_profile_id:
        raise HTTPException(409, "Hãy quản lý thiết bị từ hồ sơ trẻ.")
    hwid = device.device_hwid
    db.query(models.TimeLimit).filter(models.TimeLimit.device_id == device.id).delete()
    db.query(models.AppWebRule).filter(models.AppWebRule.device_id == device.id).delete()

    db.delete(device)
    db.commit()
    if hwid:
        await manager.close_device(hwid)

    return {
        "status": "success",
        "message": "Đã xóa thiết bị thành công"
    }
