"""
Tracks active WebSocket connections per team, so we know who to push
updates to when a checkpoint lands. Kept in memory - fine for a small
team dashboard; would need Redis pub/sub if this ever ran across multiple
backend server instances, but that's not a concern at this scale.
"""

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # team_id -> list of open WebSocket connections currently viewing that team's dashboard
        self.active_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, team_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(team_id, []).append(websocket)

    def disconnect(self, team_id: int, websocket: WebSocket):
        connections = self.active_connections.get(team_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections and team_id in self.active_connections:
            del self.active_connections[team_id]

    async def broadcast_to_team(self, team_id: int, message: dict):
        """Sends a message to every dashboard currently open for this team.
        Silently drops connections that error out (they've likely disconnected
        without us catching it yet) - those get cleaned up on their next
        disconnect event."""
        dead_connections = []
        for connection in self.active_connections.get(team_id, []):
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        for dead in dead_connections:
            self.disconnect(team_id, dead)


manager = ConnectionManager()