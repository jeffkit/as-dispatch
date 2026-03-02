"""
as-dispatch MCP Server

为 AgentStudio meta-agent 提供企微 Bot 管理工具。
通过 HTTP 调用 as-dispatch 的 /admin/bots API，使用 X-Admin-Key 鉴权
（与 as-enterprise ConfigSyncService 保持一致的 Header 命名）。

启动方式（stdio，供 MCP 客户端调用）：
    AS_DISPATCH_URL=http://hitl.woa.com:8083 AS_ADMIN_KEY=<secret> \\
        uv run python -m forward_service.mcp_server

环境变量：
    AS_DISPATCH_URL  as-dispatch 服务地址（默认 http://localhost:8083）
    AS_ADMIN_KEY     admin API key，与 as-dispatch 服务端 AS_ADMIN_KEY 保持一致（必填）
"""

import os
import httpx
from fastmcp import FastMCP

AS_DISPATCH_URL = os.getenv("AS_DISPATCH_URL", "http://localhost:8083").rstrip("/")
AS_ADMIN_KEY = os.getenv("AS_ADMIN_KEY", "")

mcp = FastMCP(
    name="as-dispatch",
    instructions=(
        "Tools for managing WeCom (企业微信) bots in as-dispatch. "
        "Use these tools to create, query, and update bot configurations "
        "when setting up IM integration for AgentStudio agents."
    ),
)


def _admin_headers() -> dict:
    """构造 admin API 请求头，X-Admin-Key 与 as-enterprise 保持一致"""
    return {
        "Content-Type": "application/json",
        "X-Admin-Key": AS_ADMIN_KEY,
    }


@mcp.tool
async def create_wecom_bot(
    bot_key: str,
    name: str,
    target_url: str,
    api_key: str,
    owner_id: str,
    description: str = "",
    timeout: int = 300,
    access_mode: str = "allow_all",
) -> dict:
    """
    在 as-dispatch 创建企微 Bot 配置。

    Args:
        bot_key:     从企微机器人 Webhook URL 中提取的 key 值
                     (e.g. "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        name:        Bot 名称（如 "my-project-agent"）
        target_url:  AgentStudio A2A 端点 URL
                     (e.g. "https://my-agent.agentstudio.woa.com/a2a/<agentId>/messages")
        api_key:     AgentStudio A2A API Key (agt_proj_xxx_yyy)
        owner_id:    创建者标识，填写 AgentStudio 用户信息或 "meta-agent"
        description: Bot 描述（可选）
        timeout:     转发超时秒数（默认 300）
        access_mode: 访问控制模式："allow_all" / "whitelist" / "blacklist"

    Returns:
        {"success": bool, "bot": {...}} 或 {"success": false, "error": "..."}
    """
    payload = {
        "bot_key": bot_key,
        "name": name,
        "target_url": target_url,
        "api_key": api_key,
        "owner_id": owner_id,
        "description": description,
        "timeout": timeout,
        "access_mode": access_mode,
        "enabled": True,
        "platform": "wecom",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{AS_DISPATCH_URL}/admin/bots",
            json=payload,
            headers=_admin_headers(),
        )
        response.raise_for_status()
        return response.json()


@mcp.tool
async def get_wecom_bot(bot_key: str) -> dict:
    """
    查询企微 Bot 配置详情。

    Args:
        bot_key: 企微机器人的 key 值

    Returns:
        {"success": bool, "bot": {...}} 或 {"success": false, "error": "..."}
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{AS_DISPATCH_URL}/admin/bots/{bot_key}",
            headers=_admin_headers(),
        )
        response.raise_for_status()
        return response.json()


@mcp.tool
async def list_wecom_bots() -> dict:
    """
    列出 as-dispatch 中所有已配置的企微 Bot。

    Returns:
        {"success": bool, "bots": [...], "total": int}
    """
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{AS_DISPATCH_URL}/admin/bots",
            headers=_admin_headers(),
        )
        response.raise_for_status()
        return response.json()


@mcp.tool
async def update_wecom_bot(
    bot_key: str,
    target_url: str | None = None,
    api_key: str | None = None,
    name: str | None = None,
    timeout: int | None = None,
    enabled: bool | None = None,
) -> dict:
    """
    更新企微 Bot 配置。只传入需要修改的字段。

    Args:
        bot_key:    企微机器人的 key 值（必填，用于定位 bot）
        target_url: 新的 A2A 端点 URL（可选）
        api_key:    新的 API Key（可选）
        name:       新的 Bot 名称（可选）
        timeout:    新的超时秒数（可选）
        enabled:    是否启用（可选）

    Returns:
        {"success": bool, "bot": {...}} 或 {"success": false, "error": "..."}
    """
    payload = {
        k: v for k, v in {
            "target_url": target_url,
            "api_key": api_key,
            "name": name,
            "timeout": timeout,
            "enabled": enabled,
        }.items() if v is not None
    }

    if not payload:
        return {"success": False, "error": "未提供任何需要更新的字段"}

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.put(
            f"{AS_DISPATCH_URL}/admin/bots/{bot_key}",
            json=payload,
            headers=_admin_headers(),
        )
        response.raise_for_status()
        return response.json()


def main():
    """以 stdio 模式运行 MCP 服务"""
    if not AS_ADMIN_KEY:
        raise RuntimeError(
            "AS_ADMIN_KEY 环境变量未设置，MCP 服务无法启动"
        )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
