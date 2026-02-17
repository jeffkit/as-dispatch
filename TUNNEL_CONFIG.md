# Tunely Server 配置说明

Forward Service 内嵌了 Tunely Server，支持通过 WebSocket 隧道转发 HTTP 请求。

## 配置方式

支持两种配置方式，优先级从高到低：

### 1. 环境变量（优先级最高）

```bash
export TUNNEL_DOMAIN="tunnel"
export TUNNEL_WS_URL="ws://21.6.243.90:80/ws/tunnel"
export TUNNEL_ADMIN_API_KEY="your-admin-api-key"
export WS_TUNNEL_INSTRUCTION="接入须知说明"
export TUNNEL_JWT_SECRET="your-jwt-shared-secret"
```

### 2. JSON 配置文件（推荐）

默认配置文件路径：`data/tunnel_config.json`

可通过环境变量指定其他路径：

```bash
export TUNNEL_CONFIG_FILE="/path/to/tunnel_config.json"
```

**配置文件示例：**

```json
{
  "ws_path": "/ws/tunnel",
  "domain": "tunnel",
  "ws_url": "ws://21.6.243.90:80/ws/tunnel",
  "admin_api_key": null,
  "instruction": "腾讯司内的 .tunnel 隧道域名仅用于企微接入的回调用，暂不支持直接通过隧道域名访问。如需在企微内接入，请在群内添加 Agent Studio 机器人，私信它获取接入指南，或详询 @kongjie",
  "jwt_secret": null
}
```

## 配置项说明

| 配置项 | 说明 | 默认值 | 环境变量 |
|-------|------|--------|---------|
| `ws_path` | WebSocket 路径 | `/ws/tunnel` | - |
| `domain` | 隧道域名后缀 | `tunnel` | `TUNNEL_DOMAIN` |
| `ws_url` | WebSocket 完整 URL | `ws://21.6.243.90:80/ws/tunnel` | `TUNNEL_WS_URL` |
| `admin_api_key` | 管理 API 密钥 | `null` | `TUNNEL_ADMIN_API_KEY` |
| `instruction` | 接入须知说明 | `null` | `WS_TUNNEL_INSTRUCTION` |
| `jwt_secret` | JWT 共享密钥（设置后创建隧道需要 Bearer JWT 认证） | `null` | `TUNNEL_JWT_SECRET` |

## 使用建议

1. **开发环境**：使用 JSON 配置文件，方便修改和共享
2. **生产环境**：JSON 配置文件 + 环境变量覆盖敏感信息（如 API Key）

## 修改配置后

修改 JSON 配置文件后，需要重启 Forward Service：

```bash
sudo systemctl restart forward-service
```

## 查看配置是否生效

访问 `/api/info` 接口查看当前配置：

```bash
curl http://localhost:8083/api/info
```

如果配置了 `instruction`，将在返回结果中看到：

```json
{
  "name": "Tunely Server",
  "version": "0.2.1",
  "domain": {...},
  "websocket": {...},
  "protocols": [...],
  "auth": {
    "required": true,
    "type": "bearer"
  },
  "instruction": "你的须知内容"
}
```
