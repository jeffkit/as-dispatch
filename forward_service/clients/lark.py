"""
飞书 (Lark) Bot API 客户端

封装飞书开放平台 API 的常用操作:
- Token 管理 (tenant_access_token)
- 发送消息 (文本、富文本、卡片)
- Webhook 处理
- 事件解密
"""
import logging
import json
import time
import base64
import hashlib
from typing import Optional, Dict, Any
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

logger = logging.getLogger(__name__)


class LarkClient:
    """飞书/Lark Bot API 客户端"""
    
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        encrypt_key: Optional[str] = None,
        verification_token: Optional[str] = None
    ):
        """
        初始化客户端
        
        Args:
            app_id: 应用 ID
            app_secret: 应用 Secret
            encrypt_key: 加密密钥 (用于事件解密，可选)
            verification_token: 验证 Token (用于 URL 验证，可选)
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.encrypt_key = encrypt_key
        self.verification_token = verification_token
        self.base_url = "https://open.feishu.cn/open-apis"
        
        # Token 缓存
        self._access_token = None
        self._token_expire_time = 0
    
    # ============== Token 管理 ==============
    
    async def get_tenant_access_token(self, force_refresh: bool = False) -> str:
        """
        获取 tenant_access_token
        
        Args:
            force_refresh: 是否强制刷新 token
        
        Returns:
            access_token
        """
        import httpx
        
        # 检查缓存
        current_time = int(time.time())
        if not force_refresh and self._access_token and current_time < self._token_expire_time:
            return self._access_token
        
        # 请求新 token
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") != 0:
                    raise Exception(f"获取 token 失败: {data.get('msg')}")
                
                self._access_token = data["tenant_access_token"]
                # Token 有效期 2 小时，提前 5 分钟刷新
                self._token_expire_time = current_time + data.get("expire", 7200) - 300
                
                logger.info(f"获取 Lark tenant_access_token 成功，有效期至: {self._token_expire_time}")
                return self._access_token
        
        except Exception as e:
            logger.error(f"获取 Lark token 失败: {e}", exc_info=True)
            raise
    
    # ============== 消息发送 ==============
    
    async def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: str | dict,
        receive_id_type: str = "chat_id"
    ) -> Dict[str, Any]:
        """
        发送消息
        
        Args:
            receive_id: 接收者 ID (chat_id, user_id, email 等)
            msg_type: 消息类型 (text, post, interactive, image 等)
            content: 消息内容 (字符串或字典)
            receive_id_type: 接收者 ID 类型 (chat_id, user_id, email, open_id)
        
        Returns:
            发送结果
        """
        import httpx
        
        token = await self.get_tenant_access_token()
        url = f"{self.base_url}/im/v1/messages"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # 构建消息内容
        if isinstance(content, str):
            content_str = content
        else:
            content_str = json.dumps(content)
        
        payload = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content_str
        }
        
        params = {
            "receive_id_type": receive_id_type
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload, params=params)
                response.raise_for_status()
                data = response.json()
                
                if data.get("code") != 0:
                    raise Exception(f"发送消息失败: {data.get('msg')}")
                
                return data["data"]
        
        except Exception as e:
            logger.error(f"发送 Lark 消息失败: {e}", exc_info=True)
            raise
    
    async def send_text(
        self,
        receive_id: str,
        text: str,
        receive_id_type: str = "chat_id"
    ) -> Dict[str, Any]:
        """
        发送文本消息
        
        Args:
            receive_id: 接收者 ID
            text: 文本内容
            receive_id_type: 接收者 ID 类型
        
        Returns:
            发送结果
        """
        content = {"text": text}
        return await self.send_message(receive_id, "text", content, receive_id_type)
    
    async def send_rich_text(
        self,
        receive_id: str,
        title: str,
        content: list,
        receive_id_type: str = "chat_id"
    ) -> Dict[str, Any]:
        """
        发送富文本消息
        
        Args:
            receive_id: 接收者 ID
            title: 标题
            content: 内容数组 (支持文本、链接、@等)
            receive_id_type: 接收者 ID 类型
        
        Returns:
            发送结果
        """
        post_content = {
            "zh_cn": {
                "title": title,
                "content": content
            }
        }
        return await self.send_message(receive_id, "post", {"post": post_content}, receive_id_type)
    
    async def send_card(
        self,
        receive_id: str,
        card: dict,
        receive_id_type: str = "chat_id"
    ) -> Dict[str, Any]:
        """
        发送交互式卡片
        
        Args:
            receive_id: 接收者 ID
            card: 卡片配置 (JSON)
            receive_id_type: 接收者 ID 类型
        
        Returns:
            发送结果
        """
        return await self.send_message(receive_id, "interactive", card, receive_id_type)
    
    # ============== Webhook 处理 ==============
    
    def verify_url(self, challenge: str, token: str) -> Optional[Dict]:
        """
        验证 Webhook URL
        
        Args:
            challenge: 挑战码
            token: 验证 token
        
        Returns:
            验证响应 (如果验证通过)
        """
        if self.verification_token and token != self.verification_token:
            logger.warning(f"Verification token 不匹配")
            return None
        
        return {"challenge": challenge}
    
    def decrypt_event(self, encrypted: str) -> Dict[str, Any]:
        """
        解密事件数据
        
        Args:
            encrypted: 加密的事件数据 (Base64)
        
        Returns:
            解密后的事件对象
        """
        if not self.encrypt_key:
            raise ValueError("未配置 encrypt_key，无法解密事件")
        
        try:
            # Base64 解码
            encrypted_bytes = base64.b64decode(encrypted)
            
            # AES-256-CBC 解密
            key = self.encrypt_key.encode("utf-8")
            cipher = AES.new(key, AES.MODE_CBC, key[:16])
            decrypted = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)
            
            # 解析 JSON
            event = json.loads(decrypted.decode("utf-8"))
            return event
        
        except Exception as e:
            logger.error(f"解密事件失败: {e}", exc_info=True)
            raise
    
    def parse_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析飞书事件对象
        
        Args:
            event: 事件对象
        
        Returns:
            解析后的统一格式:
            {
                "event_id": str,
                "event_type": str,
                "chat_id": str,
                "user_id": str,
                "open_id": str,
                "message_id": str,
                "text": str,
                "timestamp": int,
                "raw": dict
            }
        """
        header = event.get("header", {})
        event_data = event.get("event", {})
        
        # 提取消息内容
        message = event_data.get("message", {})
        sender = event_data.get("sender", {})
        
        # 解析消息文本 (可能是 JSON 格式)
        content = message.get("content")
        text = None
        if content:
            try:
                content_obj = json.loads(content)
                text = content_obj.get("text")
            except:
                text = content
        
        return {
            "event_id": header.get("event_id"),
            "event_type": header.get("event_type"),
            "chat_id": message.get("chat_id"),
            "user_id": sender.get("sender_id", {}).get("user_id"),
            "open_id": sender.get("sender_id", {}).get("open_id"),
            "message_id": message.get("message_id"),
            "message_type": message.get("message_type"),
            "text": text,
            "timestamp": int(header.get("create_time", 0)) // 1000,  # 毫秒转秒
            "raw": event
        }
    
    # ============== 卡片构建 ==============
    
    def build_text_card(
        self,
        title: str,
        content: str,
        note: Optional[str] = None
    ) -> dict:
        """
        构建简单文本卡片
        
        Args:
            title: 标题
            content: 内容
            note: 备注 (可选)
        
        Returns:
            卡片配置
        """
        card = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "plain_text",
                        "content": content
                    }
                }
            ]
        }
        
        if note:
            card["elements"].append({
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": note
                    }
                ]
            })
        
        return card
    
    # ============== 辅助方法 ==============
    
    def format_agent_response(self, response: str, use_card: bool = False) -> tuple[str, dict]:
        """
        格式化 Agent 响应为飞书消息
        
        Args:
            response: Agent 响应文本
            use_card: 是否使用卡片格式
        
        Returns:
            (msg_type, content)
        """
        # 如果响应太长，使用卡片格式
        if len(response) > 2000 or use_card:
            card = self.build_text_card(
                title="Agent 回复",
                content=response[:4000],  # 卡片内容限制
                note="由 AI Agent 生成"
            )
            return "interactive", card
        else:
            return "text", {"text": response}
