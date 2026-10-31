import json
import time

from typing import Any
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

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
    action: str = "MESSAGE"
    data: dict[str, Any] = Field(default_factory=dict)


@router.websocket("/ws/relay/{device_hwid}")
async def cloud_relay_endpoint(
    websocket: WebSocket,
    device_hwid: str
):
    await manager.connect(device_hwid, websocket)

    try:
        await manager.broadcast_json({
            "type": "DEVICE_CONNECTED_WAN",
            "device_hwid": device_hwid,
        })

        while True:
            raw_data = await websocket.receive_text()

            try:
                message = json.loads(raw_data)

                if not isinstance(message, dict):
                    continue

                message_type = message.get("type", "")

                if message_type == "PING":
                    await websocket.send_json({
                        "type": "PONG",
                        "timestamp": time.time(),
                    })
                    continue

                # Không cho Agent tự giả danh một thiết bị khác.
                message["device_hwid"] = device_hwid

                # Giữ cơ chế thông báo realtime hiện tại.
                await manager.broadcast_json(
                    message,
                    sender_ws=websocket
                )

            except json.JSONDecodeError:
                # Không chuyển tiếp raw text không có cấu trúc.
                await websocket.send_json({
                    "type": "ERROR",
                    "message": "Invalid JSON message",
                })

    except WebSocketDisconnect:
        pass

    finally:
        manager.disconnect(websocket)

        await manager.broadcast_json({
            "type": "DEVICE_DISCONNECTED_WAN",
            "device_hwid": device_hwid,
        })


@router.post("/relay/command")
async def send_relay_command(payload: RelayCommandRequest):
    target_hwid = payload.target_hwid.strip()
    action = payload.action.strip().upper()

    if action not in ALLOWED_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Action không được hỗ trợ: {action}"
        )

    message = {
        "type": action,
        "target_hwid": target_hwid,
        "sender": "parent_cloud",
        "data": payload.data,
        "timestamp": time.time(),
    }

    sent = await manager.send_to_device(
        target_hwid,
        message
    )

    if not sent:
        raise HTTPException(
            status_code=404,
            detail=f"Thiết bị {target_hwid} hiện không kết nối."
        )

    return {
        "status": "success",
        "target_hwid": target_hwid,
        "action": action,
        "message": f"Đã gửi lệnh {action} đến {target_hwid}",
    }