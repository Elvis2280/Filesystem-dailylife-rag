import asyncio
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect


HEARTBEAT_INTERVAL = 30


class ConnectionManager:
    """Manages active WebSocket connections and message broadcasting.

    Maintains a dictionary of active connections keyed by file_id,
    enabling targeted status updates during async file processing.
    """

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.current_steps: dict[str, str] = {}

    async def connect(self, file_id: str, websocket: WebSocket):
        """Accept a new WebSocket connection and register it."""
        await websocket.accept()
        self.active_connections[file_id] = websocket
        self.current_steps[file_id] = "0/4"

    def disconnect(self, file_id: str):
        """Remove a WebSocket connection by file_id."""
        self.active_connections.pop(file_id, None)
        self.current_steps.pop(file_id, None)

    def update_step(self, file_id: str, step: str):
        """Update the current pipeline step for a file's heartbeat."""
        if file_id in self.active_connections:
            self.current_steps[file_id] = step

    def is_connected(self, file_id: str) -> bool:
        """Return True if a client is currently connected for file_id."""
        return file_id in self.active_connections

    async def heartbeat(self, file_id: str):
        """Send periodic ping messages to keep the connection alive."""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            if file_id not in self.active_connections:
                break
            try:
                await self.active_connections[file_id].send_json(
                    {
                        "status": "PING",
                        "step": self.current_steps.get(file_id, "0/4"),
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            except WebSocketDisconnect:
                break

    async def send_message(self, file_id: str, message: dict):
        """Send a JSON message to a connected client by file_id.

        Silently drops messages if the client has disconnected, so
        callers don't need to handle WebSocketDisconnect on every send.
        """
        if file_id not in self.active_connections:
            return
        try:
            await self.active_connections[file_id].send_json(message)
        except WebSocketDisconnect:
            self.disconnect(file_id)


manager = ConnectionManager()
