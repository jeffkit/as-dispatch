# QQ Bot 接入指南

将 QQ 机器人接入 AS-Dispatcher，通过 QQ 开放平台 Bot API 与 AgentStudio Agent 交互。

## 架构概述

```
QQ 用户 (C2C/群聊)
     │
     ▼
QQ 开放平台 WebSocket Gateway
     │
     ▼
AS-Dispatcher (QQBotClient)
     │  WebSocket 长连接接收消息
     ▼
QQBotAdapter.parse_inbound()
     │  统一 InboundMessage 格式
     ▼
pipeline.process_message()
     │  10 步统一处理管线
     ▼
forward_to_agent_with_user_project()
     │  HTTP 转发到 AgentStudio
     ▼
QQBotAdapter.send_outbound()
     │  QQ Bot HTTP API 发送回复
     ▼
QQ 用户收到消息
```

## 前置条件

### 1. 注册 QQ 开放平台

前往 [QQ 开放平台](https://q.qq.com/) 注册账号（需要单独注册，不能用个人 QQ 登录）。

### 2. 创建 QQ 机器人

1. 在 QQ 开放平台 → QQ 机器人页面 → 创建机器人
2. 获取 **AppID** 和 **AppSecret**（注意 AppSecret 仅显示一次）
3. 在「开发管理」→「沙箱配置」中添加测试成员

### 3. 权限说明

| 权限 | Intent 值 | 说明 |
|------|-----------|------|
| 群聊 + 私聊 | `GROUP_AND_C2C` (1 << 25) | 需要申请 |
| 频道公开消息 | `PUBLIC_GUILD_MESSAGES` (1 << 30) | 默认有 |

## 配置方式

### 方式一：通过管理接口注册

```bash
# 1. 注册 Bot
curl -X POST http://localhost:8083/admin/bots \
  -H "Content-Type: application/json" \
  -d '{
    "bot_key": "qqbot-my-agent",
    "name": "我的 QQ Agent",
    "platform": "qqbot",
    "target_url": "http://localhost:4936/a2a/default/messages",
    "enabled": true,
    "platform_config": {
      "app_id": "你的AppID",
      "client_secret": "你的AppSecret"
    }
  }'

# 2. 重启服务使 WebSocket 连接生效
```

### 方式二：通过数据库直接配置

在 `chatbots` 表中插入记录：

| 字段 | 值 |
|------|------|
| bot_key | `qqbot-my-agent`（自定义唯一标识） |
| platform | `qqbot` |
| target_url | AgentStudio 的 A2A 地址 |
| platform_config | `{"app_id": "xxx", "client_secret": "xxx"}` |
| enabled | `true` |

## 消息支持

| 消息类型 | 入站（接收） | 出站（发送） |
|----------|:---:|:---:|
| 文本 | ✅ | ✅ |
| 图片 | ✅（URL） | 🔜 计划中 |
| @消息（群聊） | ✅ | - |
| C2C 私聊 | ✅ | ✅ |
| 群聊消息 | ✅ | ✅ |
| 频道消息 | ✅ | ✅ |
| 语音/视频/文件 | 🔜 计划中 | 🔜 计划中 |

## 消息映射

| QQ 概念 | AS-Dispatcher 概念 |
|---------|-------------------|
| `user_openid` | `user_id` (effective_user) |
| `group_openid` | `chat_id` = `group:{group_openid}` |
| `channel_id` | `chat_id` = `channel:{channel_id}` |
| C2C 私聊 | `chat_type` = `direct` |
| 群聊 @消息 | `chat_type` = `group` |
| `message_id` | `message_id`（去重 + 被动回复） |

## 与其他平台的差异

| 特性 | 企微 | QQ Bot |
|------|------|--------|
| 接入方式 | HTTP Webhook 回调 | WebSocket 长连接 |
| Bot 标识 | webhook URL 中的 key | AppID |
| 鉴权 | Webhook 签名 | AccessToken (OAuth) |
| 消息发送 | fly-pigeon SDK | QQ Bot HTTP API |
| 消息格式 | text / markdown | text / markdown |

## 开发调试

### 日志

QQ Bot 相关日志带 `[qqbot]` 前缀：

```
[qqbot] Starting QQ Bot: appId=xxx
[qqbot-gw] Connecting to wss://...
[qqbot-gw] Hello received, heartbeat interval: 41.25s
[qqbot-gw] Ready, session_id=xxx
[qqbot] 消息已发送: c2c:xxx, parts=1
```

### 常见问题

1. **连接后无法收到消息**：检查 QQ 开放平台的沙箱配置，确保测试用户已添加
2. **Token 获取失败**：确认 AppID 和 AppSecret 正确，且 QQ 开放平台账号状态正常
3. **群聊收不到消息**：QQ 开放平台目前仅支持群聊 @消息和 C2C 私聊，不支持群聊普通消息监听

## 参考资料

- [QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/)
- [QQ 开放平台](https://q.qq.com/)
- [@sliverp/qqbot OpenClaw 插件](https://github.com/sliverp/qqbot)（TypeScript 实现参考）
