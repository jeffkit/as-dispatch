# IM 渠道接入指南

> 适用版本：`intelligent-bot` 分支（多平台统一架构）  
> 最后更新：2026-03-02

本文档覆盖 AS-Dispatch 支持的全部 5 个 IM 渠道的完整接入流程，包括凭据申请、服务配置、Webhook 注册和验证测试。

---

## 目录

- [架构概览](#架构概览)
- [通用配置说明](#通用配置说明)
- [企业微信（WeCom）](#企业微信wecom)
- [Telegram](#telegram)
- [飞书（Lark）](#飞书lark)
- [Slack](#slack)
- [Discord](#discord)
- [多渠道配置示例](#多渠道配置示例)
- [常见问题排查](#常见问题排查)

---

## 架构概览

所有 IM 渠道经过统一的消息处理管线，架构如下：

```
IM 平台  →  Webhook 回调  →  ChannelAdapter（解析）  →  统一管线  →  AI 后端
                               ↑ 各平台实现                  ↓
IM 平台  ←  send_outbound  ←  ChannelAdapter（发送）  ←  AI 响应
```

统一回调入口（企微除外）：
```
POST https://your-server.com/callback/{platform}
```

| 平台 | `{platform}` 值 | 接入方式 | `bot_key` 来源 |
|------|-----------------|---------|----------------|
| 企业微信 | `wecom` | HTTP Webhook | Webhook URL 中的 `key` 参数 |
| Telegram | `telegram` | HTTP Webhook | 请求头 `X-Telegram-Bot-Api-Secret-Token` |
| 飞书 | `lark` | HTTP Webhook | 事件 Header 中的 `app_id` |
| Slack | `slack` | HTTP Webhook | 事件体中的 `api_app_id` |
| Discord | `discord` | WebSocket Gateway | 配置中的 `bot_key` |

---

## 通用配置说明

### Bot 配置结构

每个 Bot 在 `data/forward_bots.json` 中（或数据库模式下的 `chatbots` 表）使用以下结构：

```json
{
  "bot_key": "唯一标识符",
  "name": "机器人显示名称",
  "platform": "wecom | telegram | lark | slack | discord",
  "platform_config": {
    // 平台特定凭据，见各平台章节
  },
  "target_url": "http://localhost:4936/a2a/<agent-id>/messages",
  "access_mode": "whitelist | blacklist | none",
  "whitelist": [],
  "blacklist": [],
  "enabled": true
}
```

### 服务启动

```bash
# JSON 文件模式（开发）
uv run python -m forward_service.app

# 数据库模式（生产）
USE_DATABASE=true uv run python -m forward_service.app

# 自定义端口
FORWARD_PORT=8083 uv run python -m forward_service.app
```

---

## 企业微信（WeCom）

### 1. 创建机器人

1. 打开企业微信 → 进入目标群聊
2. 点击右上角 **「...」** → **「群机器人」** → **「添加机器人」** → **「新创建一个机器人」**
3. 设置机器人名称、头像
4. 复制 **Webhook 地址**，格式为：
   ```
   https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   ```
   其中 `key` 参数值即为 `bot_key`

### 2. 服务配置

**JSON 文件模式**（`data/forward_bots.json`）：

```json
{
  "default_bot_key": "my-wecom-bot",
  "bots": {
    "my-wecom-bot": {
      "bot_key": "my-wecom-bot",
      "name": "企微 AI 助手",
      "platform": "wecom",
      "platform_config": {
        "wecom_key": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
      },
      "target_url": "http://localhost:4936/a2a/your-agent-id/messages",
      "access_mode": "whitelist",
      "whitelist": ["user1", "user2"],
      "enabled": true
    }
  }
}
```

> **注意**：企微的 `bot_key` 是你在 `forward_bots.json` 中自定义的标识符（如 `my-wecom-bot`），不是微信的 `key` 参数。微信 `key` 参数存入 `platform_config.wecom_key` 供发送消息时使用。

**数据库模式**（Admin API）：

```bash
curl -X POST "http://localhost:8083/admin/bots" \
  -H "Content-Type: application/json" \
  -d '{
    "bot_key": "my-wecom-bot",
    "name": "企微 AI 助手",
    "platform": "wecom",
    "platform_config": {
      "wecom_key": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    },
    "target_url": "http://localhost:4936/a2a/your-agent-id/messages",
    "enabled": true
  }'
```

### 3. 注册回调地址

企微机器人需要在 **企业微信管理后台** 配置接收消息的 URL：

1. 进入 [企业微信管理后台](https://work.weixin.qq.com/) → **「应用管理」** → 找到对应机器人
2. 在「接收消息」中设置 URL：
   ```
   https://your-server.com/callback/wecom
   ```
3. 设置 Token 和 EncodingAESKey（如需加密模式）

> **本地开发**：如果服务运行在本地，需要通过内网穿透暴露地址。AS-Dispatch 内置了 Tunely 隧道支持，详见 [TUNNEL_CONFIG.md](./TUNNEL_CONFIG.md)。

### 4. Platform Config 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `wecom_key` | string | ✅ | 企微 Webhook URL 中的 `key` 参数 |

### 5. 验证接入

在群聊中 @ 机器人发送消息，机器人应在 30 秒内回复：

```
@AI助手 你好
```

---

## Telegram

### 1. 创建 Bot

1. 在 Telegram 搜索 **@BotFather**
2. 发送 `/newbot`
3. 按提示设置机器人名称（Name）和用户名（Username，必须以 `bot` 结尾）
4. 复制获得的 **Bot Token**，格式为：
   ```
   6543210987:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
   ```

### 2. 服务配置

```json
{
  "bot_key": "my-telegram-bot",
  "name": "Telegram AI 助手",
  "platform": "telegram",
  "platform_config": {
    "bot_token": "6543210987:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
    "secret_token": "my-telegram-bot"
  },
  "target_url": "http://localhost:4936/a2a/your-agent-id/messages",
  "enabled": true
}
```

> **关键**：`secret_token` 必须与 `bot_key` **保持一致**。Telegram 会将 `secret_token` 附在每个 Webhook 请求的 `X-Telegram-Bot-Api-Secret-Token` 头中，AS-Dispatch 以此来识别是哪个 Bot 收到了消息。

### 3. 注册 Webhook

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-server.com/callback/telegram",
    "secret_token": "<BOT_KEY>"
  }'
```

将 `<BOT_TOKEN>` 换成实际 Token，`<BOT_KEY>` 换成与 `platform_config.secret_token` 相同的值。

**验证 Webhook 状态**：

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```

响应中 `url` 字段应指向你的服务器，`last_error_message` 应为空。

### 4. Platform Config 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bot_token` | string | ✅ | 从 @BotFather 获取的 Token |
| `secret_token` | string | ✅ | Webhook 验证 Token，**必须与 `bot_key` 相同** |

### 5. 允许的消息类型

| 类型 | 支持 | 说明 |
|------|------|------|
| 文本消息 | ✅ | 包含 Markdown |
| 图片 | ✅ | 自动获取最大尺寸，通过 getFile API 解析为 URL |
| 图片 + 文字（caption） | ✅ | 图文混合消息 |
| Sticker / 视频 / 语音 | ❌ | 当前忽略 |
| Bot 消息 | ❌（自动过滤） | 防止死循环 |

### 6. 验证接入

向 Bot 发送私信或在加入 Bot 的群里发消息：

```
/start
你好，介绍一下你自己
```

---

## 飞书（Lark）

### 1. 创建飞书应用

1. 访问 [飞书开放平台](https://open.feishu.cn/) → **「开发者后台」**
2. 点击 **「创建企业自建应用」**
3. 填写应用名称、描述
4. 在左侧菜单 **「凭证与基础信息」** 中获取：
   - **App ID**（格式：`cli_xxxxxxxxxxxxxxxxx`）
   - **App Secret**

5. 在 **「事件订阅」** 中：
   - 设置 **请求网址**：
     ```
     https://your-server.com/callback/lark
     ```
   - 如需加密，开启「加密策略」，记录 **Encrypt Key**
   - 记录 **Verification Token**
   - 订阅事件：搜索并添加 **`im.message.receive_v1`**（接收消息事件）

6. 在 **「权限管理」** 中申请权限：
   - `im:message` — 获取/发送消息
   - `im:message.group_at_msg` — 接收群组 @ 消息
   - `im:message.p2p_msg` — 接收单聊消息

7. 发布应用，等待管理员审批

### 2. 服务配置

```json
{
  "bot_key": "cli_xxxxxxxxxxxxxxxxx",
  "name": "飞书 AI 助手",
  "platform": "lark",
  "platform_config": {
    "app_id": "cli_xxxxxxxxxxxxxxxxx",
    "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "encrypt_key": "xxxxxxxxxxxxxxxxxxxx",
    "verification_token": "xxxxxxxxxxxxxxxxxxxx"
  },
  "target_url": "http://localhost:4936/a2a/your-agent-id/messages",
  "enabled": true
}
```

> **关键**：飞书的 `bot_key` 必须与 `platform_config.app_id` **保持一致**。适配器从事件 Header 的 `app_id` 字段自动提取，用于查找对应的 Bot 配置。

### 3. URL 验证

飞书在保存 Webhook URL 时会发送 `url_verification` 请求。适配器会自动处理并返回正确的 challenge 响应，无需手动干预。

确认服务已启动后，在飞书开发者后台点击 **「保存」**，飞书会实时验证 URL 有效性。

### 4. Platform Config 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `app_id` | string | ✅ | 飞书应用 App ID，以 `cli_` 开头 |
| `app_secret` | string | ✅ | 飞书应用 App Secret |
| `encrypt_key` | string | ❌ | 事件加密 Key（如开启了加密策略则必填） |
| `verification_token` | string | ❌ | 验证 Token（推荐填写以增强安全性） |

### 5. 允许的消息类型

| 类型 | 支持 | 说明 |
|------|------|------|
| 文本消息 | ✅ | `text` 类型 |
| 图片 | ✅ | 存储 `image_key`（飞书图片需授权访问，暂不解析为公开 URL） |
| 富文本 | ❌（计划中） | `post` 类型 |
| 卡片消息 | ❌（计划中） | `interactive` 类型 |
| Bot 消息 | ❌（自动过滤） | `sender_type == "app"` |

### 6. 将机器人加入群组

1. 在飞书中打开目标群组
2. 点击右上角设置 → **「群机器人」** → **「添加机器人」**
3. 搜索并添加你的应用

然后在群中 @ 机器人发消息即可触发。

---

## Slack

### 1. 创建 Slack App

1. 访问 [Slack API](https://api.slack.com/apps) → **「Create New App」** → **「From scratch」**
2. 填写 App Name，选择工作区
3. 在 **「OAuth & Permissions」** 中添加 Bot Token Scopes：
   - `chat:write` — 发送消息
   - `channels:history` — 读取公共频道消息
   - `groups:history` — 读取私有频道消息
   - `im:history` — 读取私信
   - `files:read` — 读取文件（图片支持）
4. 点击 **「Install to Workspace」**，复制 **Bot User OAuth Token**（以 `xoxb-` 开头）

5. 在 **「Event Subscriptions」** 中：
   - 开启 Events
   - 设置 **Request URL**：
     ```
     https://your-server.com/callback/slack
     ```
   - 飞书会发送 URL 验证请求，AS-Dispatch 会自动响应（需服务已启动）
   - 在 **「Subscribe to bot events」** 中添加：
     - `message.channels` — 公共频道消息
     - `message.groups` — 私有频道消息
     - `message.im` — 私信
     - `app_mention` — 被 @ 时

6. 记录 **App ID**（在 **「Basic Information」** 页面，格式 `Axxxxxxxxxx`）

### 2. 服务配置

```json
{
  "bot_key": "Axxxxxxxxxx",
  "name": "Slack AI 助手",
  "platform": "slack",
  "platform_config": {
    "bot_token": "xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx"
  },
  "target_url": "http://localhost:4936/a2a/your-agent-id/messages",
  "enabled": true
}
```

> **关键**：Slack 的 `bot_key` 必须与 **App ID** 一致（即 Slack 事件体中的 `api_app_id` 字段值）。适配器会自动从事件体中提取此值来匹配 Bot 配置。

### 3. URL 验证

Slack 在保存 Request URL 时会发送 `url_verification` 类型的 POST 请求。确保服务已启动，AS-Dispatch 会自动返回 `{"challenge": "..."}` 响应。

### 4. Platform Config 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bot_token` | string | ✅ | Bot User OAuth Token，以 `xoxb-` 开头 |

### 5. 重试处理

Slack 在收不到 200 响应时会自动重试（最多 3 次），AS-Dispatch 通过检测 `X-Slack-Retry-Num` 请求头自动忽略重试消息，避免重复处理。

### 6. 允许的消息类型

| 类型 | 支持 | 说明 |
|------|------|------|
| 文本消息 | ✅ | `event.type == "message"` |
| App Mention（被 @）| ✅ | `event.type == "app_mention"` |
| 图片文件 | ✅ | 从 `event.files` 提取 `url_private_download` |
| Bot 消息 | ❌（自动过滤） | `event.bot_id` 存在时忽略 |
| 重试请求 | ❌（自动过滤） | `X-Slack-Retry-Num` 头存在时忽略 |

### 7. 将 App 添加到频道

在 Slack 频道中输入：
```
/invite @你的-app-名称
```

然后 @ 机器人即可：
```
@AI助手 帮我写一段代码
```

---

## Discord

### 1. 创建 Discord Bot

1. 访问 [Discord Developer Portal](https://discord.com/developers/applications) → **「New Application」**
2. 填写应用名称，点击 **「Create」**
3. 在左侧 **「Bot」** 菜单：
   - 点击 **「Add Bot」** → **「Yes, do it!」**
   - 点击 **「Reset Token」** 获取 **Bot Token**
   - 开启以下 **Privileged Gateway Intents**：
     - ✅ `MESSAGE CONTENT INTENT`（必须，读取消息内容）
     - ✅ `SERVER MEMBERS INTENT`（可选，获取成员信息）

4. 在 **「OAuth2」** → **「URL Generator」** 中生成邀请链接：
   - Scopes：选择 `bot`
   - Bot Permissions：选择 `Send Messages`、`Read Message History`、`View Channels`
   - 复制生成的 URL，用浏览器打开并将 Bot 邀请到你的服务器

### 2. 服务配置

Discord 使用 **WebSocket Gateway**（非 HTTP Webhook），不需要设置 Webhook URL。服务启动时 Bot 会自动与 Discord 建立 WebSocket 连接。

```json
{
  "bot_key": "my-discord-bot",
  "name": "Discord AI 助手",
  "platform": "discord",
  "platform_config": {
    "bot_token": "MTxxxxxxxxxxxxxxxxxxxxxxxx.xxxxxx.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  },
  "target_url": "http://localhost:4936/a2a/your-agent-id/messages",
  "enabled": true
}
```

> **注意**：Discord 的 `bot_key` 是你自定义的标识符（任意字符串），因为 Discord 通过 WebSocket 而非 Webhook 通信，无法从请求中自动提取标识。

### 3. Discord 架构说明

与其他 4 个平台不同，Discord 不走 `POST /callback/discord` HTTP 接口，而是通过 `discord.py` 库保持 **WebSocket 长连接**。消息到来时直接触发 `on_message` 事件回调，内部再经过 `DiscordAdapter → 统一管线` 处理。

这意味着：
- **无需配置外网 Webhook URL**（即使本地开发也可正常工作）
- Bot 必须保持服务进程运行（WebSocket 断连后 Bot 离线）
- 服务重启时 Bot 会自动重连

### 4. Platform Config 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `bot_token` | string | ✅ | Discord Bot Token（从 Developer Portal 获取） |

### 5. 允许的消息类型

| 类型 | 支持 | 说明 |
|------|------|------|
| 文本消息 | ✅ | 频道消息和私信 |
| 图片附件 | ✅ | `attachment.content_type` 以 `image/` 开头的附件 |
| 其他文件附件 | ❌ | 当前忽略 |
| Bot 自身消息 | ❌（自动过滤） | `author.bot == True` |

### 6. 消息长度限制

Discord 单条消息限制 **2000 字符**，AI 响应超出时自动分拆发送（标注 `(1/n)` 前缀）。

---

## 多渠道配置示例

以下是一个同时接入全部 5 个渠道的完整配置文件示例：

```json
{
  "default_bot_key": "wecom-main",
  "bots": {
    "wecom-main": {
      "bot_key": "wecom-main",
      "name": "企微 AI 助手",
      "platform": "wecom",
      "platform_config": {
        "wecom_key": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
      },
      "target_url": "http://localhost:4936/a2a/agent-id/messages",
      "access_mode": "whitelist",
      "whitelist": ["zhangsan", "lisi"],
      "enabled": true
    },

    "my-telegram-bot": {
      "bot_key": "my-telegram-bot",
      "name": "Telegram AI 助手",
      "platform": "telegram",
      "platform_config": {
        "bot_token": "6543210987:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",
        "secret_token": "my-telegram-bot"
      },
      "target_url": "http://localhost:4936/a2a/agent-id/messages",
      "enabled": true
    },

    "cli_xxxxxxxxxxxxxxxxx": {
      "bot_key": "cli_xxxxxxxxxxxxxxxxx",
      "name": "飞书 AI 助手",
      "platform": "lark",
      "platform_config": {
        "app_id": "cli_xxxxxxxxxxxxxxxxx",
        "app_secret": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "encrypt_key": "xxxxxxxxxxxxxxxxxxxx",
        "verification_token": "xxxxxxxxxxxxxxxxxxxx"
      },
      "target_url": "http://localhost:4936/a2a/agent-id/messages",
      "enabled": true
    },

    "Axxxxxxxxxx": {
      "bot_key": "Axxxxxxxxxx",
      "name": "Slack AI 助手",
      "platform": "slack",
      "platform_config": {
        "bot_token": "xoxb-xxxxxxxxxxxx-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx"
      },
      "target_url": "http://localhost:4936/a2a/agent-id/messages",
      "enabled": true
    },

    "my-discord-bot": {
      "bot_key": "my-discord-bot",
      "name": "Discord AI 助手",
      "platform": "discord",
      "platform_config": {
        "bot_token": "MTxxxxxxxxxxxxxxxxxxxxxxxx.xxxxxx.xxxxxxxxxxxxxxxxxxxx"
      },
      "target_url": "http://localhost:4936/a2a/agent-id/messages",
      "enabled": true
    }
  }
}
```

---

## Bot Key 映射速查表

各平台 `bot_key` 的值规则和来源：

| 平台 | `bot_key` 的值 | 从哪里获取 | 适配器如何识别 |
|------|---------------|-----------|----------------|
| **企微** | 自定义字符串（如 `wecom-main`） | 运维人员自定义 | 从 Webhook URL 的 `key` 参数提取，与配置中 `wecom_key` 匹配 |
| **Telegram** | 自定义字符串（如 `my-telegram-bot`） | 运维人员自定义 | 从请求头 `X-Telegram-Bot-Api-Secret-Token` 提取，直接等于 `bot_key` |
| **飞书** | **必须等于 App ID**（如 `cli_xxx`） | 飞书开放平台 | 从事件 `header.app_id` 自动提取 |
| **Slack** | **必须等于 App ID**（如 `Axxx`） | Slack API 管理台 | 从事件体 `api_app_id` 自动提取 |
| **Discord** | 自定义字符串（如 `my-discord-bot`） | 运维人员自定义 | WebSocket 连接时由路由代码传入 |

---

## Webhook URL 汇总

| 平台 | Webhook 类型 | URL 格式 |
|------|-------------|---------|
| 企微 | HTTP POST | `https://your-server.com/callback/wecom` |
| Telegram | HTTP POST | `https://your-server.com/callback/telegram` |
| 飞书 | HTTP POST | `https://your-server.com/callback/lark` |
| Slack | HTTP POST | `https://your-server.com/callback/slack` |
| Discord | WebSocket（discord.py 管理） | 无需配置 URL |

> **本地开发**：建议使用内置 Tunely 隧道将本地服务暴露到外网，详见 [TUNNEL_CONFIG.md](./TUNNEL_CONFIG.md)。

---

## 常见问题排查

### Bot 没有响应消息

**1. 检查服务是否正常运行**
```bash
curl http://localhost:8083/api/info
```

**2. 检查 Bot 配置是否存在且启用**
```bash
curl http://localhost:8083/admin/bots
```

**3. 查看实时日志**
```bash
uv run python -m forward_service.app 2>&1 | grep -E "(ERROR|WARNING|bot_key)"
```

---

### Telegram Bot 没有收到消息

**检查 Webhook 状态**：
```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```

注意 `last_error_message` 字段，常见错误：
- `SSL_CERTIFICATE_VERIFY_FAILED` → 服务器证书问题，需要有效的 HTTPS 证书
- `Connection refused` → 服务未启动或端口不通
- `PEER_CERTIFICATE_NOT_VERIFIED` → 证书链不完整

**重新注册 Webhook**：
```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -d "url=https://your-server.com/callback/telegram" \
  -d "secret_token=<BOT_KEY>"
```

---

### 飞书 URL 验证失败

1. 确认服务已正常启动（飞书会立即发验证请求）
2. 确认 URL 可以被飞书服务器访问（需公网 HTTPS）
3. 查看服务日志中是否有 `[lark] 处理 URL 验证挑战` 的输出

---

### Slack URL 验证失败

与飞书类似，确认服务已启动且可从公网访问：
```bash
# 手动模拟验证请求
curl -X POST "http://localhost:8083/callback/slack" \
  -H "Content-Type: application/json" \
  -d '{"type": "url_verification", "challenge": "test-challenge-123"}'
# 期望响应: {"challenge": "test-challenge-123"}
```

---

### Slack 消息被重复处理

检查日志是否出现 `检测到 Slack 重试请求` 的输出。如果重复处理仍然发生：

1. 确认服务在 3 秒内返回 200 响应（Slack 超时重试阈值）
2. 如果 AI 响应较慢，确认 `process_message` 是异步处理的

---

### Discord Bot 离线 / 无响应

1. 确认已开启 `MESSAGE CONTENT INTENT`（在 Developer Portal → Bot → Privileged Gateway Intents）
2. 检查 Bot Token 是否正确
3. 确认 Bot 已被邀请加入服务器且有频道读写权限
4. 查看日志中的 discord 相关错误

```bash
# 手动验证 Token
python3 -c "
import discord
import asyncio

async def check():
    client = discord.Client(intents=discord.Intents.default())
    await client.login('<BOT_TOKEN>')
    print('Token valid:', client.user)
    await client.close()

asyncio.run(check())
"
```

---

### 查看某个平台的适配器状态

```bash
# 查看所有已注册的适配器
curl http://localhost:8083/admin/adapters 2>/dev/null || \
  python3 -c "
from forward_service.channel import list_adapters
import asyncio
print(list(list_adapters().keys()))
"
```

---

## 相关文档

- [MULTI_PLATFORM_ROADMAP.md](./MULTI_PLATFORM_ROADMAP.md) — 多平台支持路线图
- [TUNNEL_CONFIG.md](./TUNNEL_CONFIG.md) — 内网穿透（本地开发）
- [TELEGRAM_INTEGRATION.md](./TELEGRAM_INTEGRATION.md) — Telegram 详细集成文档
- [LARK_INTEGRATION.md](./LARK_INTEGRATION.md) — 飞书详细集成文档
- [SLACK_INTEGRATION.md](./SLACK_INTEGRATION.md) — Slack 详细集成文档
- [DISCORD_INTEGRATION.md](./DISCORD_INTEGRATION.md) — Discord 详细集成文档
- [README.md](./README.md) — 服务概览和快速开始
