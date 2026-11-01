
import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from ..services.realtime import manager


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
    connected = False

    try:
        await manager.connect(device_hwid, websocket)
        connected = True

        await manager.broadcast_json({
            "type": "DEVICE_CONNECTED_WAN",
            "device_hwid": device_hwid,
        })

        while True:
            raw_data = await websocket.receive_text()

            try:
                message = json.loads(raw_data)
            except json.JSONDecodeError:
                # Tương thích với các Agent cũ gửi payload dạng text thuần.
                await manager.broadcast_text(
                    raw_data,
                    sender_ws=websocket,
                )
                continue

            # Chỉ xử lý PING nếu payload là JSON object.
            if not isinstance(message, dict):
                await manager.broadcast_text(
                    raw_data,
                    sender_ws=websocket,
                )
                continue

            message_type = str(message.get("type", "")).strip().upper()

            if message_type == "PING":
                await websocket.send_json({
                    "type": "PONG",
                    "timestamp": time.time(),
                })
                continue

            # Không cho Agent tự giả danh một thiết bị khác.
            message["device_hwid"] = device_hwid

            await manager.broadcast_json(
                message,
                sender_ws=websocket,
            )

    except WebSocketDisconnect:
        # Client đóng kết nối bình thường.
        pass
    finally:
        if connected:
            manager.disconnect(websocket)
            await manager.broadcast_json({
                "type": "DEVICE_DISCONNECTED_WAN",
                "device_hwid": device_hwid,
            })


@router.post("/relay/command")
async def send_relay_command(payload: RelayCommandRequest):
    target_hwid = payload.target_hwid
    action = payload.action

    if action not in ALLOWED_ACTIONS:
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

