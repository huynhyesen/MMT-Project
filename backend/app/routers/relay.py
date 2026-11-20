
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from ..services.realtime import manager
from ..security import resolve_device, same_origin


router = APIRouter(tags=["Relay"])


ALLOWED_ACTIONS = {
    "MESSAGE",
    "LOCK_MACHINE",
    "UNLOCK_MACHINE",
    "RULES_UPDATED",
    "RULES_RESET",
    "LIMIT_UPDATED",
}


class RelayCommandRequest(BaseModel):
    target_hwid: str = Field(min_length=1, max_length=100)
    action: str = Field(default="MESSAGE", min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_hwid")
    @classmethod
    def validate_target_hwid(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target_hwid không được để trống")
        return value

    @field_validator("action")
    @classmethod
    def normalize_action(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("action không được để trống")
        return value


@router.websocket("/ws/relay/{device_hwid}")
async def cloud_relay_endpoint(
    websocket: WebSocket,
    device_hwid: str,
):
    device = resolve_device(websocket, agent_only=True) if same_origin(websocket) else None
    if not device or device.device_hwid != device_hwid or device_hwid == "parent_dashboard":
        await websocket.close(code=1008)
        return

    await manager.connect(device_hwid, websocket)
    try:
        await manager.send_to_device("parent_dashboard", {
            "type": "DEVICE_CONNECTED_WAN",
            "device_hwid": device_hwid,
        })
        while True:
            raw_data = await websocket.receive_text()
            try:
                message = json.loads(raw_data)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            message_type = message.get("type")
            if message_type == "PING":
                await websocket.send_json({"type": "PONG", "timestamp": time.time()})
            elif message_type in ("AGENT_ONLINE", "TELEMETRY", "AI_CONTENT_VIOLATION", "UNAPPROVED_ATTEMPT"):
                message["device_hwid"] = device_hwid
                await manager.send_to_device("parent_dashboard", message)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
        await manager.send_to_device("parent_dashboard", {
            "type": "DEVICE_DISCONNECTED_WAN",
            "device_hwid": device_hwid,
        })


@router.post("/relay/command")
async def send_relay_command(payload: RelayCommandRequest):
    target_hwid = payload.target_hwid
    action = payload.action

    if target_hwid == "parent_dashboard" or action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Action không được hỗ trợ: {action}",
        )

    message = {
        "type": action,
        "target_hwid": target_hwid,
        "sender": "parent_cloud",
        "data": payload.data,
        "timestamp": time.time(),
    }

    # Command phải được gửi đúng thiết bị đích, không broadcast toàn hệ thống.
    sent = await manager.send_to_device(target_hwid, message)

    if not sent:
        raise HTTPException(
            status_code=404,
            detail=f"Thiết bị {target_hwid} hiện không kết nối.",
        )

    return {
        "status": "success",
        "target_hwid": target_hwid,
        "action": action,
        "message": f"Đã gửi lệnh {action} đến {target_hwid}",
    }

