"""
隧道服务集成模块

将 tunely TunnelServer 集成到 Forward Service 中，支持：
- 通过 WebSocket 建立隧道连接
- 通过隧道转发 HTTP 请求到内网 Agent
- 企微命令管理隧道
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

from tunely import TunnelServer, TunnelServerConfig

logger = logging.getLogger(__name__)


def load_tunnel_config() -> dict:
    """
    加载隧道服务器配置
    
    优先级（从高到低）：
    1. 环境变量
    2. JSON 配置文件 (TUNNEL_CONFIG_FILE 指定的路径，或默认 data/tunnel_config.json)
    3. 默认值
    
    Returns:
        配置字典
    """
    config = {
        "ws_path": "/ws/tunnel",
        "domain": "tunnel",
        "ws_url": "ws://21.6.243.90:80/ws/tunnel",
        "admin_api_key": None,
        "instruction": None,
        "jwt_secret": None,
    }
    
    # 1. 尝试从 JSON 文件加载
    config_file = os.getenv("TUNNEL_CONFIG_FILE", "data/tunnel_config.json")
    config_path = Path(config_file)
    
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                json_config = json.load(f)
                config.update(json_config)
                logger.info(f"已从 JSON 文件加载隧道配置: {config_path}")
        except Exception as e:
            logger.warning(f"加载隧道配置文件失败: {e}")
    
    # 2. 环境变量覆盖（优先级最高）
    if domain := os.getenv("TUNNEL_DOMAIN"):
        config["domain"] = domain
    if ws_url := os.getenv("TUNNEL_WS_URL"):
        config["ws_url"] = ws_url
    if admin_api_key := os.getenv("TUNNEL_ADMIN_API_KEY") or os.getenv("WS_TUNNEL_ADMIN_API_KEY"):
        config["admin_api_key"] = admin_api_key
    if instruction := os.getenv("WS_TUNNEL_INSTRUCTION"):
        config["instruction"] = instruction
    if jwt_secret := os.getenv("TUNNEL_JWT_SECRET"):
        config["jwt_secret"] = jwt_secret
    
    return config


# 加载配置
tunnel_config = load_tunnel_config()

# 全局隧道服务器实例（配置后才初始化数据库）
# 使用固定的 ws_path 创建，这样 router 在模块加载时就可以注册
tunnel_server: TunnelServer = TunnelServer(
    config=TunnelServerConfig(
        ws_path=tunnel_config["ws_path"],
        domain=tunnel_config["domain"],
        ws_url=tunnel_config["ws_url"],
        admin_api_key=tunnel_config["admin_api_key"],
        instruction=tunnel_config["instruction"],
        jwt_secret=tunnel_config["jwt_secret"],
    )
)

# 隧道域名后缀（用于识别隧道请求）
TUNNEL_DOMAIN_SUFFIX = ".tunnel"


async def init_tunnel_server(database_url: str) -> None:
    """
    初始化隧道服务器的数据库连接
    
    注意：tunnel_server 实例在模块加载时已经创建（含 router），
    这里只是初始化数据库连接。
    
    Args:
        database_url: 数据库连接 URL（与 Forward Service 共用）
    """
    # 更新配置中的数据库 URL
    tunnel_server.config.database_url = database_url
    
    # 初始化数据库
    await tunnel_server.initialize()
    
    logger.info(f"隧道服务器已初始化: ws_path={tunnel_server.config.ws_path}")


def get_tunnel_server() -> TunnelServer:
    """获取隧道服务器实例"""
    return tunnel_server


def is_tunnel_url(url: str) -> bool:
    """
    检查 URL 是否是隧道地址
    
    Args:
        url: 目标 URL，例如 http://my-agent.tunnel/api/chat
        
    Returns:
        True 如果是隧道地址
    """
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(url)
        host = parsed.netloc.split(":")[0]  # 去掉端口
        return host.endswith(TUNNEL_DOMAIN_SUFFIX)
    except Exception:
        return False


def extract_tunnel_domain(url: str) -> Optional[str]:
    """
    从 URL 中提取隧道域名
    
    Args:
        url: 目标 URL，例如 http://my-agent.tunnel/api/chat
        
    Returns:
        隧道域名，例如 "my-agent"，如果不是隧道 URL 则返回 None
    """
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(url)
        host = parsed.netloc.split(":")[0]
        
        if host.endswith(TUNNEL_DOMAIN_SUFFIX):
            # 去掉 .tunnel 后缀
            return host[:-len(TUNNEL_DOMAIN_SUFFIX)]
        return None
    except Exception:
        return None


def extract_tunnel_path(url: str) -> str:
    """
    从 URL 中提取路径
    
    Args:
        url: 目标 URL，例如 http://my-agent.tunnel/api/chat
        
    Returns:
        路径，例如 "/api/chat"
    """
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return path
    except Exception:
        return "/"
