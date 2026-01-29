# AS-Dispatch 多平台接入路线图

**创建日期**: 2026-01-29  
**负责人**: AI Assistant  
**目标**: 打造统一的多平台 IM 机器人消息转发服务

---

## 📋 执行摘要

AS-Dispatch 将扩展支持多个主流即时通讯平台，实现统一的消息转发和 Agent 集成架构。本路线图规划了 6 个平台的接入顺序、技术方案和实施计划。

### 当前状态 (Phase 0)

| 平台 | 状态 | 功能 |
|------|------|------|
| 企业微信 (普通机器人) | ✅ 生产 | 完整支持 |
| 企业微信 (智能机器人) | ✅ 开发 | XML 消息、流式响应 |
| Slack | ✅ 开发 | 基础集成 |
| Discord | ✅ 开发 | Bot 集成 |

### 目标平台 (Phase 1-3)

| 平台 | 优先级 | 预计工作量 | 计划阶段 |
|------|--------|-----------|---------|
| Telegram | 🔴 高 | 2周 | Phase 1 |
| 飞书 (Lark) | 🔴 高 | 2周 | Phase 1 |
| 钉钉 (DingTalk) | 🟡 中 | 1周 | Phase 2 |
| WhatsApp Business | 🟢 低 | 3周 | Phase 3 |
| Microsoft Teams | 🟢 低 | 3周 | Phase 3 |
| Line | 🟢 低 | 2周 | Phase 3 |

---

## 🎯 阶段规划

### Phase 1: 国际主流平台 (2-3周)

**目标**: 接入 Telegram 和飞书，扩大用户覆盖

#### 1.1 Telegram Bot (Week 1-2)

**优先级**: 🔴 高
**理由**: 
- 国际用户广泛使用
- API 设计优秀，文档完善
- 开发难度低

**技术方案**:

```python
# telegram.py - Telegram Bot 客户端

class TelegramClient:
    """Telegram Bot API 客户端"""
    
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
    
    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "Markdown"
    ) -> dict:
        """发送文本消息"""
        url = f"{self.base_url}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        # 实现 HTTP POST 请求
    
    async def handle_webhook(self, update: dict) -> str:
        """处理 webhook 更新"""
        # 解析 Update 对象
        # 转发消息到 Agent
        # 返回响应
```

**Webhook 配置**:
- URL: `https://hitl.woa.com/callback/telegram/{bot_key}`
- 方法: POST
- 格式: JSON (Update 对象)
- 验证: Secret token 头部

**支持的消息类型**:
- ✅ 文本消息
- ✅ Markdown 格式
- ✅ 内联按钮
- 🚧 图片/文件 (Phase 1.5)

**数据模型扩展**:
```python
# models.py
class Chatbot(Base):
    # 新增字段
    platform_config: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="平台特定配置 JSON"
    )
    # Telegram: {"bot_token": "xxx", "allowed_chat_ids": []}
```

**实施步骤**:
1. ✅ Week 1.1: 创建分支 `feature/telegram-integration`
2. ✅ Week 1.2: 实现 TelegramClient
3. ✅ Week 1.3: 实现 Webhook 路由
4. ✅ Week 1.4: 会话管理集成
5. ✅ Week 2.1: 测试和调试
6. ✅ Week 2.2: 文档编写
7. ✅ Week 2.3: 合并到 main

**技术要点**:
- Webhook vs Long Polling: 使用 Webhook (生产环境)
- SSL 要求: 必须 HTTPS (443/80/88/8443)
- IP 白名单: `149.154.160.0/20`, `91.108.4.0/22`
- 响应超时: 60 秒

#### 1.2 飞书 (Lark) (Week 3-4)

**优先级**: 🔴 高
**理由**:
- 国内企业广泛使用
- 功能丰富，支持卡片消息
- 与企微形成互补

**技术方案**:

```python
# lark.py - 飞书 Bot 客户端

class LarkClient:
    """飞书/Lark Bot 客户端"""
    
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = "https://open.feishu.cn/open-apis"
        self._access_token = None
    
    async def get_tenant_access_token(self) -> str:
        """获取 tenant_access_token"""
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        data = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        # 实现 token 获取和缓存
    
    async def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: str
    ) -> dict:
        """发送消息"""
        url = f"{self.base_url}/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {await self.get_tenant_access_token()}",
            "Content-Type": "application/json"
        }
        data = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content
        }
        # 实现 HTTP POST 请求
    
    async def handle_webhook(self, event: dict) -> str:
        """处理事件回调"""
        # 解析 Event 对象
        # 处理不同事件类型
        # 转发消息到 Agent
```

**Webhook 配置**:
- URL: `https://hitl.woa.com/callback/lark/{bot_key}`
- 方法: POST
- 格式: JSON (Event 对象)
- 验证: Encrypt Key 或 Verification Token

**支持的消息类型**:
- ✅ 文本消息
- ✅ 富文本消息
- ✅ 交互式卡片
- ✅ 图片消息

**数据模型**:
```python
# platform_config for Lark
{
    "app_id": "cli_xxx",
    "app_secret": "xxx",
    "encrypt_key": "xxx",  # 可选
    "verification_token": "xxx"
}
```

**实施步骤**:
1. ✅ Week 3.1: 创建分支 `feature/lark-integration`
2. ✅ Week 3.2: 实现 LarkClient (token 管理)
3. ✅ Week 3.3: 实现 Webhook 路由 (事件解密)
4. ✅ Week 3.4: 实现卡片消息支持
5. ✅ Week 4.1: 会话管理集成
6. ✅ Week 4.2: 测试和调试
7. ✅ Week 4.3: 文档编写
8. ✅ Week 4.4: 合并到 main

**技术要点**:
- Token 管理: tenant_access_token (2小时有效期)
- 事件订阅: Webhook 或 Long-connection
- 消息加密: AES-256-CBC (可选)
- 卡片渲染: 支持交互式模板

---

### Phase 2: 国内企业平台 (1-2周)

#### 2.1 钉钉 (DingTalk) (Week 5-6)

**优先级**: 🟡 中
**理由**:
- 国内企业用户基数大
- API 相对简单
- 但 Webhook 机器人即将下线

**技术方案**:

```python
# dingtalk.py - 钉钉 Bot 客户端

class DingTalkClient:
    """钉钉群机器人客户端 (Webhook)"""
    
    def __init__(self, webhook_url: str, secret: str = None):
        self.webhook_url = webhook_url
        self.secret = secret
    
    async def send_message(
        self,
        msg_type: str,
        content: dict,
        at_mobiles: list = None,
        is_at_all: bool = False
    ) -> dict:
        """发送消息到钉钉群"""
        # 生成签名 (如果配置了 secret)
        timestamp = int(time.time() * 1000)
        sign = self._gen_signature(timestamp)
        
        url = f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"
        data = {
            "msgtype": msg_type,
            msg_type: content,
            "at": {
                "atMobiles": at_mobiles or [],
                "isAtAll": is_at_all
            }
        }
        # 实现 HTTP POST 请求
    
    def _gen_signature(self, timestamp: int) -> str:
        """生成请求签名"""
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        return urllib.parse.quote_plus(base64.b64encode(hmac_code))
```

**⚠️ 重要限制**:
- **单向发送**: 仅支持主动发送消息，不支持接收回调
- **即将下线**: 官方已不再推出新功能
- **替代方案**: 建议使用企业内部应用 (需要 appKey/appSecret)

**支持的消息类型**:
- ✅ 文本消息 (text)
- ✅ Markdown
- ✅ Link (链接)
- ✅ ActionCard
- ✅ FeedCard

**数据模型**:
```python
# platform_config for DingTalk
{
    "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=xxx",
    "secret": "SEC...",  # 可选，用于签名验证
    "at_mobiles": []  # 默认 @ 的手机号列表
}
```

**实施步骤**:
1. ✅ Week 5.1: 创建分支 `feature/dingtalk-integration`
2. ✅ Week 5.2: 实现 DingTalkClient (Webhook 模式)
3. ✅ Week 5.3: 实现签名验证
4. ✅ Week 5.4: 消息发送测试
5. ✅ Week 6.1: 文档编写
6. ✅ Week 6.2: 合并到 main

**技术要点**:
- 签名算法: HmacSHA256
- 频率限制: 每个机器人每分钟 20 条消息
- @ 功能: 通过手机号指定 @对象
- 安全设置: IP 白名单或关键词验证

**未来扩展**:
- 企业内部应用: 支持双向消息 (需要额外开发)
- 事件订阅: 接收群消息回调 (企业应用模式)

---

### Phase 3: 国际扩展平台 (4-6周)

#### 3.1 WhatsApp Business (Week 7-9)

**优先级**: 🟢 低
**理由**:
- 全球用户基数最大
- 商业应用广泛
- 但 API 复杂度高，需要 Facebook 审核

**技术挑战**:
- 需要 Facebook Business Account
- WhatsApp Business API 需要审核
- Webhook 验证复杂
- 消息模板限制严格

**技术方案**:

```python
# whatsapp.py - WhatsApp Business API 客户端

class WhatsAppClient:
    """WhatsApp Business API 客户端"""
    
    def __init__(self, phone_number_id: str, access_token: str):
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.base_url = f"https://graph.facebook.com/v18.0/{phone_number_id}"
    
    async def send_message(
        self,
        to: str,
        message_type: str,
        content: dict
    ) -> dict:
        """发送消息"""
        url = f"{self.base_url}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": message_type,
            message_type: content
        }
        # 实现 HTTP POST 请求
    
    async def handle_webhook(self, data: dict) -> str:
        """处理 webhook 事件"""
        # Webhook 验证
        # 解析消息事件
        # 转发到 Agent
```

**Webhook 配置**:
- URL: `https://hitl.woa.com/callback/whatsapp/{bot_key}`
- 验证: Challenge token 机制
- 格式: JSON (Webhook 对象)
- 签名验证: X-Hub-Signature-256

**支持的消息类型**:
- ✅ 文本消息
- ✅ 模板消息 (需预先审核)
- ✅ 媒体消息 (图片、视频、文档)
- ✅ 交互式按钮

**实施步骤**:
1. Week 7.1-7.2: 申请 WhatsApp Business API 访问
2. Week 7.3-7.4: 创建分支 `feature/whatsapp-integration`
3. Week 8.1-8.2: 实现 WhatsAppClient
4. Week 8.3-8.4: Webhook 验证和事件处理
5. Week 9.1-9.2: 模板消息支持
6. Week 9.3: 测试和调试
7. Week 9.4: 文档编写和合并

**技术要点**:
- 模板消息: 必须预先在 Meta 后台创建并审核
- 24小时窗口: 用户发起对话后有 24 小时可自由回复
- 媒体处理: 上传到 Facebook 服务器获取 media_id
- Webhook 验证: GET 请求验证 token

#### 3.2 Microsoft Teams (Week 10-12)

**优先级**: 🟢 低
**理由**:
- 企业客户常用
- 与 Microsoft 生态集成
- 但需要 Azure 注册，复杂度高

**技术方案**:

```python
# teams.py - Microsoft Teams Bot 客户端

class TeamsClient:
    """Microsoft Teams Bot Framework 客户端"""
    
    def __init__(self, app_id: str, app_password: str):
        self.app_id = app_id
        self.app_password = app_password
        self.connector = None
    
    async def send_activity(
        self,
        conversation_id: str,
        activity: dict
    ) -> dict:
        """发送 Activity (消息)"""
        # 使用 Bot Framework Connector
        # 实现认证和消息发送
    
    async def handle_activity(self, activity: dict) -> dict:
        """处理接收的 Activity"""
        # 解析 Activity 对象
        # 转发到 Agent
        # 构建响应 Activity
```

**Webhook 配置**:
- URL: `https://hitl.woa.com/callback/teams/{bot_key}`
- 方法: POST
- 格式: JSON (Activity 对象)
- 验证: JWT Bearer token

**支持的消息类型**:
- ✅ 文本消息
- ✅ Adaptive Cards
- ✅ 文件附件
- ✅ 会议通知

**实施步骤**:
1. Week 10.1-10.2: Azure Bot Service 注册
2. Week 10.3-10.4: 创建分支 `feature/teams-integration`
3. Week 11.1-11.3: 实现 TeamsClient (Bot Framework)
4. Week 11.4-12.1: Activity 处理和响应
5. Week 12.2: Adaptive Cards 支持
6. Week 12.3: 测试和调试
7. Week 12.4: 文档编写和合并

**技术要点**:
- Bot Framework: 使用 Microsoft Bot Framework SDK
- JWT 验证: 验证来自 Teams 的请求
- Adaptive Cards: 丰富的交互式卡片
- Channel Data: Teams 特定的元数据

#### 3.3 Line (Week 13-14)

**优先级**: 🟢 低
**理由**:
- 日本、泰国等亚洲市场主流
- API 设计良好
- 但国内用户较少

**技术方案**:

```python
# line.py - Line Messaging API 客户端

class LineClient:
    """Line Messaging API 客户端"""
    
    def __init__(self, channel_access_token: str, channel_secret: str):
        self.channel_access_token = channel_access_token
        self.channel_secret = channel_secret
        self.base_url = "https://api.line.me/v2/bot"
    
    async def reply_message(
        self,
        reply_token: str,
        messages: list
    ) -> dict:
        """回复消息"""
        url = f"{self.base_url}/message/reply"
        headers = {
            "Authorization": f"Bearer {self.channel_access_token}",
            "Content-Type": "application/json"
        }
        data = {
            "replyToken": reply_token,
            "messages": messages
        }
        # 实现 HTTP POST 请求
    
    async def handle_webhook(self, body: bytes, signature: str) -> str:
        """处理 webhook 事件"""
        # 验证签名
        # 解析事件
        # 转发到 Agent
        # 使用 reply_token 回复
```

**Webhook 配置**:
- URL: `https://hitl.woa.com/callback/line/{bot_key}`
- 方法: POST
- 格式: JSON (Webhook Event 对象)
- 验证: X-Line-Signature (HMAC-SHA256)

**支持的消息类型**:
- ✅ 文本消息
- ✅ 图片/视频/音频
- ✅ Flex Message (JSON 布局)
- ✅ Quick Reply 按钮

**实施步骤**:
1. Week 13.1: Line Developers Console 注册
2. Week 13.2: 创建分支 `feature/line-integration`
3. Week 13.3-13.4: 实现 LineClient
4. Week 14.1: Webhook 验证和事件处理
5. Week 14.2: Flex Message 支持
6. Week 14.3: 测试和调试
7. Week 14.4: 文档编写和合并

**技术要点**:
- Reply Token: 一次性 token，30秒有效
- 签名验证: HMAC-SHA256 with channel secret
- Push vs Reply: Push 需要费用，Reply 免费
- Flex Message: JSON 定义的灵活布局

---

## 🏗️ 统一架构设计

### 核心接口抽象

为了支持多平台，设计统一的接口抽象：

```python
# base_client.py - 平台客户端基类

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

class BasePlatformClient(ABC):
    """平台客户端基类"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化客户端
        
        Args:
            config: 平台特定配置
        """
        self.config = config
    
    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        content: str,
        message_type: str = "text",
        **kwargs
    ) -> Dict[str, Any]:
        """
        发送消息 (统一接口)
        
        Args:
            chat_id: 对话 ID
            content: 消息内容
            message_type: 消息类型
            **kwargs: 平台特定参数
        
        Returns:
            发送结果
        """
        pass
    
    @abstractmethod
    async def handle_webhook(
        self,
        raw_data: bytes | dict,
        headers: Dict[str, str]
    ) -> Optional[str]:
        """
        处理 webhook 回调 (统一接口)
        
        Args:
            raw_data: 原始请求数据
            headers: 请求头
        
        Returns:
            响应内容 (可选)
        """
        pass
    
    @abstractmethod
    def verify_signature(
        self,
        data: bytes,
        signature: str
    ) -> bool:
        """
        验证请求签名 (平台特定)
        
        Args:
            data: 原始数据
            signature: 签名字符串
        
        Returns:
            验证结果
        """
        pass
    
    @abstractmethod
    def parse_message(
        self,
        raw_message: dict
    ) -> Dict[str, Any]:
        """
        解析平台消息为统一格式
        
        Args:
            raw_message: 平台原始消息
        
        Returns:
            统一消息格式:
            {
                "user_id": str,
                "chat_id": str,
                "content": str,
                "message_type": str,
                "timestamp": int,
                "raw": dict  # 原始数据
            }
        """
        pass


# 平台客户端工厂

class PlatformClientFactory:
    """平台客户端工厂"""
    
    _clients = {
        "wecom": WeComClient,
        "wecom-intelligent": WeComIntelligentClient,
        "slack": SlackClient,
        "discord": DiscordClient,
        "telegram": TelegramClient,
        "lark": LarkClient,
        "dingtalk": DingTalkClient,
        "whatsapp": WhatsAppClient,
        "teams": TeamsClient,
        "line": LineClient,
    }
    
    @classmethod
    def create(cls, platform: str, config: Dict[str, Any]) -> BasePlatformClient:
        """
        创建平台客户端实例
        
        Args:
            platform: 平台类型
            config: 平台配置
        
        Returns:
            平台客户端实例
        """
        client_class = cls._clients.get(platform)
        if not client_class:
            raise ValueError(f"Unsupported platform: {platform}")
        return client_class(config)
```

### 统一消息格式

```python
# message_format.py - 统一消息格式定义

from pydantic import BaseModel
from typing import Literal, Optional, Any

class UnifiedMessage(BaseModel):
    """统一消息格式"""
    
    # 基础字段
    platform: str  # 平台类型
    user_id: str  # 用户 ID
    chat_id: str  # 对话 ID
    message_id: str  # 消息 ID
    timestamp: int  # 时间戳
    
    # 消息内容
    content: str  # 文本内容
    message_type: Literal["text", "image", "audio", "video", "file", "card", "event"]
    
    # 可选字段
    reply_to: Optional[str] = None  # 回复的消息 ID
    mentions: list[str] = []  # @用户列表
    attachments: list[dict] = []  # 附件列表
    
    # 原始数据
    raw: dict  # 平台原始消息数据


class UnifiedResponse(BaseModel):
    """统一响应格式"""
    
    # 基础字段
    platform: str
    chat_id: str
    message_type: Literal["text", "image", "audio", "video", "file", "card"]
    
    # 响应内容
    content: str
    
    # 可选字段
    reply_to: Optional[str] = None
    buttons: list[dict] = []  # 交互按钮
    cards: list[dict] = []  # 卡片数据
    
    # 平台特定数据
    platform_data: dict = {}
```

### 路由统一化

```python
# unified_callback.py - 统一回调路由

@router.post("/callback/{platform}/{bot_key}")
async def unified_callback(
    platform: str,
    bot_key: str,
    request: Request
) -> Response:
    """
    统一平台回调接口
    
    所有平台的 webhook 都路由到这个接口，通过 platform 参数区分
    """
    try:
        # 获取 Bot 配置
        bot = config.get_bot_or_default(bot_key)
        if not bot or bot.platform != platform:
            return JSONResponse(
                status_code=404,
                content={"error": "Bot not found or platform mismatch"}
            )
        
        # 创建平台客户端
        client = PlatformClientFactory.create(
            platform=platform,
            config=bot.get_platform_config()
        )
        
        # 读取请求数据
        raw_data = await request.body()
        headers = dict(request.headers)
        
        # 验证签名 (如果平台需要)
        if hasattr(client, "verify_signature"):
            signature = headers.get("x-signature") or headers.get("x-hub-signature-256")
            if signature and not client.verify_signature(raw_data, signature):
                return JSONResponse(
                    status_code=403,
                    content={"error": "Invalid signature"}
                )
        
        # 处理 webhook
        response = await client.handle_webhook(raw_data, headers)
        
        # 返回响应
        if response:
            return PlainTextResponse(content=response)
        else:
            return Response(status_code=200)
    
    except Exception as e:
        logger.error(f"Unified callback error: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )
```

---

## 📊 数据库设计扩展

### Bot 配置表更新

```sql
-- chatbots 表新增字段

ALTER TABLE chatbots 
ADD COLUMN platform_config TEXT COMMENT '平台特定配置 JSON';

-- 平台配置示例
-- Telegram: {"bot_token": "xxx", "allowed_chat_ids": [123, 456]}
-- Lark: {"app_id": "xxx", "app_secret": "xxx", "encrypt_key": "xxx"}
-- DingTalk: {"webhook_url": "xxx", "secret": "xxx"}
-- WhatsApp: {"phone_number_id": "xxx", "access_token": "xxx"}
-- Teams: {"app_id": "xxx", "app_password": "xxx"}
-- Line: {"channel_access_token": "xxx", "channel_secret": "xxx"}
```

### 平台能力映射表

```python
# platform_capabilities.py - 平台能力映射

PLATFORM_CAPABILITIES = {
    "wecom": {
        "text": True,
        "markdown": True,
        "image": True,
        "file": True,
        "card": True,
        "stream": False,
        "buttons": False,
        "webhook": True,
        "bidirectional": True
    },
    "wecom-intelligent": {
        "text": True,
        "markdown": False,
        "image": True,
        "file": False,
        "card": True,
        "stream": True,
        "buttons": False,
        "webhook": True,
        "bidirectional": True
    },
    "telegram": {
        "text": True,
        "markdown": True,
        "image": True,
        "file": True,
        "card": False,
        "stream": False,
        "buttons": True,
        "webhook": True,
        "bidirectional": True
    },
    "lark": {
        "text": True,
        "markdown": True,
        "image": True,
        "file": True,
        "card": True,
        "stream": False,
        "buttons": True,
        "webhook": True,
        "bidirectional": True
    },
    "dingtalk": {
        "text": True,
        "markdown": True,
        "image": False,
        "file": False,
        "card": True,
        "stream": False,
        "buttons": False,
        "webhook": False,  # 仅支持单向发送
        "bidirectional": False
    },
    # ... 其他平台
}
```

---

## 🧪 测试策略

### 单元测试

每个平台客户端都需要完整的单元测试：

```python
# tests/test_telegram_client.py

import pytest
from forward_service.clients.telegram import TelegramClient

@pytest.fixture
def telegram_client():
    return TelegramClient(bot_token="test_token")

def test_send_message(telegram_client):
    """测试发送消息"""
    # Mock HTTP 请求
    # 验证请求参数
    # 验证响应处理

def test_handle_webhook(telegram_client):
    """测试 webhook 处理"""
    # 构造 Update 对象
    # 调用 handle_webhook
    # 验证消息解析和转发

def test_verify_signature(telegram_client):
    """测试签名验证"""
    # 构造签名
    # 验证签名算法
```

### 集成测试

使用真实的 API 进行端到端测试：

```python
# tests/test_e2e_telegram.py

@pytest.mark.e2e
async def test_telegram_e2e(test_telegram_bot):
    """端到端测试 Telegram 集成"""
    # 1. 创建 Bot 配置
    # 2. 模拟 webhook 回调
    # 3. 验证消息转发到 Agent
    # 4. 验证响应返回到 Telegram
```

### 压力测试

测试各平台的并发处理能力：

```bash
# 使用 locust 或 k6 进行压力测试
locust -f tests/locust_telegram.py --host=http://localhost:8083
```

---

## 📚 文档规范

每个平台集成完成后，需要提供完整的文档：

### 1. 平台集成文档 (`{PLATFORM}_INTEGRATION.md`)

```markdown
# {平台名称} 集成指南

## 概述
- 平台介绍
- 支持的功能
- 限制和注意事项

## 前置条件
- 账号注册
- 权限申请
- 开发环境配置

## 配置步骤
1. 创建 Bot/应用
2. 获取凭证
3. 配置 Webhook
4. 测试验证

## API 参考
- 发送消息
- 接收消息
- 错误处理

## 示例代码
- Python
- cURL

## 常见问题
- FAQ
- 故障排查
```

### 2. 部署文档更新 (`DEPLOYMENT.md`)

每个新平台需要更新部署文档：
- 环境变量配置
- 数据库迁移步骤
- 服务重启命令
- 健康检查方法

---

## 📈 监控和分析

### 指标收集

为每个平台收集关键指标：

```python
# metrics.py - 平台指标收集

from prometheus_client import Counter, Histogram

# 消息计数
platform_messages_total = Counter(
    "platform_messages_total",
    "Total messages by platform",
    ["platform", "message_type", "status"]
)

# 响应时间
platform_response_time = Histogram(
    "platform_response_time_seconds",
    "Response time by platform",
    ["platform"]
)

# API 调用失败
platform_api_errors_total = Counter(
    "platform_api_errors_total",
    "API errors by platform",
    ["platform", "error_type"]
)
```

### 告警规则

```yaml
# prometheus/alerts.yml

groups:
  - name: platform_alerts
    rules:
      - alert: HighPlatformErrorRate
        expr: |
          rate(platform_api_errors_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate on {{ $labels.platform }}"
      
      - alert: SlowPlatformResponse
        expr: |
          histogram_quantile(0.95, rate(platform_response_time_seconds_bucket[5m])) > 3
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Slow response on {{ $labels.platform }}"
```

---

## 🎯 成功标准

每个平台集成完成后，需要满足以下标准：

### 功能标准

- [ ] 支持文本消息收发
- [ ] Webhook 验证通过
- [ ] 签名验证正确
- [ ] 错误处理完善
- [ ] 会话管理集成
- [ ] Slash 命令支持

### 质量标准

- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试通过
- [ ] 性能测试达标 (QPS > 100)
- [ ] 文档完整
- [ ] 代码审查通过

### 运维标准

- [ ] 监控指标完善
- [ ] 告警规则配置
- [ ] 日志记录清晰
- [ ] 部署文档完整
- [ ] 回滚方案明确

---

## 📝 里程碑

| 里程碑 | 目标 | 截止日期 | 状态 |
|--------|------|---------|------|
| M1: Telegram 集成 | 完成 Telegram Bot 接入 | Week 2 | ⏳ 计划中 |
| M2: Lark 集成 | 完成飞书集成 | Week 4 | ⏳ 计划中 |
| M3: DingTalk 集成 | 完成钉钉集成 | Week 6 | ⏳ 计划中 |
| M4: 架构优化 | 统一接口抽象 | Week 7 | ⏳ 计划中 |
| M5: WhatsApp 集成 | 完成 WhatsApp Business 接入 | Week 9 | ⏳ 计划中 |
| M6: Teams 集成 | 完成 Microsoft Teams 接入 | Week 12 | ⏳ 计划中 |
| M7: Line 集成 | 完成 Line 接入 | Week 14 | ⏳ 计划中 |
| M8: 全平台上线 | 所有平台生产就绪 | Week 16 | ⏳ 计划中 |

---

## 🤝 团队协作

### 分工建议

| 角色 | 职责 |
|------|------|
| 后端开发 | 实现平台客户端、Webhook 路由 |
| 前端开发 | 管理界面、配置页面 |
| 测试工程师 | 编写测试用例、执行测试 |
| DevOps | 部署、监控、告警配置 |
| 技术文档 | 编写集成文档、API 文档 |

### 沟通机制

- **每日站会**: 同步进度，解决阻塞
- **周度评审**: 代码审查，质量把关
- **双周回顾**: 总结经验，优化流程

---

## 🔄 持续改进

### 后续优化方向

1. **消息队列**: 引入 RabbitMQ/Kafka 处理高并发
2. **缓存优化**: Redis 缓存 token、会话数据
3. **负载均衡**: 多实例部署，Nginx 负载均衡
4. **容器化**: Docker + Kubernetes 部署
5. **AI 增强**: 
   - 多语言支持 (自动翻译)
   - 情感分析
   - 智能路由 (根据内容分配 Agent)

---

## 📖 参考资源

### 官方文档

- **Telegram**: https://core.telegram.org/bots/api
- **飞书**: https://open.feishu.cn/document/home/index
- **钉钉**: https://open-dingtalk.github.io/developerpedia/
- **WhatsApp**: https://developers.facebook.com/docs/whatsapp
- **Teams**: https://learn.microsoft.com/en-us/microsoftteams/platform/bots/what-are-bots
- **Line**: https://developers.line.biz/en/docs/messaging-api/

### 开源项目

- **python-telegram-bot**: https://github.com/python-telegram-bot/python-telegram-bot
- **slack-sdk**: https://github.com/slackapi/python-slack-sdk
- **discord.py**: https://github.com/Rapptz/discord.py

---

**最后更新**: 2026-01-29  
**版本**: 1.0  
**维护者**: AI Assistant

---

## 附录: 快速参考

### 平台对比表

| 特性 | 企微 | Telegram | 飞书 | 钉钉 | WhatsApp | Teams | Line |
|------|------|----------|------|------|----------|-------|------|
| Webhook | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ | ✅ |
| 双向消息 | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ |
| 富文本 | ✅ | ✅ | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| 卡片消息 | ✅ | ⚠️ | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| 流式响应 | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| 难度 | 中 | 低 | 中 | 低 | 高 | 高 | 中 |

### 优先级排序依据

1. **用户覆盖度**: 潜在用户数量
2. **技术复杂度**: API 难易程度
3. **审核要求**: 是否需要平台审核
4. **文档质量**: 官方文档完善程度
5. **社区支持**: 开源库和社区活跃度

---

**祝接入顺利！** 🚀
