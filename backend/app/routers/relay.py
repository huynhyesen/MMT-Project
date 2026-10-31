
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.realtime import manager


router = APIRouter(tags=["Relay"])


@router.websocket("/ws/relay/{device_hwid}")
async def cloud_relay_endpoint(
    websocket: WebSocket,
    device_hwid: str
):
    """WebSocket Cloud Relay for remote device connections."""

    await manager.connect(device_hwid, websocket)

    try:
        await manager.broadcast_json({
            "type": "DEVICE_CONNECTED_WAN",
            "device_hwid": device_hwid,
            "message": (
                f"Thiết bị {device_hwid} "
                "đã kết nối từ xa qua Cloud Relay thành công!"
            )
        })

        while True:
            data = await websocket.receive_text()

            try:
                msg = json.loads(data)
                mtype = msg.get("type", "")

                if mtype == "PING":
                    await websocket.send_text(json.dumps({
                        "type": "PONG",
                        "timestamp": time.time()
                    }))
                    continue

                await manager.broadcast_json(
                    msg,
                    sender_ws=websocket
                )

            except (json.JSONDecodeError, AttributeError):
                await manager.broadcast_text(
                    data,
                    sender_ws=websocket
                )

    except WebSocketDisconnect:
        manager.disconnect(websocket)

        await manager.broadcast_json({
            "type": "DEVICE_DISCONNECTED_WAN",
            "device_hwid": device_hwid
        })


@router.post("/relay/command")
async def send_relay_command(payload: dict):
    """Send a remote command through Cloud Relay."""

    target_hwid = payload.get("target_hwid")
    action = payload.get("action", "MESSAGE")
    data = payload.get("data", {})

    msg = {
        "type": action,
        "target_hwid": target_hwid,
        "sender": "parent_cloud",
        "data": data,
        "timestamp": time.time()
    }

    await manager.broadcast_json(msg)

    return {
        "status": "success",
        "message": (
            f"Đã gửi lệnh {action} qua Cloud Relay tới "
            f"{target_hwid or 'tất cả thiết bị'}"
        )
    }
