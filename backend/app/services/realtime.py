import json
from collections import defaultdict
from typing import Optional

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # Một thiết bị có thể có nhiều kết nối.
        # Ví dụ: Agent reconnect trong khi kết nối cũ chưa đóng.
        self.active_connections: dict[WebSocket, str] = {}

    async def connect(self, device_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = device_id

    def disconnect(self, websocket: WebSocket):
        self.active_connections.pop(websocket, None)

    def get_connections(self, device_id: str) -> list[WebSocket]:
        return [
            ws
            for ws, connected_id in self.active_connections.items()
            if connected_id == device_id
        ]

    async def send_to_device(self, device_id: str, data: dict) -> bool:
        """Gửi message đến các kết nối thuộc đúng device_id."""
        connections = self.get_connections(device_id)

        if not connections:
            return False

        message = json.dumps(data, ensure_ascii=False)
        failed = []

        for websocket in connections:
            try:
                await websocket.send_text(message)
            except Exception:
                failed.append(websocket)

        for websocket in failed:
            self.disconnect(websocket)

        return len(connections) > len(failed)

    async def broadcast_text(
        self,
        message: str,
        sender_ws: Optional[WebSocket] = None
    ):
        failed = []

        for websocket in list(self.active_connections):
            if websocket == sender_ws:
                continue

            try:
                await websocket.send_text(message)
            except Exception:
                failed.append(websocket)

        for websocket in failed:
            self.disconnect(websocket)

    async def broadcast_json(
        self,
        data: dict,
        sender_ws: Optional[WebSocket] = None
    ):
        await self.broadcast_text(
            json.dumps(data, ensure_ascii=False),
            sender_ws=sender_ws
        )


manager = ConnectionManager()