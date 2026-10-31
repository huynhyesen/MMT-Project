
import hashlib
import secrets
import string
import uuid

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import database, models, schemas
from ..services.classification import extract_target_name
from ..services.realtime import manager


router = APIRouter(
    prefix="/devices",
    tags=["Devices"]
)


def generate_pairing_code() -> str:
    """Generate a human-readable device pairing code."""
    digits = "".join(
        secrets.choice(string.digits)
        for _ in range(4)
    )
    return f"MMT-{digits}"


def _generate_unique_pairing_code(db: Session) -> str:
    """Generate a pairing code that does not already exist."""
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
    """Build the configuration returned to a paired device."""

    child = None

    if device.child_profile_id:
        child = (
            db.query(models.ChildProfile)
            .filter(
                models.ChildProfile.id == device.child_profile_id
            )
            .first()
        )

    daily_limit = (
        child.daily_limit_minutes
        if child else 120
    )
    child_name = child.name if child else "Bé An"

    time_limit = db.query(models.TimeLimit).first()

    bedtime = (
        time_limit.bedtime
        if time_limit and time_limit.bedtime
        else "22:00"
    )

    wakeup = (
        time_limit.wakeup_time
        if time_limit and time_limit.wakeup_time
        else "06:00"
    )

    rules = db.query(models.AppWebRule).all()

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
        child_name=child_name,
        daily_limit_minutes=daily_limit,
        bedtime=bedtime,
        wakeup_time=wakeup,
        allowed_rules=allowed_rules,
        blocked_rules=blocked_rules,
        anti_tamper_enabled=device.anti_tamper_active,
        content_filter_enabled=device.content_filter_active,
        admin_password_hash=hashlib.sha256(
            "admin123".encode()
        ).hexdigest()
    )


@router.post(
    "/create",
    response_model=schemas.DeviceResponse
)
async def create_device_profile(
    dev_data: schemas.DeviceCreateRequest,
    db: Session = Depends(database.get_db)
):
    """Create a device profile and its initial configuration."""

    code = _generate_unique_pairing_code(db)

    new_device = models.Device(
        device_name=dev_data.device_name.strip(),
        pairing_code=code,
        child_profile_id=dev_data.child_profile_id,
        status="PENDING_PAIR",
        is_paired=False,
        anti_tamper_active=True,
        content_filter_active=True
    )

    db.add(new_device)
    db.commit()
    db.refresh(new_device)

    # Create initial blocked rules when supplied by the parent.
    if dev_data.blocked_items:
        for item in dev_data.blocked_items:
            clean_item = extract_target_name(item)

            if not clean_item:
                continue

            rule_type = (
                "WEBSITE"
                if "." in clean_item
                else "APP"
            )

            existing_rule = (
                db.query(models.AppWebRule)
                .filter(
                    models.AppWebRule.target_value == clean_item
                )
                .first()
            )

            if not existing_rule:
                db.add(
                    models.AppWebRule(
                        device_id=new_device.id,
                        rule_type=rule_type,
                        target_value=clean_item,
                        action="BLOCK",
                        time_limit_minutes=30,
                        used_minutes=0
                    )
                )

        db.commit()

    # Update the selected child's daily time limit.
    if dev_data.child_profile_id:
        child = (
            db.query(models.ChildProfile)
            .filter(
                models.ChildProfile.id == dev_data.child_profile_id
            )
            .first()
        )

        if child and dev_data.daily_limit_minutes:
            child.daily_limit_minutes = (
                dev_data.daily_limit_minutes
            )
            db.commit()

    child_name = None

    if new_device.child_profile_id:
        child = (
            db.query(models.ChildProfile)
            .filter(
                models.ChildProfile.id == new_device.child_profile_id
            )
            .first()
        )

        if child:
            child_name = child.name

    await manager.broadcast_json({
        "type": "DEVICE_CREATED",
        "device_id": new_device.id,
        "device_name": new_device.device_name,
        "pairing_code": new_device.pairing_code
    })

    return schemas.DeviceResponse(
        id=new_device.id,
        device_name=new_device.device_name,
        device_hwid=new_device.device_hwid,
        pairing_code=new_device.pairing_code,
        is_paired=new_device.is_paired,
        status=new_device.status,
        child_profile_id=new_device.child_profile_id,
        child_name=child_name,
        platform=new_device.platform,
        anti_tamper_active=new_device.anti_tamper_active,
        content_filter_active=new_device.content_filter_active,
        last_seen=new_device.last_seen,
        created_at=new_device.created_at
    )


@router.post(
    "/pair",
    response_model=schemas.DeviceConfigResponse
)
async def pair_device(
    pair_data: schemas.DevicePairRequest,
    db: Session = Depends(database.get_db)
):
    """Pair an agent with a device profile using a pairing code."""

    code = pair_data.pairing_code.strip().upper()

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
            detail="Mã ghép nối không hợp lệ hoặc đã hết hạn."
        )

    device.device_hwid = pair_data.device_hwid
    device.is_paired = True
    device.status = "ONLINE_WAN"
    device.platform = pair_data.platform or "Linux"

    if pair_data.ip_address:
        device.ip_address = pair_data.ip_address

    device.last_seen = datetime.utcnow()
    device.pairing_token = str(uuid.uuid4())

    db.commit()
    db.refresh(device)

    config = _build_device_config(db, device)

    await manager.broadcast_json({
        "type": "DEVICE_PAIRED",
        "device_id": device.id,
        "device_name": device.device_name,
        "device_hwid": device.device_hwid,
        "child_name": config.child_name,
        "platform": device.platform
    })

    return config


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

    device.last_seen = datetime.utcnow()
    db.commit()
    db.refresh(device)

    return _build_device_config(
        db,
        device,
        hwid_fallback=hwid
    )


@router.delete("/{device_id}")
def delete_device(
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

    db.delete(device)
    db.commit()

    return {
        "status": "success",
        "message": "Đã xóa thiết bị thành công"
    }
