# AgentStudio Dispatch

企业微信消息转发服务 + WebSocket 隧道管理

## 功能特性

### 消息转发服务

- 📨 **双向消息转发** - 企微消息转发到外部服务，外部服务回复自动发送到企微
- 🤖 **多机器人管理** - 支持配置多个企微机器人
- 🔐 **访问控制** - 黑白名单机制，精确控制访问权限
- 📊 **请求日志** - 完整记录转发历史，便于追踪和调试
- ⚙️ **灵活配置** - JSON 文件或数据库存储，支持热更新
- 🎯 **项目管理** - 用户可创建项目，配置独立的转发规则
- 💬 **斜杠命令** - 通过企微消息直接管理 Bot 和项目

### WebSocket 隧道

- 🚇 **内网穿透** - 让外网访问内网服务
- 🔑 **Token 认证** - 安全的隧道连接
- 📈 **请求统计** - 实时监控隧道流量
- 📋 **请求日志** - 记录所有通过隧道的请求
- 🎛️ **管理控制台** - Web UI 管理隧道

---

## 项目结构

```
as-dispatch/
├── forward_service/      # 转发服务代码
│   ├── app.py           # 主应用
│   ├── config.py        # 配置管理
│   ├── routes/          # API 路由
│   ├── models.py        # 数据模型
│   └── tunnel.py        # 隧道集成
├── tunely/              # Tunely submodule (WebSocket 隧道)
├── tests/               # 测试
├── alembic/             # 数据库迁移
└── scripts/             # 工具脚本
```

---

## 快速开始

### 安装依赖

```bash
# 初始化 submodule
git submodule update --init --recursive

# 安装依赖
uv sync
```

### 运行服务

```bash
# 启动转发服务（默认端口 8083）
uv run python -m forward_service.app

# 使用数据库模式
USE_DATABASE=true uv run python -m forward_service.app

# 指定端口
FORWARD_PORT=8084 uv run python -m forward_service.app
```

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `FORWARD_PORT` | 服务端口 | `8083` |
| `USE_DATABASE` | 启用数据库模式 | `false` |
| `DATABASE_URL` | 数据库连接字符串 | SQLite |
| `DEFAULT_BOT_KEY` | 默认 Bot Key | - |

---

## 配置方式

### JSON 文件模式（默认）

配置文件：`data/forward_bots.json`

```json
{
  "default_bot_key": "bot1",
  "bots": {
    "bot1": {
      "bot_key": "bot1",
      "name": "测试机器人",
      "forward_config": {
        "url_template": "https://api.example.com/chat"
      },
      "access_mode": "whitelist",
      "whitelist": ["user1", "user2"],
      "enabled": true
    }
  }
}
```

### 数据库模式

```bash
# 启用数据库
export USE_DATABASE=true

# MySQL（推荐生产环境）
export DATABASE_URL="mysql+pymysql://user:pass@host:port/db"

# SQLite（开发/测试）
export DATABASE_URL="sqlite+aiosqlite:///./data/forward_service.db"

# 运行迁移
alembic upgrade head

# 启动服务
uv run python -m forward_service.app
```

---

## 斜杠命令

用户可以通过企微消息直接管理：

### Bot 管理（需要管理员权限）

```
/bots                    - 列出所有 Bot
/bot create <key>        - 创建 Bot
/bot delete <key>        - 删除 Bot
```

### 项目管理

```
/projects                - 列出我的项目
/project create <name>   - 创建项目
/ap <project> <url>      - 添加项目转发配置
/project delete <name>   - 删除项目
```

### 隧道管理

```
/tunnel create <domain>  - 创建隧道
/tunnels                 - 列出所有隧道
/tunnel token <domain>   - 获取隧道 Token
/tunnel delete <domain>  - 删除隧道
```

---

## WebSocket 隧道

### 创建隧道

```bash
# 1. 通过企微创建隧道
/tunnel create my-agent

# 2. 在本地启动隧道客户端
pip install tunely

tunely connect \
  --server wss://your-server.com/ws/tunnel \
  --token <your-token> \
  --target http://localhost:8080

# 3. 添加项目配置
/ap my-project http://my-agent.tunnel/api/chat
```

### 管理控制台

访问 `http://localhost:8083/admin/tunnels` 查看：
- 隧道列表和状态
- 请求统计
- 请求日志详情

---

## API 文档

### 转发接口

```bash
# 发送消息（触发转发）
POST /callback/{bot_key}
Content-Type: application/json

{
  "from": {
    "userid": "user123",
    "name": "张三"
  },
  "text": {
    "content": "你好"
  },
  "chatid": "group123"
}
```

### 管理接口

```bash
# 获取配置
GET /admin/config

# 更新配置
PUT /admin/config

# 查看转发日志
GET /admin/logs?limit=20
```

---

## 数据库迁移

```bash
# 查看当前版本
alembic current

# 升级到最新版本
alembic upgrade head

# 回退一个版本
alembic downgrade -1

# 生成新的迁移（修改 models.py 后）
alembic revision --autogenerate -m "描述"
```

---

## 测试

```bash
# 运行所有测试
uv run pytest

# 运行特定测试
uv run pytest tests/test_callback.py

# 运行端到端测试
uv run pytest tests/test_e2e_tunnel.py -v

# 查看覆盖率
uv run pytest --cov=forward_service
```

---

## 部署

### 使用 systemd

```ini
[Unit]
Description=AgentStudio Dispatch Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/as-dispatch
Environment="USE_DATABASE=true"
Environment="DATABASE_URL=mysql+pymysql://..."
ExecStart=/path/to/uv run python -m forward_service.app
Restart=always

[Install]
WantedBy=multi-user.target
```

### 使用 Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装 uv
RUN pip install uv

# 复制代码
COPY . .

# 初始化 submodule
RUN git submodule update --init --recursive

# 安装依赖
RUN uv sync

# 暴露端口
EXPOSE 8083

# 启动服务
CMD ["uv", "run", "python", "-m", "forward_service.app"]
```

---

## 相关项目

- **Tunely**: https://github.com/jeffkit/tunely - WebSocket 隧道框架
- **HIL-MCP**: https://git.woa.com/kongjie/tmp - Human-in-the-Loop MCP 服务

---

## License

MIT
