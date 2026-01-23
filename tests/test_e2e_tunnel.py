"""
端到端隧道测试

测试流程：
1. 启动 Forward Service（包含 TunnelServer）
2. 创建隧道，获取 token
3. 启动模拟 Agent（本地 HTTP 服务）
4. 启动 tunely client 连接隧道
5. 通过隧道发送请求，验证响应
"""

import asyncio
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest
import httpx
from tunely import TunnelClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockAgentHandler(BaseHTTPRequestHandler):
    """模拟 Agent HTTP 处理器"""
    
    def log_message(self, format, *args):
        logger.info(f"MockAgent: {format % args}")
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(body)
            message = data.get('message', '')
        except json.JSONDecodeError:
            message = body
        
        # 模拟 Agent 响应
        response = {
            "response": f"Echo from MockAgent: {message}",
            "sessionId": "mock-session-123"
        }
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode('utf-8'))


def start_mock_agent(port: int = 8765):
    """启动模拟 Agent"""
    server = HTTPServer(('127.0.0.1', port), MockAgentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"MockAgent started on port {port}")
    return server


@pytest.mark.asyncio
async def test_tunnel_e2e():
    """端到端隧道测试"""
    
    # 1. 导入必要模块
    from tunely import TunnelServer, TunnelServerConfig
    from tunely.repository import TunnelRepository
    
    # 2. 创建独立的 TunnelServer 实例（使用内存数据库）
    config = TunnelServerConfig(
        database_url="sqlite+aiosqlite:///:memory:",
        ws_path="/ws/tunnel",
    )
    tunnel_server = TunnelServer(config=config)
    await tunnel_server.initialize()
    
    logger.info("TunnelServer initialized")
    
    # 3. 创建隧道
    async with tunnel_server.db.session() as session:
        repo = TunnelRepository(session)
        tunnel = await repo.create(
            domain="test-agent",
            name="Test Agent",
        )
        token = tunnel.token
        logger.info(f"Tunnel created: domain=test-agent, token={token[:20]}...")
    
    # 4. 启动模拟 Agent
    mock_agent_port = 8765
    mock_agent = start_mock_agent(mock_agent_port)
    await asyncio.sleep(0.5)  # 等待服务启动
    
    # 5. 验证模拟 Agent 正常工作
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"http://127.0.0.1:{mock_agent_port}/api/chat",
            json={"message": "test"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "Echo from MockAgent" in data["response"]
    logger.info("MockAgent is working")
    
    # 6. 创建 FastAPI 测试客户端来测试 WebSocket
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import websockets
    
    app = FastAPI()
    app.include_router(tunnel_server.router)
    
    # 启动测试服务器
    import uvicorn
    from multiprocessing import Process
    
    # 使用线程启动服务器
    server_ready = asyncio.Event()
    
    async def run_server():
        config = uvicorn.Config(app, host="127.0.0.1", port=8766, log_level="warning")
        server = uvicorn.Server(config)
        await server.serve()
    
    # 在后台任务中启动服务器
    server_task = asyncio.create_task(run_server())
    await asyncio.sleep(1)  # 等待服务器启动
    
    logger.info("Test server started on port 8766")
    
    # 7. 启动 tunely client
    tunnel_client = TunnelClient(
        server_url="ws://127.0.0.1:8766/ws/tunnel",
        token=token,
        target_url=f"http://127.0.0.1:{mock_agent_port}",
    )
    
    client_task = asyncio.create_task(tunnel_client.run())
    await asyncio.sleep(2)  # 等待客户端连接
    
    # 8. 检查隧道是否连接
    assert tunnel_server.manager.is_connected("test-agent"), "Tunnel should be connected"
    logger.info("Tunnel client connected")
    
    # 9. 通过隧道转发请求
    response = await tunnel_server.forward(
        domain="test-agent",
        method="POST",
        path="/api/chat",
        headers={"Content-Type": "application/json"},
        body={"message": "Hello via tunnel!"},
        timeout=30.0,
    )
    
    logger.info(f"Forward response: status={response.status}, body={response.body}")
    
    # 10. 验证响应
    assert response.status == 200, f"Expected 200, got {response.status}"
    assert response.error is None, f"Unexpected error: {response.error}"
    assert "Echo from MockAgent" in response.body.get("response", "")
    
    logger.info("✅ E2E tunnel test passed!")
    
    # 清理
    tunnel_client.stop()
    server_task.cancel()
    mock_agent.shutdown()
    await tunnel_server.close()


@pytest.mark.asyncio
async def test_tunnel_url_parsing():
    """测试隧道 URL 解析"""
    from forward_service.tunnel import is_tunnel_url, extract_tunnel_domain, extract_tunnel_path
    
    # 测试 is_tunnel_url
    assert is_tunnel_url("http://my-agent.tunnel/api/chat") == True
    assert is_tunnel_url("https://my-agent.tunnel:8080/api") == True
    assert is_tunnel_url("http://example.com/api") == False
    assert is_tunnel_url("http://localhost:8080") == False
    
    # 测试 extract_tunnel_domain
    assert extract_tunnel_domain("http://my-agent.tunnel/api/chat") == "my-agent"
    assert extract_tunnel_domain("http://test.tunnel:8080/") == "test"
    assert extract_tunnel_domain("http://example.com/") is None
    
    # 测试 extract_tunnel_path
    assert extract_tunnel_path("http://my-agent.tunnel/api/chat") == "/api/chat"
    assert extract_tunnel_path("http://my-agent.tunnel/api?foo=bar") == "/api?foo=bar"
    assert extract_tunnel_path("http://my-agent.tunnel") == "/"
    
    logger.info("✅ URL parsing tests passed!")


@pytest.mark.asyncio
async def test_tunnel_command_regex():
    """测试隧道命令正则匹配"""
    import re
    
    # 直接定义正则表达式（与 tunnel_commands.py 一致）
    TUNNEL_CREATE_RE = re.compile(
        r'^/tunnel\s+create\s+([a-zA-Z0-9][-a-zA-Z0-9]{0,62})'
        r'(?:\s+--name\s+(.+?))?$',
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
    
    def is_tunnel_command(message: str) -> bool:
        message = message.strip()
        return bool(
            TUNNEL_CREATE_RE.match(message) or
            TUNNEL_LIST_RE.match(message) or
            TUNNEL_DELETE_RE.match(message) or
            TUNNEL_STATUS_RE.match(message) or
            TUNNEL_TOKEN_RE.match(message)
        )
    
    # 测试 /tunnel create
    match = TUNNEL_CREATE_RE.match("/tunnel create my-agent")
    assert match is not None
    assert match.group(1) == "my-agent"
    
    match = TUNNEL_CREATE_RE.match("/tunnel create my-agent --name Test Agent")
    assert match is not None
    assert match.group(1) == "my-agent"
    assert match.group(2) == "Test Agent"
    
    # 测试 /tunnels
    assert TUNNEL_LIST_RE.match("/tunnels") is not None
    assert TUNNEL_LIST_RE.match("/tunnel") is not None
    assert TUNNEL_LIST_RE.match("/tl") is not None
    
    # 测试 /tunnel delete
    match = TUNNEL_DELETE_RE.match("/tunnel delete my-agent")
    assert match is not None
    assert match.group(1) == "my-agent"
    
    match = TUNNEL_DELETE_RE.match("/tunnel rm test")
    assert match is not None
    assert match.group(1) == "test"
    
    # 测试 /tunnel status
    assert TUNNEL_STATUS_RE.match("/tunnel status") is not None
    
    # 测试 /tunnel token
    match = TUNNEL_TOKEN_RE.match("/tunnel token my-agent")
    assert match is not None
    assert match.group(1) == "my-agent"
    
    # 测试 is_tunnel_command
    assert is_tunnel_command("/tunnel create test") == True
    assert is_tunnel_command("/tunnels") == True
    assert is_tunnel_command("/tunnel status") == True
    assert is_tunnel_command("/tunnel token test") == True
    assert is_tunnel_command("/ap test http://example.com") == False
    assert is_tunnel_command("hello world") == False
    
    logger.info("✅ Command regex tests passed!")


if __name__ == "__main__":
    # 运行简化的测试
    asyncio.run(test_tunnel_url_parsing())
    asyncio.run(test_tunnel_command_regex())
    print("\n✅ All basic tests passed!")
