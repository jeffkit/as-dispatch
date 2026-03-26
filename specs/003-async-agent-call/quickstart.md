# Quickstart: 003-async-agent-call

**面向**: 实现工程师  
**目的**: 最快速地理解本特性并开始开发

---

## 一句话摘要

将企微 → Agent 的调用从"同步等待（最长 30 分钟）"改为"即时确认 + 后台异步执行 + 结果回推"，解决 WeChat Work 3 秒回调超时问题。

---

## 关键文件

```
specs/003-async-agent-call/
├── spec.md                          # 用户故事 + FR + SC（需求来源）
├── research.md                      # 技术决策和权衡分析
├── data-model.md                    # AsyncAgentTask 模型 + Chatbot 新字段
├── contracts/internal-async-interface.md  # 模块接口契约
├── plan.md                          # 实现计划（本文档的父文档）
└── quickstart.md                    # 本文件
```

---

## 开发前必读

1. **`data-model.md`** — 了解 `AsyncAgentTask` 模型和状态机（5 分钟）
2. **`contracts/internal-async-interface.md`**中的 Section 1 — 了解 `AsyncTaskService` 的 3 个核心方法（5 分钟）
3. **`forward_service/services/forwarder.py`** — 了解现有的 `forward_to_agent_with_user_project()` 接口，异步执行器将直接调用它（5 分钟）

---

## 开发顺序

```
Phase 1 (DB)  →  Phase 2 (Repository)  →  Phase 3 (Executor)
→  Phase 4 (Callback)  →  Phase 5 (Admin API)  →  Phase 6 (Test)
```

每个 Phase 结束后可独立验证，不必等待后续 Phase。

---

## 最重要的设计约束

1. **`async_mode` 默认 `False`**: 新代码对现有 bot 零影响
2. **直接复用 `forward_to_agent_with_user_project()`**: 不重写 Agent 调用逻辑
3. **`asyncio.Semaphore`**: 防止并发任务耗尽 DB 连接池（默认限制 10 个）
4. **`asyncio.wait_for()`**: 任务超时控制，不用 `time.sleep()`（P3 合规）
5. **fly-pigeon 可能是同步库**: 需确认，若是则用 `asyncio.to_thread()` 包裹

---

## 快速本地测试

```bash
cd platform/as-dispatch

# 1. 应用 migration
alembic upgrade head

# 2. 启动服务
uv run python -m forward_service.app

# 3. 通过 Admin API 为某个 bot 启用 async_mode
curl -X PATCH http://localhost:8083/api/admin/bots/{bot_key} \
  -H "X-Api-Key: your-key" \
  -d '{"async_mode": true}'

# 4. 模拟 WeChat 回调，验证 <3s 返回
curl -X POST http://localhost:8083/callback \
  -H "Content-Type: application/json" \
  -d '{
    "chatid": "test_chat",
    "chattype": "single",
    "msgtype": "text",
    "text": {"content": "测试消息"},
    "from": {"userid": "test_user", "name": "Test"},
    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={bot_key}"
  }'
# 预期: 响应时间 < 3s，用户侧收到"正在处理"消息

# 5. 查看任务状态
curl http://localhost:8083/api/admin/async-tasks \
  -H "X-Api-Key: your-key"
```
