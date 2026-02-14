# 并发控制与群聊会话共享设计方案

> **状态**: 设计中
> **日期**: 2026-02-14
> **关联问题**: 创建 Bot 报错 (platform 字段缺失), 消息路由到错误 Bot, 并发消息导致 Agent 会话混乱

---

## 1. 背景

### 1.1 已修复的 Bug

| Bug | 原因 | 修复 |
|-----|------|------|
| 管理台创建 Bot 报错: `Field 'platform' doesn't have a default value` | `chatbots` 表的 `platform` 列 NOT NULL 无默认值，代码链路未传递 | 代码层传递 platform 字段 + DB 添加 server_default |
| @ aw-coder 收到 jarvis 的回复 | `create_bot()` 创建 Bot 后未刷新内存缓存，新 Bot 不在路由表中 | 在 `create_bot()` 后添加 `reload_config()` |

### 1.2 待解决的问题

**问题 1: 缺少并发控制**
- 用户连续发送多条消息时，所有消息同时转发给 Agent
- Agent 端同一 session 收到并发请求，可能导致会话状态混乱
- `ProcessingSession` 模型已定义但从未使用

**问题 2: 群聊会话隔离不合理**
- 当前 session key 为 `(user_id, chat_id, bot_key)`
- 群聊中每个用户有独立会话，不符合群聊协作场景
- 群聊应该是多人共享一个会话上下文

---

## 2. 系统现状梳理

### 2.1 数据模型关系

```
Chatbot (Bot 级别配置)
├── bot_key (唯一标识，来自企微 Webhook Key)
├── target_url, api_key, timeout (默认转发目标)
├── platform (wecom/slack/telegram/discord)
└── 1:N → ChatAccessRule (访问控制规则)

UserProjectConfig (用户级别转发配置，即"项目")
├── bot_key + chat_id + project_id (唯一约束)
├── url_template (转发目标 URL)
├── api_key, timeout (项目级覆盖)
├── is_default (每个 bot_key+chat_id 最多一个)
└── enabled

UserSession (会话跟踪)
├── user_id, chat_id, bot_key (联合索引)
├── session_id (Agent 返回的会话 ID)
├── short_id (session_id 前 8 位，用于 /change 命令)
├── current_project_id (当前项目)
├── is_active (是否为活跃会话)
└── message_count, last_message

ProcessingSession (并发锁 — 已定义，未使用)
├── session_key (唯一约束，充当分布式锁)
├── user_id, chat_id, bot_key
├── message (正在处理的消息)
└── started_at (用于超时清理)
```

### 2.2 转发优先级链

```
消息到达 → 获取活跃会话 → 提取 current_project_id
    ↓
[优先级 1] 会话指定的项目 (current_project_id)
    ↓ 未找到/未启用
[优先级 2] 用户默认项目 (is_default=True)
    ↓ 无默认
[优先级 3] 智能选择 (唯一项目自动选中 / 多项目取第一个)
    ↓ 无项目
[优先级 4] Bot 默认配置 (Chatbot.target_url)
    ↓ 无配置
[错误] 返回帮助信息
```

### 2.3 现有会话命令

| 命令 | 快捷 | 功能 |
|------|------|------|
| `/sess` | `/s` | 列出会话列表 |
| `/reset` | `/r` | 重置当前会话（创建新会话） |
| `/change <id>` | `/c <id>` | 切换到指定会话 |
| `/add-project` | `/ap` | 添加转发项目 |
| `/list-projects` | `/lp` | 列出所有项目 |
| `/use <id>` | `/u <id>` | 切换项目 |
| `/current-project` | `/cp` | 查看当前项目 |
| `/remove-project` | `/rp` | 删除项目 |

### 2.4 消息路由流程

```
WeChat 回调 → POST /callback
    ↓
提取 webhook_url → 提取 bot_key → 查找 Bot 配置
    ↓
(内存缓存 config.bots 字典, get_bot_or_default)
    ↓
检查访问控制 → 解析内容/命令 → 获取活跃会话
    ↓
转发到 Agent (forward_to_agent_with_user_project)
    ↓
发送回复 → 记录会话
```

---

## 3. 设计方案

### 3.1 并发控制

#### 3.1.1 核心原则

- **同一个 Agent 会话 (session_id) 的请求必须串行处理**
- **不同会话之间可以并行**
- **使用数据库级别的互斥锁**，支持未来多实例部署

#### 3.1.2 ProcessingSession 锁机制

**锁的粒度: session_id 级别**

```python
# 计算 session_key 的策略
def compute_processing_key(session_id, user_id, chat_id, bot_key, chat_type):
    if session_id:
        # 已有会话：锁定具体的 Agent 会话
        return session_id
    else:
        # 新会话：按用户/群维度锁定，防止同时创建多个新会话
        if chat_type == "group":
            return f"{chat_id}:{bot_key}"
        else:
            return f"{user_id}:{bot_key}"
```

**加锁流程:**

```
收到消息
    ↓
查找活跃会话 → 获取 session_id
    ↓
计算 processing_key
    ↓
try: INSERT INTO processing_sessions (session_key=processing_key, ...)
    ↓
成功 → 继续处理 → 完成后 DELETE
    ↓
失败 (Unique Violation) → 检查 started_at
    ├── 超时 (> 5分钟) → DELETE 旧记录 → 重试 INSERT
    └── 未超时 → 回复 "⏳ 前一条消息正在处理中，请稍候..."
```

**超时清理:**
- 服务启动时清理所有 `started_at > 5分钟` 的记录
- 定期清理（每 60 秒检查一次）
- 超时阈值: 5 分钟（可配置）

#### 3.1.3 实现细节

**新增 `ProcessingSessionRepository`:**

```python
class ProcessingSessionRepository:
    async def try_acquire(self, session_key, user_id, chat_id, bot_key, message) -> bool:
        """尝试获取锁，成功返回 True"""
        
    async def release(self, session_key) -> bool:
        """释放锁"""
        
    async def is_locked(self, session_key) -> tuple[bool, Optional[ProcessingSession]]:
        """检查是否已锁定"""
        
    async def cleanup_stale(self, timeout_seconds=300) -> int:
        """清理超时的锁"""
```

**callback.py 修改:**

```python
# 在转发前
processing_key = compute_processing_key(current_session_id, ...)
acquired = await processing_repo.try_acquire(processing_key, ...)

if not acquired:
    # 检查是否超时
    is_locked, lock_info = await processing_repo.is_locked(processing_key)
    if is_locked and lock_info:
        elapsed = (now - lock_info.started_at).total_seconds()
        if elapsed > PROCESSING_TIMEOUT:
            await processing_repo.release(processing_key)
            acquired = await processing_repo.try_acquire(processing_key, ...)
    
    if not acquired:
        await send_reply("⏳ 前一条消息正在处理中，请稍候...")
        return

try:
    result = await forward_to_agent_with_user_project(...)
finally:
    await processing_repo.release(processing_key)
```

### 3.2 群聊会话共享

#### 3.2.1 核心变更

**群聊中，所有用户共享同一个会话上下文**

| 场景 | 会话查找条件 | 说明 |
|------|-------------|------|
| 私聊 | `user_id + chat_id + bot_key` | 不变，等同于 `user_id + bot_key` |
| 群聊 | `chat_id + bot_key` (忽略 user_id) | **变更**: 所有人共享 |

#### 3.2.2 session_manager.py 修改

**引入 "effective_user" 概念:**

```python
def get_effective_user(user_id: str, chat_id: str, chat_type: str) -> str:
    """
    获取会话的有效用户标识
    
    群聊: 返回 chat_id (所有人共享)
    私聊: 返回 user_id (个人独立)
    """
    if chat_type == "group":
        return chat_id  # 群内所有人共用
    return user_id  # 私聊按用户隔离
```

**受影响的方法:**
- `get_active_session(effective_user, chat_id, bot_key)` — 群聊时 effective_user = chat_id
- `record_session(effective_user, chat_id, bot_key, ...)` — 同上
- `list_sessions(effective_user, chat_id, bot_key)` — 同上
- `reset_session(effective_user, chat_id, bot_key)` — 同上
- `change_session(effective_user, chat_id, short_id, bot_key)` — 同上

#### 3.2.3 callback.py 修改

在消息处理流程的早期阶段计算 `effective_user`：

```python
# 确定 effective_user
effective_user = get_effective_user(from_user_id, chat_id, chat_type)

# 后续所有 session_mgr 调用统一使用 effective_user
active_session = await session_mgr.get_active_session(effective_user, chat_id, bot.bot_key)
```

### 3.3 转发时包含发送者信息

在群聊共享会话场景下，Agent 需要知道当前消息的发送者。

**修改转发请求体:**

```python
request_body = {
    "message": content,
    "sessionId": session_id,
    # 新增: 发送者上下文
    "metadata": {
        "from_user": from_user_name,
        "from_user_id": from_user_id,
        "chat_type": chat_type,  # "group" / "single"
        "chat_id": chat_id
    }
}
```

> 注意: 这取决于 Agent 端 (AgentStudio) 是否支持此字段。如果 Agent 端暂不支持，此修改可以延后，不影响核心功能。

---

## 4. 改动文件清单

| 文件 | 改动 | 优先级 |
|------|------|--------|
| `forward_service/repository.py` | 新增 `ProcessingSessionRepository` | P0 |
| `forward_service/session_manager.py` | 添加 `get_effective_user()`, 修改所有 session 方法 | P0 |
| `forward_service/routes/callback.py` | 集成并发锁 + effective_user | P0 |
| `forward_service/app.py` | 启动时清理过期锁 | P1 |
| `forward_service/services/forwarder.py` | 转发时添加发送者 metadata | P2 |
| `forward_service/routes/admin_commands.py` | 更新 session_key 生成逻辑 | P1 |

---

## 5. TODO

- [ ] **P0**: 实现 ProcessingSessionRepository (基于 DB 的并发锁)
- [ ] **P0**: 修改 session_manager 支持群聊共享会话 (effective_user)
- [ ] **P0**: 在 callback.py 中集成并发锁
- [ ] **P1**: 服务启动时清理过期的 processing_sessions
- [ ] **P1**: 更新 admin_commands.py 中的 session_key 逻辑
- [ ] **P2**: 转发请求中添加发送者 metadata
- [ ] **P2**: 为群聊命令添加显示"当前活跃会话的发送者"
- [ ] **FUTURE**: 多实例部署前评估是否需要更强的分布式锁机制（当前 DB unique constraint 已具备分布式能力）

---

## 6. 测试计划

### 6.1 并发控制测试
1. 私聊: 快速连发 2 条消息 → 第 2 条应提示等待
2. 私聊: 会话 A 处理中，/change 到会话 B 发消息 → 应可并行
3. 私聊: 会话 A 处理完，再发消息 → 应正常处理
4. 锁超时: 模拟处理超过 5 分钟 → 新消息应清理旧锁并继续

### 6.2 群聊共享会话测试
5. 群聊: 用户 A 发消息创建会话 → 用户 B 发消息 → 应复用同一 session_id
6. 群聊: 用户 A 发消息处理中 → 用户 B 发消息 → 第 2 条应提示等待
7. 群聊: /sess 显示的是群共享会话，不是个人会话

### 6.3 兼容性测试
8. 私聊行为不变: 会话仍按 user_id 隔离
9. 命令兼容: /sess, /reset, /change 在群聊中正常工作
10. 项目命令: /ap, /use, /lp 在群聊中正常工作
