"""
QQ Bot 客户端

基于 QQ 开放平台 Bot API 实现：
- AccessToken 鉴权（AppID + AppSecret）
- WebSocket Gateway 长连接（接收消息 + 心跳）
- 消息发送（C2C 私聊、群聊、频道）

参考：
- QQ 官方文档: https://bot.q.qq.com/wiki/develop/api-v2/
- @sliverp/qqbot OpenClaw 插件: https://github.com/sliverp/qqbot
"""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Awaitable, Optional

import httpx

logger = logging.getLogger(__name__)

# ============== 常量 ==============

API_BASE = "https://api.sgroup.qq.com"
TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"

# WebSocket OpCodes
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Intents
INTENT_GUILDS = 1 << 0
INTENT_GUILD_MEMBERS = 1 << 1
INTENT_DIRECT_MESSAGE = 1 << 12
INTENT_GROUP_AND_C2C = 1 << 25
INTENT_PUBLIC_GUILD_MESSAGES = 1 << 30

DEFAULT_INTENTS = INTENT_PUBLIC_GUILD_MESSAGES | INTENT_GROUP_AND_C2C

RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
MAX_RECONNECT_ATTEMPTS = 50


# ============== Token 管理 ==============


class TokenManager:
    """QQ Bot AccessToken 管理器，带缓存和并发安全"""

    def __init__(self, app_id: str, client_secret: str):
        self.app_id = app_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._expires_at: float = 0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 300:
            return self._token

        async with self._lock:
            if self._token and time.time() < self._expires_at - 300:
                return self._token
            return await self._refresh_token()

    async def _refresh_token(self) -> str:
        logger.info(f"[qqbot] Refreshing access token for appId={self.app_id}")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                TOKEN_URL,
                json={"appId": self.app_id, "clientSecret": self.client_secret},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data.get("access_token"):
            raise RuntimeError(f"Failed to get access_token: {data}")

        self._token = data["access_token"]
        expires_in = int(data.get("expires_in", 7200))
        self._expires_at = time.time() + expires_in
        logger.info(f"[qqbot] Token refreshed, expires in {expires_in}s")
        return self._token

    def clear(self):
        self._token = None
        self._expires_at = 0


# ============== API 请求 ==============


async def api_request(
    token: str,
    method: str,
    path: str,
    body: Optional[dict] = None,
    timeout: float = 30.0,
) -> dict:
    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method, url, headers=headers,
            json=body if body else None,
        )

    data = resp.json()
    if not resp.is_success:
        error_msg = data.get("message", json.dumps(data))
        raise RuntimeError(f"QQ Bot API error [{path}] {resp.status_code}: {error_msg}")
    return data


# ============== 消息发送 ==============


def _build_msg_body(content: str, msg_id: Optional[str] = None, msg_type: int = 0) -> dict:
    body: dict[str, Any] = {
        "content": content,
        "msg_type": msg_type,
    }
    if msg_id:
        body["msg_id"] = msg_id
    return body


async def send_c2c_message(
    token: str, openid: str, content: str, msg_id: Optional[str] = None,
) -> dict:
    body = _build_msg_body(content, msg_id)
    return await api_request(token, "POST", f"/v2/users/{openid}/messages", body)


async def send_group_message(
    token: str, group_openid: str, content: str, msg_id: Optional[str] = None,
) -> dict:
    body = _build_msg_body(content, msg_id)
    return await api_request(token, "POST", f"/v2/groups/{group_openid}/messages", body)


async def send_channel_message(
    token: str, channel_id: str, content: str, msg_id: Optional[str] = None,
) -> dict:
    body = _build_msg_body(content, msg_id)
    return await api_request(token, "POST", f"/channels/{channel_id}/messages", body)


# ============== WebSocket Gateway ==============


class QQBotGateway:
    """
    QQ Bot WebSocket Gateway 客户端

    负责：
    - 建立 WebSocket 连接
    - 鉴权（Identify）和心跳维护
    - 接收消息并回调
    - 自动重连和 Session Resume
    """

    def __init__(
        self,
        token_manager: TokenManager,
        on_message: Callable[[str, dict], Awaitable[None]],
        intents: int = DEFAULT_INTENTS,
    ):
        self.token_manager = token_manager
        self.on_message = on_message
        self.intents = intents

        self._ws = None
        self._session_id: Optional[str] = None
        self._last_seq: Optional[int] = None
        self._heartbeat_interval: float = 45.0
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
        self._reconnect_attempts = 0

    async def start(self):
        """启动 Gateway 连接（持续运行，自动重连）"""
        self._running = True
        self._reconnect_attempts = 0

        while self._running and self._reconnect_attempts < MAX_RECONNECT_ATTEMPTS:
            try:
                await self._connect()
            except asyncio.CancelledError:
                logger.info("[qqbot-gw] Gateway cancelled")
                break
            except Exception as e:
                logger.error(f"[qqbot-gw] Connection error: {e}")

            if not self._running:
                break

            delay = RECONNECT_DELAYS[
                min(self._reconnect_attempts, len(RECONNECT_DELAYS) - 1)
            ]
            self._reconnect_attempts += 1
            logger.info(
                f"[qqbot-gw] Reconnecting in {delay}s "
                f"(attempt {self._reconnect_attempts}/{MAX_RECONNECT_ATTEMPTS})"
            )
            await asyncio.sleep(delay)

        logger.info("[qqbot-gw] Gateway stopped")

    async def stop(self):
        """停止 Gateway"""
        self._running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        if self._ws:
            await self._ws.aclose()

    async def _connect(self):
        """建立一次 WebSocket 连接"""
        import websockets

        token = await self.token_manager.get_token()
        gw_url = await self._get_gateway_url(token)
        logger.info(f"[qqbot-gw] Connecting to {gw_url}")

        async with websockets.connect(gw_url) as ws:
            self._ws = ws

            async for raw_msg in ws:
                try:
                    payload = json.loads(raw_msg)
                except json.JSONDecodeError:
                    logger.warning(f"[qqbot-gw] Invalid JSON: {raw_msg[:200]}")
                    continue

                await self._handle_payload(ws, payload)

    async def _get_gateway_url(self, token: str) -> str:
        data = await api_request(token, "GET", "/gateway")
        return data["url"]

    async def _handle_payload(self, ws, payload: dict):
        op = payload.get("op")
        d = payload.get("d")
        s = payload.get("s")
        t = payload.get("t")

        if s is not None:
            self._last_seq = s

        if op == OP_HELLO:
            self._heartbeat_interval = d.get("heartbeat_interval", 45000) / 1000.0
            logger.info(
                f"[qqbot-gw] Hello received, heartbeat interval: {self._heartbeat_interval}s"
            )

            if self._session_id and self._last_seq is not None:
                await self._send_resume(ws)
            else:
                await self._send_identify(ws)

            self._start_heartbeat(ws)

        elif op == OP_DISPATCH:
            if t == "READY":
                self._session_id = d.get("session_id")
                self._reconnect_attempts = 0
                logger.info(f"[qqbot-gw] Ready, session_id={self._session_id}")
            elif t == "RESUMED":
                self._reconnect_attempts = 0
                logger.info("[qqbot-gw] Session resumed")
            else:
                await self.on_message(t, d)

        elif op == OP_HEARTBEAT_ACK:
            pass

        elif op == OP_RECONNECT:
            logger.info("[qqbot-gw] Server requested reconnect")
            await ws.close()

        elif op == OP_INVALID_SESSION:
            resumable = d if isinstance(d, bool) else False
            logger.warning(f"[qqbot-gw] Invalid session, resumable={resumable}")
            if not resumable:
                self._session_id = None
                self._last_seq = None
            await asyncio.sleep(2)
            await ws.close()

        elif op == OP_HEARTBEAT:
            await self._send_heartbeat(ws)

    async def _send_identify(self, ws):
        token = await self.token_manager.get_token()
        payload = {
            "op": OP_IDENTIFY,
            "d": {
                "token": f"QQBot {token}",
                "intents": self.intents,
            },
        }
        await ws.send(json.dumps(payload))
        logger.info(f"[qqbot-gw] Identify sent, intents={self.intents}")

    async def _send_resume(self, ws):
        token = await self.token_manager.get_token()
        payload = {
            "op": OP_RESUME,
            "d": {
                "token": f"QQBot {token}",
                "session_id": self._session_id,
                "seq": self._last_seq,
            },
        }
        await ws.send(json.dumps(payload))
        logger.info(f"[qqbot-gw] Resume sent, session_id={self._session_id}, seq={self._last_seq}")

    async def _send_heartbeat(self, ws):
        payload = {"op": OP_HEARTBEAT, "d": self._last_seq}
        try:
            await ws.send(json.dumps(payload))
        except Exception as e:
            logger.error(f"[qqbot-gw] Heartbeat send error: {e}")

    def _start_heartbeat(self, ws):
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))

    async def _heartbeat_loop(self, ws):
        try:
            while self._running:
                await asyncio.sleep(self._heartbeat_interval)
                await self._send_heartbeat(ws)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[qqbot-gw] Heartbeat loop error: {e}")


# ============== QQ Bot 客户端（高层封装） ==============


class QQBotClient:
    """
    QQ Bot 完整客户端

    封装 TokenManager + Gateway + 消息发送，
    提供类似 DiscordBotClient 的使用体验。
    """

    def __init__(
        self,
        app_id: str,
        client_secret: str,
        on_message: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.app_id = app_id
        self.client_secret = client_secret
        self._on_message = on_message

        self.token_manager = TokenManager(app_id, client_secret)
        self.gateway = QQBotGateway(
            token_manager=self.token_manager,
            on_message=self._dispatch_event,
        )
        self._gateway_task: Optional[asyncio.Task] = None

    async def start(self):
        """启动 Bot（后台运行 Gateway）"""
        logger.info(f"[qqbot] Starting QQ Bot: appId={self.app_id}")
        self._gateway_task = asyncio.create_task(self.gateway.start())

    async def close(self):
        """关闭 Bot"""
        logger.info(f"[qqbot] Stopping QQ Bot: appId={self.app_id}")
        await self.gateway.stop()
        if self._gateway_task and not self._gateway_task.done():
            self._gateway_task.cancel()
            try:
                await self._gateway_task
            except asyncio.CancelledError:
                pass

    async def send_text(
        self,
        target_type: str,
        target_id: str,
        content: str,
        msg_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        发送文本消息

        Args:
            target_type: "c2c" / "group" / "channel"
            target_id: openid / group_openid / channel_id
            content: 消息内容
            msg_id: 回复的消息 ID（可选）
        """
        token = await self.token_manager.get_token()
        try:
            if target_type == "c2c":
                return await send_c2c_message(token, target_id, content, msg_id)
            elif target_type == "group":
                return await send_group_message(token, target_id, content, msg_id)
            elif target_type == "channel":
                return await send_channel_message(token, target_id, content, msg_id)
            else:
                logger.error(f"[qqbot] Unknown target_type: {target_type}")
                return None
        except Exception as e:
            # Token 过期重试一次
            if "401" in str(e) or "token" in str(e).lower():
                logger.info("[qqbot] Token may be expired, refreshing...")
                self.token_manager.clear()
                token = await self.token_manager.get_token()
                if target_type == "c2c":
                    return await send_c2c_message(token, target_id, content, msg_id)
                elif target_type == "group":
                    return await send_group_message(token, target_id, content, msg_id)
                elif target_type == "channel":
                    return await send_channel_message(token, target_id, content, msg_id)
            raise

    async def _dispatch_event(self, event_type: str, data: dict):
        """分发 WebSocket 事件到消息回调"""
        message_events = {
            "C2C_MESSAGE_CREATE",
            "GROUP_AT_MESSAGE_CREATE",
            "AT_MESSAGE_CREATE",
            "DIRECT_MESSAGE_CREATE",
        }

        if event_type in message_events and self._on_message:
            parsed = self._parse_message_event(event_type, data)
            if parsed:
                await self._on_message(parsed)

    def _parse_message_event(self, event_type: str, data: dict) -> Optional[dict]:
        """
        将 QQ Bot WebSocket 事件解析为统一格式

        返回格式:
        {
            "type": "c2c" | "group" | "channel" | "dm",
            "sender_id": str,
            "sender_name": str,
            "content": str,
            "message_id": str,
            "timestamp": str,
            "group_openid": str | None,
            "channel_id": str | None,
            "guild_id": str | None,
            "attachments": [{"content_type": str, "url": str}],
        }
        """
        if event_type == "C2C_MESSAGE_CREATE":
            author = data.get("author", {})
            return {
                "type": "c2c",
                "sender_id": author.get("user_openid", author.get("id", "")),
                "sender_name": author.get("user_openid", "")[:8],
                "content": (data.get("content") or "").strip(),
                "message_id": data.get("id", ""),
                "timestamp": data.get("timestamp", ""),
                "group_openid": None,
                "channel_id": None,
                "guild_id": None,
                "attachments": self._extract_attachments(data),
            }

        elif event_type == "GROUP_AT_MESSAGE_CREATE":
            author = data.get("author", {})
            return {
                "type": "group",
                "sender_id": author.get("member_openid", author.get("id", "")),
                "sender_name": author.get("member_openid", "")[:8],
                "content": (data.get("content") or "").strip(),
                "message_id": data.get("id", ""),
                "timestamp": data.get("timestamp", ""),
                "group_openid": data.get("group_openid", ""),
                "channel_id": None,
                "guild_id": None,
                "attachments": self._extract_attachments(data),
            }

        elif event_type in ("AT_MESSAGE_CREATE", "DIRECT_MESSAGE_CREATE"):
            author = data.get("author", {})
            msg_type = "dm" if event_type == "DIRECT_MESSAGE_CREATE" else "channel"
            return {
                "type": msg_type,
                "sender_id": author.get("id", ""),
                "sender_name": author.get("username", ""),
                "content": (data.get("content") or "").strip(),
                "message_id": data.get("id", ""),
                "timestamp": data.get("timestamp", ""),
                "group_openid": None,
                "channel_id": data.get("channel_id"),
                "guild_id": data.get("guild_id"),
                "attachments": self._extract_attachments(data),
            }

        return None

    def _extract_attachments(self, data: dict) -> list[dict]:
        result = []
        for att in data.get("attachments", []):
            url = att.get("url", "")
            if url.startswith("//"):
                url = f"https:{url}"
            result.append({
                "content_type": att.get("content_type", ""),
                "url": url,
                "filename": att.get("filename"),
            })
        return result
