import asyncio
import websockets

URI = "ws://127.0.0.1:8000/ws/agent/device_001"

async def listen_to_server():
    # Sử dụng cú pháp chuẩn với phiên bản websockets mới nhất
    async with websockets.connect(URI) as websocket:
        print("Đã kết nối WebSocket tới Backend thành công!")
        
        # Gửi thông điệp kết nối ban đầu
        await websocket.send("Hello from Client Agent (Online)")

        while True:
            # Lắng nghe thông điệp từ server
            response = await websocket.recv()
            print(f"[Lệnh từ Server]: {response}")

if __name__ == "__main__":
    asyncio.run(listen_to_server())