"""
隧道命令处理

处理用户的隧道管理斜杠命令：
- /tunnel create <domain> - 创建隧道
- /tunnels - 列出我的隧道
- /tunnel delete <domain> - 删除隧道
- /tunnel status - 查看隧道连接状态
- /tunnel token <domain> - 获取隧道 token
"""
import logging
import re
from typing import Tuple

from ..tunnel import get_tunnel_server

logger = logging.getLogger(__name__)


# ============== 命令正则匹配 ==============

TUNNEL_CREATE_RE = re.compile(
    r'^/tunnel\s+create\s+([a-zA-Z0-9][-a-zA-Z0-9]{0,62})'  # domain
    r'(?:\s+--name\s+(.+?))?$',  # optional: name
    re.IGNORECASE
)

TUNNEL_LIST_RE = re.compile(
    r'^/(?:tunnels?|tl)\s*$',
    re.IGNORECASE
)

TUNNEL_DELETE_RE = re.compile(
    r'^/tunnel\s+(?:delete|rm)\s+([a-zA-Z0-9][-a-zA-Z0-9]{0,62})$',
    re.IGNORECASE
)

TUNNEL_STATUS_RE = re.compile(
    r'^/tunnel\s+status\s*$',
    re.IGNORECASE
)

TUNNEL_TOKEN_RE = re.compile(
    r'^/tunnel\s+token\s+([a-zA-Z0-9][-a-zA-Z0-9]{0,62})$',
    re.IGNORECASE
)


# ============== 命令处理函数 ==============

async def handle_tunnel_create(domain: str, name: str | None = None) -> Tuple[bool, str]:
    """
    处理 /tunnel create 命令
    
    用法: /tunnel create <domain> [--name <name>]
    
    示例:
    /tunnel create my-agent
    /tunnel create my-agent --name "我的本地Agent"
    """
    try:
        tunnel_server = get_tunnel_server()
        
        if not tunnel_server.db:
            return False, "❌ 隧道服务未初始化"
        
        from tunely.repository import TunnelRepository
        
        async with tunnel_server.db.session() as session:
            repo = TunnelRepository(session)
            
            # 检查域名是否已存在
            existing = await repo.get_by_domain(domain)
            if existing:
                return False, f"❌ 域名 `{domain}` 已被占用\n\n💡 请尝试其他名称，如 `{domain}-2` 或 `my-{domain}`"
            
            # 创建隧道
            tunnel = await repo.create(
                domain=domain,
                name=name,
            )
            
            # 构建成功响应
            lines = [
                "🎉 **隧道创建成功！**",
                "",
                f"📦 域名: `{domain}.tunnel`",
            ]
            
            if name:
                lines.append(f"📛 名称: {name}")
            
            lines.extend([
                "",
                f"🔑 **Token**: `{tunnel.token}`",
                "",
                "---",
                "",
                "📋 **在本地启动隧道**",
                "",
                "1️⃣ 安装客户端",
                "```",
                "pip install tunely",
                "```",
                "",
                "2️⃣ 启动隧道",
                "```",
                f"tunely connect \\",
                f"  --server wss://YOUR_SERVER/ws/tunnel \\",
                f"  --token {tunnel.token} \\",
                f"  --target http://localhost:8080",
                "```",
                "",
                "3️⃣ 添加项目配置",
                "```",
                f"/ap my-project http://{domain}.tunnel/api/chat",
                "```",
                "",
                "💡 看到 \"✅ 隧道已连接\" 后，发消息开始对话！",
            ])
            
            return True, "\n".join(lines)
            
    except Exception as e:
        logger.error(f"创建隧道失败: {e}", exc_info=True)
        return False, f"❌ 创建隧道失败: {str(e)}"


async def handle_tunnel_list() -> Tuple[bool, str]:
    """
    处理 /tunnels 命令
    
    列出所有隧道及其状态
    """
    try:
        tunnel_server = get_tunnel_server()
        
        if not tunnel_server.db:
            return False, "❌ 隧道服务未初始化"
        
        from tunely.repository import TunnelRepository
        
        async with tunnel_server.db.session() as session:
            repo = TunnelRepository(session)
            tunnels = await repo.list_all()
            
            if not tunnels:
                return True, "📭 暂无隧道\n\n💡 使用 `/tunnel create <域名>` 创建第一个隧道"
            
            lines = ["📊 **隧道列表**\n"]
            
            for t in tunnels:
                is_connected = tunnel_server.manager.is_connected(t.domain)
                status_icon = "✅" if is_connected else "⚫"
                status_text = "在线" if is_connected else "离线"
                
                lines.append(f"{status_icon} `{t.domain}.tunnel` - {status_text}")
                
                if t.name:
                    lines.append(f"   📛 {t.name}")
                
                lines.append(f"   📈 请求数: {t.total_requests}")
                lines.append("")
            
            lines.append("---")
            lines.append("💡 用法:")
            lines.append("  `/tunnel create <域名>` - 创建隧道")
            lines.append("  `/tunnel token <域名>` - 获取 Token")
            lines.append("  `/tunnel delete <域名>` - 删除隧道")
            
            return True, "\n".join(lines)
            
    except Exception as e:
        logger.error(f"列出隧道失败: {e}", exc_info=True)
        return False, f"❌ 获取隧道列表失败: {str(e)}"


async def handle_tunnel_delete(domain: str) -> Tuple[bool, str]:
    """
    处理 /tunnel delete 命令
    
    用法: /tunnel delete <domain>
    """
    try:
        tunnel_server = get_tunnel_server()
        
        if not tunnel_server.db:
            return False, "❌ 隧道服务未初始化"
        
        from tunely.repository import TunnelRepository
        
        async with tunnel_server.db.session() as session:
            repo = TunnelRepository(session)
            
            # 检查隧道是否存在
            tunnel = await repo.get_by_domain(domain)
            if not tunnel:
                return False, f"❌ 隧道 `{domain}` 不存在"
            
            # 删除隧道
            deleted = await repo.delete(domain)
            
            if deleted:
                return True, f"✅ 隧道 `{domain}.tunnel` 已删除"
            else:
                return False, "❌ 删除隧道失败"
            
    except Exception as e:
        logger.error(f"删除隧道失败: {e}", exc_info=True)
        return False, f"❌ 删除失败: {str(e)}"


async def handle_tunnel_status() -> Tuple[bool, str]:
    """
    处理 /tunnel status 命令
    
    显示当前在线的隧道连接
    """
    try:
        tunnel_server = get_tunnel_server()
        connected_domains = tunnel_server.manager.list_connected_domains()
        
        if not connected_domains:
            return True, "📭 当前没有在线的隧道\n\n💡 在本地运行 `tunely connect` 建立连接"
        
        lines = [
            f"📊 **在线隧道** ({len(connected_domains)} 个)\n"
        ]
        
        for domain in connected_domains:
            lines.append(f"✅ `{domain}.tunnel`")
        
        return True, "\n".join(lines)
        
    except Exception as e:
        logger.error(f"获取隧道状态失败: {e}", exc_info=True)
        return False, f"❌ 获取状态失败: {str(e)}"


async def handle_tunnel_token(domain: str) -> Tuple[bool, str]:
    """
    处理 /tunnel token 命令
    
    获取隧道的连接 Token
    
    用法: /tunnel token <domain>
    """
    try:
        tunnel_server = get_tunnel_server()
        
        if not tunnel_server.db:
            return False, "❌ 隧道服务未初始化"
        
        from tunely.repository import TunnelRepository
        
        async with tunnel_server.db.session() as session:
            repo = TunnelRepository(session)
            tunnel = await repo.get_by_domain(domain)
            
            if not tunnel:
                return False, f"❌ 隧道 `{domain}` 不存在"
            
            lines = [
                f"🔑 **隧道 Token**",
                "",
                f"📦 域名: `{domain}.tunnel`",
                f"🔑 Token: `{tunnel.token}`",
                "",
                "📋 **使用方式**",
                "```",
                f"tunely connect --token {tunnel.token} --target http://localhost:8080",
                "```",
            ]
            
            return True, "\n".join(lines)
            
    except Exception as e:
        logger.error(f"获取隧道 Token 失败: {e}", exc_info=True)
        return False, f"❌ 获取 Token 失败: {str(e)}"


# ============== 命令分发 ==============

def is_tunnel_command(message: str) -> bool:
    """
    判断消息是否是隧道命令
    
    Returns:
        True 如果是隧道命令
    """
    message = message.strip()
    
    return bool(
        TUNNEL_CREATE_RE.match(message) or
        TUNNEL_LIST_RE.match(message) or
        TUNNEL_DELETE_RE.match(message) or
        TUNNEL_STATUS_RE.match(message) or
        TUNNEL_TOKEN_RE.match(message)
    )


async def handle_tunnel_command(message: str) -> Tuple[bool, str]:
    """
    处理隧道命令
    
    Args:
        message: 消息内容
        
    Returns:
        (success, response_message)
    """
    message = message.strip()
    
    # /tunnel create
    match = TUNNEL_CREATE_RE.match(message)
    if match:
        domain = match.group(1)
        name = match.group(2) if match.lastindex >= 2 else None
        return await handle_tunnel_create(domain, name)
    
    # /tunnels 或 /tunnel
    if TUNNEL_LIST_RE.match(message):
        return await handle_tunnel_list()
    
    # /tunnel delete
    match = TUNNEL_DELETE_RE.match(message)
    if match:
        domain = match.group(1)
        return await handle_tunnel_delete(domain)
    
    # /tunnel status
    if TUNNEL_STATUS_RE.match(message):
        return await handle_tunnel_status()
    
    # /tunnel token
    match = TUNNEL_TOKEN_RE.match(message)
    if match:
        domain = match.group(1)
        return await handle_tunnel_token(domain)
    
    return False, "❌ 未知的隧道命令\n\n💡 用法:\n  `/tunnel create <域名>` - 创建隧道\n  `/tunnels` - 列出隧道"
