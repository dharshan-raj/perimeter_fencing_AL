# ============================================================
# FILE: shared/services/websocket_manager.py
# PURPOSE: Manages active FastAPI WebSocket connections and broadcasts real-time JSON alerts
# USE CASE: Shared Infrastructure (Real-Time Alerts)
# DEBUG TIPS:
#   - If dashboard stops receiving live events: check /ws/alerts connection in browser DevTools
# ============================================================

from fastapi import WebSocket
class ConnectionManager:
    def __init__(self): self.clients=set()
    async def connect(self,ws:WebSocket): await ws.accept(); self.clients.add(ws)
    def disconnect(self,ws): self.clients.discard(ws)
    async def broadcast(self,payload):
        dead=[]
        for ws in list(self.clients):
            try: await ws.send_json(payload)
            except Exception: dead.append(ws)
        for ws in dead:self.disconnect(ws)
manager=ConnectionManager()
