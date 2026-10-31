import json
from fastapi import WebSocket


class ConnectionManager:

    def __init__(self):
        self.active_connections: dict[WebSocket, str] = {}

    async def connect(
        self,
        device_id: str,
        websocket: WebSocket
    ):
        await websocket.accept()
        self.active_connections[websocket] = device_id

    def disconnect(self, websocket: WebSocket):
        self.active_connections.pop(websocket, None)

    async def broadcast_text(
        self,
        message: str,
        sender_ws: WebSocket = None
    ):
        dead_connections = []

        for websocket in list(self.active_connections):
            if websocket == sender_ws:
                continue

            try:
                await websocket.send_text(message)
            except Exception:
                dead_connections.append(websocket)

        for websocket in dead_connections:
            self.disconnect(websocket)

    async def broadcast_json(
        self,
        data: dict,
        sender_ws: WebSocket = None
    ):
        message = json.dumps(data)

        await self.broadcast_text(
            message,
            sender_ws=sender_ws
        )


manager = ConnectionManager()