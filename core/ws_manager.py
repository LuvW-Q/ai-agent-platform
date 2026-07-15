"""
WebSocket连接管理器
管理用户在线连接，支持多端同时在线
"""
import json
from datetime import datetime, timezone
from fastapi import WebSocket
from typing import Dict, List

class ConnectionManager:
    """管理 user_id → [WebSocket] 的映射，支持同一用户多端在线"""

    def __init__(self):
        self._connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, ws: WebSocket):
        await ws.accept()
        if user_id not in self._connections:
            self._connections[user_id] = []
        self._connections[user_id].append(ws)

    def disconnect(self, user_id: int, ws: WebSocket):
        if user_id in self._connections:
            if ws in self._connections[user_id]:
                self._connections[user_id].remove(ws)
            if not self._connections[user_id]:
                del self._connections[user_id]

    def is_online(self, user_id: int) -> bool:
        return user_id in self._connections and len(self._connections[user_id]) > 0

    async def send_to_user(self, user_id: int, data: dict):
        """向指定用户的所有在线设备推送消息"""
        if user_id in self._connections:
            msg = json.dumps(data, ensure_ascii=False, default=str)
            dead = []
            for ws in self._connections[user_id]:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.disconnect(user_id, ws)

    async def send_to_group(self, group_id: int, data: dict, exclude_user: int = None):
        """向群组所有在线成员推送消息（需要传入成员ID列表）"""
        # 由调用者提供成员列表，这里只做转发
        member_ids = data.pop("_group_member_ids", [])
        for uid in member_ids:
            if exclude_user and uid == exclude_user:
                continue
            await self.send_to_user(uid, data)

    async def force_logout(self, user_id: int, reason: str = "账号在其他设备登录"):
        """强制用户所有设备下线"""
        await self.send_to_user(user_id, {
            "msg_type": "force_logout",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "body": {"reason": reason}
        })
        # 关闭所有连接
        if user_id in self._connections:
            for ws in self._connections[user_id]:
                try:
                    await ws.close()
                except Exception:
                    pass
            del self._connections[user_id]

    def get_online_users(self) -> list[int]:
        return list(self._connections.keys())


# 全局单例
ws_manager = ConnectionManager()
