"""
微信个人号通道 HTTP 客户端

封装 iLinkAI 协议的所有 HTTP API 调用：
- QR 码登录（get_bot_qrcode / get_qrcode_status）
- 消息长轮询（getupdates）
- 消息发送（sendmessage）
- 打字状态（getconfig / sendtyping）

所有请求使用 httpx.AsyncClient，复用连接池。
认证通过 Authorization: Bearer <bot_token> + AuthorizationType: ilink_bot_token 头。

参考：
- TypeScript SDK: /tmp/weixin-ref/package/src/api/api.ts
- iLinkAI 协议文档: https://ilinkai.weixin.qq.com
"""
import base64
import logging
import os
import struct
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "1.0.0"


def _random_wechat_uin() -> str:
    """X-WECHAT-UIN header: random uint32 → decimal string → base64."""
    uint32 = struct.unpack(">I", os.urandom(4))[0]
    return base64.b64encode(str(uint32).encode()).decode()


def _build_base_info() -> dict[str, str]:
    return {"channel_version": CHANNEL_VERSION}


def _generate_client_id() -> str:
    return f"asdispatch-wx-{uuid.uuid4().hex[:12]}"


class WeixinClient:
    """iLinkAI HTTP API 客户端，每个微信 Bot 账号一个实例。"""

    def __init__(self, bot_token: str = "") -> None:
        self.bot_token = bot_token
        self._uin = _random_wechat_uin()
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=httpx.Timeout(30.0),
        )

    async def close(self) -> None:
        """关闭底层 HTTP 客户端，释放连接池。"""
        await self._http.aclose()

    # ============== 内部方法 ==============

    def _auth_headers(self) -> dict[str, str]:
        """构建带认证的请求头，用于需要 bot_token 的 POST 请求。"""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": self._uin,
        }
        if self.bot_token:
            headers["Authorization"] = f"Bearer {self.bot_token}"
        return headers

    # ============== QR 码登录 (US1) ==============

    async def get_qrcode(self) -> dict[str, Any]:
        """
        获取登录二维码。

        GET /ilink/bot/get_bot_qrcode?bot_type=3
        无需 bot_token。

        Returns:
            {"qrcode": "...", "qrcode_img_content": "https://..."}
        """
        resp = await self._http.get(
            "/ilink/bot/get_bot_qrcode",
            params={"bot_type": "3"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("[weixin] 获取二维码成功")
        return data

    async def get_qrcode_status(self, qrcode: str) -> dict[str, Any]:
        """
        轮询二维码扫码状态。

        GET /ilink/bot/get_qrcode_status?qrcode=xxx
        需要 iLink-App-ClientVersion: 1 头。

        Returns:
            {"status": "wait|scaned|confirmed|expired",
             "bot_token": "...", "ilink_bot_id": "...",
             "ilink_user_id": "...", "baseurl": "..."}
        """
        resp = await self._http.get(
            "/ilink/bot/get_qrcode_status",
            params={"qrcode": qrcode},
            headers={"iLink-App-ClientVersion": "1"},
            timeout=35.0,
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "unknown")
        logger.debug(f"[weixin] QR 状态: {status}")
        return data

    # ============== 消息收发 (US2) ==============

    async def get_updates(self, get_updates_buf: str = "") -> dict[str, Any]:
        """
        长轮询获取新消息。

        POST /ilink/bot/getupdates
        服务端 35s 超时，客户端 40s 超时（+5s 缓冲）。

        Returns:
            {"ret": 0, "errcode": 0, "msgs": [...],
             "get_updates_buf": "...", "longpolling_timeout_ms": ...}
        """
        resp = await self._http.post(
            "/ilink/bot/getupdates",
            headers=self._auth_headers(),
            json={
                "get_updates_buf": get_updates_buf,
                "base_info": _build_base_info(),
            },
            timeout=40.0,
        )
        resp.raise_for_status()
        return resp.json()

    async def send_message(
        self,
        to_user_id: str,
        context_token: str,
        text: str,
    ) -> dict[str, Any]:
        """
        发送文本消息给用户。

        POST /ilink/bot/sendmessage

        Args:
            to_user_id: 目标用户 ID
            context_token: 会话 context_token（必须回传）
            text: 消息文本

        Returns:
            API 响应 dict
        """
        client_id = _generate_client_id()
        body: dict[str, Any] = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user_id,
                "client_id": client_id,
                "message_type": 2,  # BOT
                "message_state": 2,  # FINISH
                "item_list": [{"type": 1, "text_item": {"text": text}}],
                "context_token": context_token,
            },
            "base_info": _build_base_info(),
        }
        resp = await self._http.post(
            "/ilink/bot/sendmessage",
            headers=self._auth_headers(),
            json=body,
            timeout=30.0,
        )
        resp.raise_for_status()
        logger.info(
            f"[weixin] 消息已发送: to={to_user_id}, text={text[:50]}..."
            if len(text) > 50 else f"[weixin] 消息已发送: to={to_user_id}, text={text}"
        )
        return resp.json()

    # ============== 打字指示器 (US6) ==============

    async def get_config(
        self, ilink_user_id: str, context_token: str = "",
    ) -> dict[str, Any]:
        """
        获取 Bot 配置，包含 typing_ticket。

        POST /ilink/bot/getconfig

        Returns:
            {"ret": 0, "typing_ticket": "..."}
        """
        resp = await self._http.post(
            "/ilink/bot/getconfig",
            headers=self._auth_headers(),
            json={
                "ilink_user_id": ilink_user_id,
                "context_token": context_token,
                "base_info": _build_base_info(),
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()

    async def send_typing(
        self,
        ilink_user_id: str,
        typing_ticket: str,
        status: int = 1,
    ) -> dict[str, Any]:
        """
        发送打字状态指示器。

        POST /ilink/bot/sendtyping

        Args:
            ilink_user_id: 目标用户 ID
            typing_ticket: 从 getconfig 获取的 ticket
            status: 1=正在输入, 2=取消输入
        """
        resp = await self._http.post(
            "/ilink/bot/sendtyping",
            headers=self._auth_headers(),
            json={
                "ilink_user_id": ilink_user_id,
                "typing_ticket": typing_ticket,
                "status": status,
                "base_info": _build_base_info(),
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        action = "typing" if status == 1 else "cancel"
        logger.debug(f"[weixin] 打字状态已发送: user={ilink_user_id}, action={action}")
        return resp.json()
