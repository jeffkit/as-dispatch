"""
Tunnel Proxy Routes - 路径前缀模式

通过 /t/{domain}/... 路径直接访问隧道后的服务。
用于浏览器跨域访问内网服务（无需 DNS 泛解析 + 通配符 SSL）。

使用示例:
    # 访问隧道后的 AgentStudio 后端
    https://agentstudio.woa.com/t/my-agent/api/health
    → 通过隧道转发到本地 http://localhost:4936/api/health
    
    # SSE 流式请求同样支持
    https://agentstudio.woa.com/t/my-agent/api/agents/chat
    → 通过隧道转发 SSE 流到本地后端
"""

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from ..tunnel import tunnel_server

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/t", tags=["tunnel-proxy"])


@router.api_route(
    "/{tunnel_domain}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def path_prefix_forward(request: Request, tunnel_domain: str, path: str):
    """路径前缀模式 - 通过 /t/{domain}/ 转发请求到隧道"""
    full_path = f"/{path}"
    if request.query_params:
        full_path += f"?{request.query_params}"
    return await _forward_to_tunnel(request, tunnel_domain, full_path)


@router.api_route(
    "/{tunnel_domain}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def path_prefix_forward_root(request: Request, tunnel_domain: str):
    """路径前缀模式 - 根路径转发"""
    return await _forward_to_tunnel(request, tunnel_domain, "/")


async def _forward_to_tunnel(
    request: Request, domain: str, path: str
) -> Response | StreamingResponse:
    """
    转发请求到隧道
    
    Args:
        request: FastAPI 请求对象
        domain: 隧道域名
        path: 请求路径（包含查询参数）
        
    Returns:
        响应对象
    """
    # 检查隧道是否连接
    if not tunnel_server.manager.is_connected(domain):
        return Response(
            content=json.dumps({"error": f"Tunnel not connected: {domain}"}),
            status_code=503,
            media_type="application/json",
        )
    
    # 提取请求信息
    method = request.method
    headers = dict(request.headers)
    
    # 移除不应该转发的头
    headers.pop("host", None)
    headers.pop("content-length", None)
    
    # 读取请求体
    body = None
    if method in ("POST", "PUT", "PATCH"):
        body_bytes = await request.body()
        if body_bytes:
            try:
                body = json.loads(body_bytes)
            except json.JSONDecodeError:
                # 非 JSON 请求体，转为字符串
                body = body_bytes.decode("utf-8", errors="replace")
    
    # 检查是否请求 SSE
    accept_header = headers.get("accept", "")
    is_sse = "text/event-stream" in accept_header
    
    logger.info(f"[TunnelProxy] {method} /t/{domain}{path} (SSE={is_sse})")
    
    if is_sse:
        # SSE 流式响应
        return StreamingResponse(
            _stream_tunnel_response(domain, method, path, headers, body),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # 普通响应
        try:
            response = await tunnel_server.forward(
                domain=domain,
                method=method,
                path=path,
                headers=headers,
                body=body,
                timeout=300.0,
            )
            
            logger.debug(f"[TunnelProxy] Forward response: status={response.status}, body_type={type(response.body).__name__}, body_len={len(response.body) if response.body else 0}, error={response.error}")
            
            if response.error:
                return Response(
                    content=json.dumps({"error": response.error}),
                    status_code=response.status or 502,
                    media_type="application/json",
                )
            
            # 构建响应头，过滤掉不应转发的头
            resp_headers = dict(response.headers) if response.headers else {}
            
            headers_to_remove = [
                "connection", "keep-alive", "transfer-encoding", "te",
                "trailer", "upgrade", "proxy-connection",
                "content-length", "content-encoding",
                "access-control-allow-origin", "access-control-allow-methods",
                "access-control-allow-headers", "access-control-allow-credentials",
                "access-control-expose-headers", "access-control-max-age",
            ]
            for header in headers_to_remove:
                resp_headers.pop(header, None)
            
            content = response.body
            if content is None:
                content = b""
            elif not isinstance(content, (str, bytes)):
                content = json.dumps(content)
            
            media_type = resp_headers.get("content-type", "application/octet-stream")
            
            return Response(
                content=content,
                status_code=response.status,
                headers=resp_headers,
                media_type=media_type,
            )
        except Exception as e:
            logger.error(f"[TunnelProxy] 转发请求失败: {e}", exc_info=True)
            return Response(
                content=json.dumps({"error": f"Forward failed: {str(e)}"}),
                status_code=502,
                media_type="application/json",
            )


async def _stream_tunnel_response(
    domain: str,
    method: str,
    path: str,
    headers: dict,
    body: any,
) -> AsyncIterator[str]:
    """
    流式响应生成器（SSE 格式）
    
    Yields:
        SSE 格式的数据块
    """
    from tunely import StreamStartMessage, StreamChunkMessage, StreamEndMessage
    
    try:
        async for msg in tunnel_server.forward_stream(
            domain=domain,
            method=method,
            path=path,
            headers=headers,
            body=body,
            timeout=300.0,
        ):
            if isinstance(msg, StreamStartMessage):
                yield f"event: start\ndata: {{}}\n\n"
            
            elif isinstance(msg, StreamChunkMessage):
                yield f"data: {msg.data}\n\n"
            
            elif isinstance(msg, StreamEndMessage):
                if msg.error:
                    yield f"event: error\ndata: {msg.error}\n\n"
                else:
                    yield f"event: done\ndata: {{}}\n\n"
                break
    
    except Exception as e:
        logger.error(f"[TunnelProxy] 流式转发失败: {e}", exc_info=True)
        yield f"event: error\ndata: {str(e)}\n\n"
