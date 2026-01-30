# 飞书 (Lark) Bot 集成指南

## 概述

AS-Dispatch 现已支持飞书 Bot 集成，可将用户消息转发到 AgentStudio 进行处理。

### 支持的功能

- ✅ 文本消息收发
- ✅ 富文本消息
- ✅ 交互式卡片
- ✅ 会话管理 (多会话切换)
- ✅ Slash 命令 (/sess, /reset, /change)
- ✅ Webhook URL 验证
- ✅ 事件加解密
- ✅ Token 自动管理 (tenant_access_token)
- 🚧 图片/文件消息 (计划中)

### 限制

- Token 有效期: 2 小时 (自动刷新)
- 文本消息最大长度: 约 10000 字符
- 需要企业自建应用权限

---

## 前置条件

### 1. 创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn/app)
2. 点击 **创建企业自建应用**
3. 填写应用信息:
   - 应用名称
   - 应用描述
   - 应用图标
4. 创建完成后，记录:
   - **App ID** (cli_xxx)
   - **App Secret**

### 2. 配置应用权限

在应用管理页面，添加以下权限:

**消息相关权限**:
- `im:message` - 获取与发送单聊、群组消息
- `im:message:send_as_bot` - 以应用身份发消息
- `im:chat` - 获取群组信息

### 3. 配置事件订阅

#### 方式 1: Webhook (推荐)

1. 在 **事件订阅** 页面
2. 选择 **Webhook 方式**
3. 设置 Webhook URL: `https://hitl.woa.com/callback/lark/<BOT_KEY>`
4. 配置加密设置 (可选):
   - Encrypt Key (用于事件加密)
   - Verification Token (用于 URL 验证)
5. 添加订阅事件:
   - `im.message.receive_v1` - 接收消息

#### 方式 2: 长连接 (开发调试)

暂不支持，建议使用 Webhook。

### 4. 发布应用

1. 完成配置后，点击 **发布版本**
2. 在企业管理后台审核通过
3. 应用发布后，用户可添加 Bot

---

## 配置步骤

### 方式 1: 通过数据库配置

```sql
INSERT INTO chatbots (
    bot_key,
    name,
    platform,
    platform_config,
    target_url,
    enabled
) VALUES (
    'my-lark-bot',
    'My Lark Bot',
    'lark',
    '{
        "app_id": "cli_abc123456",
        "app_secret": "your-app-secret",
        "encrypt_key": "your-encrypt-key",
        "verification_token": "your-verification-token"
    }',
    'http://localhost:4936/a2a/your-agent-id/messages',
    1
);
```

### 方式 2: 通过 Admin API 配置

```bash
curl -X POST "http://localhost:8083/admin/bots" \
  -H "Content-Type: application/json" \
  -d '{
    "bot_key": "my-lark-bot",
    "name": "My Lark Bot",
    "platform": "lark",
    "platform_config": {
      "app_id": "cli_abc123456",
      "app_secret": "your-app-secret",
      "encrypt_key": "your-encrypt-key",
      "verification_token": "your-verification-token"
    },
    "target_url": "http://localhost:4936/a2a/your-agent-id/messages",
    "enabled": true
  }'
```

### Platform Config 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `app_id` | string | ✅ | 应用 ID (cli_xxx) |
| `app_secret` | string | ✅ | 应用 Secret |
| `encrypt_key` | string | ❌ | 加密密钥 (用于事件解密) |
| `verification_token` | string | ❌ | 验证 Token (用于 URL 验证) |

---

## 使用指南

### 基本对话

1. 在飞书中搜索你的应用名称
2. 添加 Bot 到聊天或群组
3. 发送消息: `你好，帮我写一段代码`
4. Bot 会自动转发到 AgentStudio 处理
5. Agent 响应会自动回复到飞书

### Slash 命令

飞书支持与 Telegram 相同的 Slash 命令:

#### `/sess` 或 `/s` - 列出会话

```
/sess
```

#### `/reset` 或 `/r` - 重置会话

```
/reset
```

#### `/change <id>` 或 `/c <id>` - 切换会话

```
/c abc123
```

---

## API 参考

### Token 管理

飞书使用 tenant_access_token 进行 API 认证:

```python
from forward_service.clients.lark import LarkClient

client = LarkClient(
    app_id="cli_abc123456",
    app_secret="your-app-secret"
)

# 自动获取和缓存 token (有效期 2 小时)
token = await client.get_tenant_access_token()
```

### 消息格式

#### 接收的事件对象

飞书发送的 Webhook 数据格式:

```json
{
  "schema": "2.0",
  "header": {
    "event_id": "xxx",
    "event_type": "im.message.receive_v1",
    "create_time": "1738166400000",
    "token": "verification_token",
    "app_id": "cli_abc123456"
  },
  "event": {
    "sender": {
      "sender_id": {
        "open_id": "ou_xxx",
        "user_id": "xxx"
      }
    },
    "message": {
      "message_id": "om_xxx",
      "root_id": "om_xxx",
      "parent_id": "om_xxx",
      "create_time": "1738166400000",
      "chat_id": "oc_xxx",
      "chat_type": "group",
      "message_type": "text",
      "content": "{\"text\":\"Hello\"}"
    }
  }
}
```

#### 发送消息 API

```python
from forward_service.clients.lark import LarkClient

client = LarkClient(
    app_id="cli_abc123456",
    app_secret="your-app-secret"
)

# 发送文本消息
await client.send_text(
    receive_id="oc_abc123456",
    text="Hello from AS-Dispatch!"
)

# 发送富文本消息
await client.send_rich_text(
    receive_id="oc_abc123456",
    title="标题",
    content=[
        [{"tag": "text", "text": "这是一段文本"}],
        [{"tag": "a", "text": "这是链接", "href": "https://example.com"}]
    ]
)

# 发送交互式卡片
card = client.build_text_card(
    title="提示",
    content="这是卡片内容",
    note="备注信息"
)
await client.send_card(
    receive_id="oc_abc123456",
    card=card
)
```

---

## 事件加密

### 配置加密

1. 在飞书开放平台 **事件订阅** 页面
2. 启用 **加密**
3. 设置 **Encrypt Key** (AES 密钥)
4. 将 Encrypt Key 配置到 `platform_config.encrypt_key`

### 解密流程

```python
# AS-Dispatch 会自动解密事件
client = LarkClient(
    app_id="...",
    app_secret="...",
    encrypt_key="your-encrypt-key"  # 配置后自动解密
)

# 手动解密 (通常不需要)
decrypted_event = client.decrypt_event(encrypted_data)
```

---

## 富文本和卡片

### 富文本消息

支持多种内容类型:

```python
content = [
    # 文本
    [{"tag": "text", "text": "普通文本"}],
    
    # 链接
    [{"tag": "a", "text": "点击链接", "href": "https://example.com"}],
    
    # @用户
    [{"tag": "at", "user_id": "ou_xxx"}],
    
    # 图片
    [{"tag": "img", "image_key": "img_v2_xxx"}],
]

await client.send_rich_text(
    receive_id="oc_xxx",
    title="标题",
    content=content
)
```

### 交互式卡片

```python
# 简单文本卡片
card = client.build_text_card(
    title="卡片标题",
    content="卡片内容...",
    note="备注信息"
)

# 完整卡片配置
card = {
    "config": {"wide_screen_mode": True},
    "header": {
        "title": {"tag": "plain_text", "content": "标题"}
    },
    "elements": [
        {
            "tag": "div",
            "text": {"tag": "markdown", "content": "**Markdown** 内容"}
        },
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "按钮"},
                    "value": {"key": "value"}
                }
            ]
        }
    ]
}

await client.send_card(receive_id="oc_xxx", card=card)
```

---

## 测试

### 测试 Webhook URL

飞书在配置 Webhook 时会发送验证请求:

```json
{
  "challenge": "ajls384kdjx98XX",
  "token": "your-verification-token",
  "type": "url_verification"
}
```

AS-Dispatch 会自动响应:

```json
{
  "challenge": "ajls384kdjx98XX"
}
```

### 测试消息发送

```bash
# 使用 API 发送测试消息
curl -X POST "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id" \
  -H "Authorization: Bearer YOUR_TENANT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "receive_id": "oc_abc123456",
    "msg_type": "text",
    "content": "{\"text\":\"Test message\"}"
  }'
```

---

## 常见问题

### 1. Token 获取失败

**错误**: `"code": 99991663, "msg": "app_id or app_secret invalid"`

**解决**:
- 检查 App ID 和 App Secret 是否正确
- 确认应用已发布
- 检查网络是否能访问飞书 API

### 2. 事件解密失败

**错误**: `解密事件失败: Padding is incorrect`

**解决**:
- 检查 Encrypt Key 是否正确
- 确认加密算法为 AES-256-CBC
- 验证 Base64 解码是否正确

### 3. URL 验证失败

**错误**: `"msg": "challenge error"`

**解决**:
- 检查 Verification Token 是否正确
- 确认 Webhook URL 可访问
- 查看服务器日志中的错误信息

### 4. 消息发送失败

**常见错误码**:

| Code | 说明 | 解决方法 |
|------|------|---------|
| 99991668 | 无效的 tenant_access_token | 重新获取 token |
| 230002 | Bot 不在群组中 | 将 Bot 添加到群组 |
| 230011 | 消息过长 | 减少消息长度或使用卡片 |
| 10012 | 权限不足 | 检查应用权限配置 |

### 5. Token 频繁过期

Token 有效期为 2 小时，AS-Dispatch 会自动管理:
- 缓存 token
- 提前 5 分钟刷新
- 失败时重试

如果仍有问题:
```python
# 强制刷新 token
token = await client.get_tenant_access_token(force_refresh=True)
```

---

## 安全建议

1. **启用加密**: 配置 Encrypt Key 加密事件数据
2. **验证 Token**: 配置 Verification Token 验证 URL
3. **IP 白名单**: 限制只接受飞书官方 IP 的请求
4. **权限最小化**: 只申请必要的 API 权限
5. **定期轮换**: 定期更新 App Secret 和 Encrypt Key

---

## 高级功能

### 消息卡片交互

```python
# 带按钮的卡片
card = {
    "config": {"wide_screen_mode": True},
    "elements": [
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "提交"},
                    "type": "primary",
                    "value": {"action": "submit"}
                }
            ]
        }
    ]
}
```

### 群组管理

```python
# 获取群组信息
# (需要额外 API 调用，暂未实现)
```

### 文件上传

```python
# 上传图片/文件
# (需要额外 API 调用，计划中)
```

---

## 迁移指南

### 从 Webhook 机器人迁移

如果之前使用飞书 Webhook 机器人 (已废弃):

1. 创建企业自建应用
2. 配置事件订阅
3. 更新配置: 使用 `app_id` 和 `app_secret` 替代 `webhook_url`
4. 测试消息收发

### 从其他平台迁移

从企微/Telegram 迁移:
- 会话管理相同
- Slash 命令相同
- 仅需更新 `platform` 和 `platform_config`

---

## 相关资源

- [飞书开放平台](https://open.feishu.cn/)
- [消息 API 文档](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create)
- [事件订阅](https://open.feishu.cn/document/ukTMukTMukTM/uUTNz4SN1MjL1UzM)
- [卡片搭建工具](https://open.feishu.cn/tool/cardbuilder)
- [AS-Dispatch 主文档](./README.md)

---

**最后更新**: 2026-01-29
**版本**: 1.0
