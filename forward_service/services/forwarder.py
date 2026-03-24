"""
消息转发服务

将用户消息转发到 Agent 并处理响应

支持两种转发模式：
1. 直连模式：直接 HTTP POST 到目标 URL
2. 隧道模式：通过 WebSocket 隧道转发到内网 Agent
"""
import base64
import json as json_module
import logging
import mimetypes
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx

from ..config import config
from ..database import get_db_manager
from ..repository import get_user_project_repository
from ..tunnel import is_tunnel_url, extract_tunnel_domain, extract_tunnel_path, get_tunnel_server, rewrite_tunnel_url

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Agent 响应结果（包含 session_id）"""
    reply: str
    msg_type: str = "markdown_v2"
    session_id: str | None = None
    project_id: str | None = None  # 新增：使用的项目 ID
    project_name: str | None = None  # 新增：项目名称


@dataclass
class ForwardConfig:
    """转发配置"""
    target_url: str
    api_key: str | None
    timeout: int
    project_id: str | None = None
    project_name: str | None = None

    def get_url(self) -> str:
        """获取完整 URL"""
        return self.target_url


def _parse_data_uri(url: str) -> tuple[str, str] | None:
    """
    解析 data: URI，返回 (base64_data, media_type)。
    格式: data:<mediaType>;base64,<data>
    """
    if not url.startswith("data:"):
        return None
    try:
        header, data = url.split(",", 1)
        media_type = header.split(":")[1].split(";")[0]
        return data, media_type
    except (IndexError, ValueError):
        return None


async def download_images_as_base64(
    image_urls: list[str],
) -> list[dict]:
    """
    下载图片并转为 base64 编码，支持 HTTP URL 和 data: URI

    Args:
        image_urls: 图片 URL 列表（支持 http(s):// 和 data: 格式）

    Returns:
        [{"data": "base64...", "mediaType": "image/jpeg"}, ...]
    """
    if not image_urls:
        return []

    images = []
    for url in image_urls:
        parsed = _parse_data_uri(url)
        if parsed:
            data, media_type = parsed
            images.append({"data": data, "mediaType": media_type})
            logger.info(f"data: URI 图片已解析: type={media_type}, size={len(data)}chars")
            continue

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"下载图片失败: url={url}, status={resp.status_code}")
                    continue

                content_type = resp.headers.get("content-type", "")
                if "jpeg" in content_type or "jpg" in content_type:
                    media_type = "image/jpeg"
                elif "png" in content_type:
                    media_type = "image/png"
                elif "gif" in content_type:
                    media_type = "image/gif"
                elif "webp" in content_type:
                    media_type = "image/webp"
                else:
                    path = urlparse(url).path.lower()
                    guessed, _ = mimetypes.guess_type(path)
                    media_type = guessed if guessed and guessed.startswith("image/") else "image/jpeg"

                encoded = base64.b64encode(resp.content).decode("utf-8")
                images.append({"data": encoded, "mediaType": media_type})
                logger.info(f"图片下载成功: url={url[:80]}..., size={len(resp.content)}bytes, type={media_type}")
        except Exception as e:
            logger.warning(f"下载图片异常: url={url}, error={e}")
    return images


async def get_forward_config_for_user(
    bot_key: str,
    chat_id: str,
    current_project_id: str | None = None
) -> ForwardConfig:
    """
    获取用户的转发配置（优先级：会话项目 > 默认项目 > 智能选择 > Bot 配置）

    Args:
        bot_key: Bot Key
        chat_id: 用户/群 ID
        current_project_id: 当前会话指定的项目 ID（可选）

    Returns:
        ForwardConfig 对象

    Raises:
        ValueError: 当无法找到有效的转发配置时
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            project_repo = get_user_project_repository(session)

            # 1. 如果会话指定了项目，优先使用会话的项目
            if current_project_id:
                project = await project_repo.get_by_project_id(bot_key, chat_id, current_project_id)
                if project and project.enabled:
                    logger.info(f"使用会话项目配置: {current_project_id}")
                    return ForwardConfig(
                        target_url=project.url_template,
                        api_key=project.api_key,
                        timeout=project.timeout,
                        project_id=project.project_id,
                        project_name=project.project_name
                    )

            # 2. 查询用户的默认项目
            default_project = await project_repo.get_default_project(bot_key, chat_id)
            if default_project:
                logger.info(f"使用用户默认项目: {default_project.project_id}")
                return ForwardConfig(
                    target_url=default_project.url_template,
                    api_key=default_project.api_key,
                    timeout=default_project.timeout,
                    project_id=default_project.project_id,
                    project_name=default_project.project_name
                )

            # 3. 智能选择：如果没有默认项目，尝试自动选择
            all_projects = await project_repo.get_user_projects(bot_key, chat_id, enabled_only=True)
            if all_projects:
                # 如果只有一个项目，自动使用
                if len(all_projects) == 1:
                    auto_project = all_projects[0]
                    logger.info(f"自动使用唯一项目: {auto_project.project_id}")
                    return ForwardConfig(
                        target_url=auto_project.url_template,
                        api_key=auto_project.api_key,
                        timeout=auto_project.timeout,
                        project_id=auto_project.project_id,
                        project_name=auto_project.project_name
                    )
                else:
                    # 多个项目：使用第一个（Repository 按 is_default DESC, created_at ASC 排序）
                    first_project = all_projects[0]
                    logger.info(f"自动使用第一个项目: {first_project.project_id}")
                    return ForwardConfig(
                        target_url=first_project.url_template,
                        api_key=first_project.api_key,
                        timeout=first_project.timeout,
                        project_id=first_project.project_id,
                        project_name=first_project.project_name
                    )

    except Exception as e:
        logger.error(f"获取用户项目配置失败: {e}，回退到 Bot 配置")

    # 4. 兜底：使用 Bot 级别配置
    bot = await config.get_bot_or_default_from_db(bot_key)
    if not bot:
        logger.warning(f"未找到 Bot 配置: bot_key={bot_key}")
        raise ValueError(f"未找到 Bot 配置且用户无可用项目")

    # 如果 Bot 也没有 URL，抛出更友好的异常
    if not bot.forward_config.target_url:
        logger.warning(f"Bot {bot.name} 未配置转发 URL，且用户无可用项目")
        raise ValueError(f"Bot 未配置转发 URL，且用户无可用项目")

    logger.info(f"使用 Bot 默认配置: {bot.name}")
    return ForwardConfig(
        target_url=bot.forward_config.target_url,
        api_key=bot.forward_config.api_key,
        timeout=bot.forward_config.timeout,
        project_id=None,
        project_name=None
    )


async def forward_to_agent_with_bot(
    bot_key: str | None,
    content: str,
    timeout: int,
    session_id: str | None = None
) -> AgentResult | None:
    """
    使用指定 Bot 转发消息到 Agent
    
    Args:
        bot_key: Bot Key
        content: 消息内容
        timeout: 超时时间（秒）
        session_id: 会话 ID（可选，用于会话持续性）
    
    Returns:
        AgentResult 或 None
    """
    # 获取 Bot 配置（从数据库实时读取，确保多进程一致性）
    bot = await config.get_bot_or_default_from_db(bot_key)
    if not bot:
        logger.warning(f"未找到 bot_key={bot_key} 的配置，且无默认 Bot")
        return None
    
    # 获取目标 URL
    target_url = bot.forward_config.get_url()
    if not target_url:
        logger.warning(f"Bot {bot.name} 的 forward_config.target_url 未配置")
        return None
    
    # 获取 API Key
    api_key = bot.forward_config.api_key
    
    # 使用 Bot 自己的 timeout（如果配置了）
    bot_timeout = bot.forward_config.timeout or timeout
    
    logger.info(f"转发消息到 Agent: url={target_url}, session_id={session_id[:8] if session_id else 'None'}, timeout={bot_timeout}s")
    
    # 构建请求头
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    # 构建请求体（AgentStudio 格式）
    request_body = {"message": content}
    if session_id:
        # 使用 camelCase 格式以匹配 Agent 期望
        request_body["sessionId"] = session_id
    
    start_time = datetime.now()
    
    # 生成请求 ID 用于追踪
    request_id = str(uuid.uuid4())[:8]
    
    try:
        # 设置更合理的超时配置：
        # - connect: 30秒（建立连接的超时）
        # - read: bot_timeout（等待响应的超时，Agent 处理可能很慢）
        # - write: 30秒（发送请求的超时）
        # - pool: 30秒（从连接池获取连接的超时）
        timeout_config = httpx.Timeout(
            connect=30.0,
            read=float(bot_timeout),
            write=30.0,
            pool=30.0
        )
        
        logger.debug(f"[{request_id}] 准备创建 httpx.AsyncClient, read_timeout={bot_timeout}s")
        
        # 添加事件钩子来追踪请求状态
        async def log_request(request):
            logger.debug(f"[{request_id}] >> HTTP 请求开始: {request.method} {request.url}")
            logger.debug(f"[{request_id}] >> Headers: {dict(request.headers)}")
        
        async def log_response(response):
            logger.debug(f"[{request_id}] << HTTP 响应: {response.status_code}")
        
        async with httpx.AsyncClient(
            timeout=timeout_config,
            event_hooks={'request': [log_request], 'response': [log_response]}
        ) as client:
            logger.debug(f"[{request_id}] httpx.AsyncClient 已创建，开始 POST 请求到 {target_url}")
            logger.debug(f"[{request_id}] 请求体: {request_body}")
            response = await client.post(
                target_url,
                json=request_body,
                headers=headers
            )
            logger.debug(f"[{request_id}] POST 请求完成，状态码: {response.status_code}")
            
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            if response.status_code != 200:
                logger.error(f"Agent 返回错误: status={response.status_code}, body={response.text[:200]}")
                return AgentResult(
                    reply=f"⚠️ Agent 返回错误\n状态码: {response.status_code}\n响应: {response.text[:200]}",
                    msg_type="text"
                )
            
            result = response.json()
            logger.info(f"Agent 响应: {str(result)[:200]}")
            
            # 提取 session_id（Agent 可能返回新的 session_id）
            response_session_id = result.get("session_id") or result.get("sessionId") or session_id
            
            # 适配 AgentStudio 响应格式: {"response": "..."}
            if "response" in result:
                return AgentResult(
                    reply=result["response"],
                    session_id=response_session_id
                )
            
            # 兼容标准格式: {"reply": "...", "msg_type": "..."}
            if "reply" in result:
                return AgentResult(
                    reply=result.get("reply", ""),
                    msg_type=result.get("msg_type", "markdown_v2"),
                    session_id=response_session_id
                )
            
            # 兼容其他格式
            if "data" in result or "json" in result:
                raw_data = result.get("json") or result.get("data", {})
                return AgentResult(
                    reply=f"✅ 消息已处理\n\n响应数据:\n```\n{raw_data}\n```",
                    session_id=response_session_id
                )
            
            # 默认返回原始响应
            return AgentResult(
                reply=f"✅ Agent 响应:\n```\n{json_module.dumps(result, ensure_ascii=False, indent=2)[:500]}\n```",
                session_id=response_session_id
            )
            
    except httpx.TimeoutException as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{request_id}] 转发请求超时: {target_url}, 耗时: {duration_ms}ms, 错误类型: {type(e).__name__}")
        return AgentResult(
            reply="⚠️ 请求超时，Agent 响应时间过长",
            msg_type="text"
        )
    except Exception as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{request_id}] 转发请求失败: {e}, 耗时: {duration_ms}ms", exc_info=True)
        return AgentResult(
            reply=f"⚠️ 请求失败: {str(e)}",
            msg_type="text"
        )


async def forward_to_agent_with_user_project(
    bot_key: str | None,
    chat_id: str,
    content: str,
    timeout: int,
    session_id: str | None = None,
    current_project_id: str | None = None,
    image_urls: list[str] | None = None,
) -> AgentResult | None:
    """
    使用用户项目配置转发消息到 Agent（支持三层架构）

    优先级：用户项目配置 > Bot 默认配置

    Args:
        bot_key: Bot Key
        chat_id: 用户/群 ID
        content: 消息内容
        timeout: 超时时间（秒）
        session_id: 会话 ID（可选）
        current_project_id: 当前会话指定的项目 ID（可选）
        image_urls: 图片 URL 列表（可选）

    Returns:
        AgentResult 或 None（包含项目信息）
    """
    # 获取用户的转发配置（自动选择优先级）
    forward_config = await get_forward_config_for_user(bot_key, chat_id, current_project_id)

    # 获取目标 URL
    target_url = forward_config.get_url()
    if not target_url:
        logger.warning(f"转发配置的 URL 为空")
        return None

    # 获取 API Key 和超时配置
    api_key = forward_config.api_key
    request_timeout = forward_config.timeout or timeout

    logger.info(
        f"转发消息到 Agent: url={target_url}, "
        f"project={forward_config.project_id or 'Bot默认'}, "
        f"session_id={session_id[:8] if session_id else 'None'}, "
        f"timeout={request_timeout}s"
    )

    # 构建请求头
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 构建请求体（AgentStudio 格式）
    request_body = {"message": content}
    if session_id:
        request_body["sessionId"] = session_id

    # 下载图片并编码为 base64
    if image_urls:
        images = await download_images_as_base64(image_urls)
        if images:
            request_body["images"] = images
            logger.info(f"附带 {len(images)} 张图片转发到 Agent")

    start_time = datetime.now()
    request_id = str(uuid.uuid4())[:8]

    # === 检查是否使用隧道转发 ===
    if is_tunnel_url(target_url):
        # 优先重写为公共可达的 /t/ 路径 URL（通过 nginx → tunnel_proxy 路由）
        rewritten_url = rewrite_tunnel_url(target_url)
        if rewritten_url:
            logger.info(f"[{request_id}] .tunnel URL 已重写: {target_url} → {rewritten_url}")
            target_url = rewritten_url
            # 继续走下面的 HTTP POST 直连模式
        else:
            # 未配置 TUNNEL_PROXY_BASE_URL，走旧的内部隧道转发
            return await _forward_via_tunnel(
                target_url=target_url,
                headers=headers,
                request_body=request_body,
                request_timeout=request_timeout,
                session_id=session_id,
                forward_config=forward_config,
                request_id=request_id,
                start_time=start_time,
            )

    # === 直连模式：HTTP POST ===
    try:
        # 设置超时配置
        timeout_config = httpx.Timeout(
            connect=30.0,
            read=float(request_timeout),
            write=30.0,
            pool=30.0
        )

        logger.debug(f"[{request_id}] 准备创建 httpx.AsyncClient, read_timeout={request_timeout}s")

        # 添加事件钩子来追踪请求状态
        async def log_request(request):
            logger.debug(f"[{request_id}] >> HTTP 请求开始: {request.method} {request.url}")
            logger.debug(f"[{request_id}] >> Headers: {dict(request.headers)}")

        async def log_response(response):
            logger.debug(f"[{request_id}] << HTTP 响应: {response.status_code}")

        async with httpx.AsyncClient(
            timeout=timeout_config,
            event_hooks={'request': [log_request], 'response': [log_response]}
        ) as client:
            logger.debug(f"[{request_id}] httpx.AsyncClient 已创建，开始 POST 请求到 {target_url}")
            logger.debug(f"[{request_id}] 请求体: {request_body}")
            response = await client.post(
                target_url,
                json=request_body,
                headers=headers
            )
            logger.debug(f"[{request_id}] POST 请求完成，状态码: {response.status_code}")

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            if response.status_code != 200:
                logger.error(f"Agent 返回错误: status={response.status_code}, body={response.text[:200]}")
                return AgentResult(
                    reply=f"⚠️ Agent 返回错误\n状态码: {response.status_code}\n响应: {response.text[:200]}",
                    msg_type="text",
                    project_id=forward_config.project_id,
                    project_name=forward_config.project_name
                )

            # 解析响应
            try:
                result = response.json()
            except Exception as e:
                logger.warning(f"解析 JSON 响应失败: {e}，使用原始文本")
                return AgentResult(
                    reply=response.text[:1000],
                    msg_type="text",
                    session_id=session_id,
                    project_id=forward_config.project_id,
                    project_name=forward_config.project_name
                )

            logger.debug(f"[{request_id}] 响应 JSON: {result}")

            # 提取字段（兼容多种格式）
            reply = result.get("reply") or result.get("response") or result.get("message", "")
            response_session_id = result.get("sessionId") or result.get("session_id") or session_id

            if reply:
                return AgentResult(
                    reply=str(reply),
                    session_id=response_session_id,
                    project_id=forward_config.project_id,
                    project_name=forward_config.project_name
                )

            # 兼容其他格式
            if "data" in result or "json" in result:
                raw_data = result.get("json") or result.get("data", {})
                return AgentResult(
                    reply=f"✅ 消息已处理\n\n响应数据:\n```\n{raw_data}\n```",
                    session_id=response_session_id,
                    project_id=forward_config.project_id,
                    project_name=forward_config.project_name
                )

            # 默认返回原始响应
            return AgentResult(
                reply=f"✅ Agent 响应:\n```\n{json_module.dumps(result, ensure_ascii=False, indent=2)[:500]}\n```",
                session_id=response_session_id,
                project_id=forward_config.project_id,
                project_name=forward_config.project_name
            )

    except httpx.TimeoutException as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{request_id}] 转发请求超时: {target_url}, 耗时: {duration_ms}ms, 错误类型: {type(e).__name__}")
        return AgentResult(
            reply="⚠️ 请求超时，Agent 响应时间过长",
            msg_type="text",
            project_id=forward_config.project_id,
            project_name=forward_config.project_name
        )
    except Exception as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{request_id}] 转发请求失败: {e}, 耗时: {duration_ms}ms", exc_info=True)
        return AgentResult(
            reply=f"⚠️ 请求失败: {str(e)}",
            msg_type="text",
            project_id=forward_config.project_id,
            project_name=forward_config.project_name
        )


async def _forward_via_tunnel(
    target_url: str,
    headers: dict,
    request_body: dict,
    request_timeout: int,
    session_id: str | None,
    forward_config: ForwardConfig,
    request_id: str,
    start_time: datetime,
) -> AgentResult | None:
    """
    通过隧道转发请求到内网 Agent
    
    Args:
        target_url: 目标 URL（如 http://my-agent.tunnel/api/chat）
        headers: 请求头
        request_body: 请求体
        request_timeout: 超时时间
        session_id: 会话 ID
        forward_config: 转发配置
        request_id: 请求 ID（用于追踪）
        start_time: 请求开始时间
        
    Returns:
        AgentResult 或 None
    """
    tunnel_domain = extract_tunnel_domain(target_url)
    path = extract_tunnel_path(target_url)
    
    if not tunnel_domain:
        logger.error(f"[{request_id}] 无法解析隧道域名: {target_url}")
        return AgentResult(
            reply="⚠️ 隧道 URL 格式错误",
            msg_type="text",
            project_id=forward_config.project_id,
            project_name=forward_config.project_name
        )
    
    logger.info(f"[{request_id}] 使用隧道转发: domain={tunnel_domain}, path={path}")
    
    try:
        tunnel_server = get_tunnel_server()
        
        # 检查隧道是否在线
        if not tunnel_server.manager.is_connected(tunnel_domain):
            logger.warning(f"[{request_id}] 隧道未连接: {tunnel_domain}")
            return AgentResult(
                reply=f"⚠️ 隧道未连接\n\n域名: `{tunnel_domain}.tunnel`\n\n💡 请在本地运行 `tunely connect` 建立连接",
                msg_type="text",
                project_id=forward_config.project_id,
                project_name=forward_config.project_name
            )
        
        # 通过隧道转发请求
        response = await tunnel_server.forward(
            domain=tunnel_domain,
            method="POST",
            path=path,
            headers=headers,
            body=request_body,
            timeout=float(request_timeout),
        )
        
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        # 检查隧道响应状态
        if response.error:
            logger.error(f"[{request_id}] 隧道转发错误: {response.error}")
            return AgentResult(
                reply=f"⚠️ 隧道转发失败: {response.error}",
                msg_type="text",
                project_id=forward_config.project_id,
                project_name=forward_config.project_name
            )
        
        if response.status != 200:
            logger.error(f"[{request_id}] Agent 返回错误: status={response.status}")
            body_text = json_module.dumps(response.body, ensure_ascii=False) if response.body else ""
            return AgentResult(
                reply=f"⚠️ Agent 返回错误\n状态码: {response.status}\n响应: {body_text[:200]}",
                msg_type="text",
                project_id=forward_config.project_id,
                project_name=forward_config.project_name
            )
        
        # 解析响应
        result = response.body if isinstance(response.body, dict) else {}
        
        logger.debug(f"[{request_id}] 隧道响应: {result}, 耗时: {duration_ms}ms")
        
        # 提取字段（兼容多种格式）
        reply = result.get("reply") or result.get("response") or result.get("message", "")
        response_session_id = result.get("sessionId") or result.get("session_id") or session_id
        
        if reply:
            return AgentResult(
                reply=str(reply),
                session_id=response_session_id,
                project_id=forward_config.project_id,
                project_name=forward_config.project_name
            )
        
        # 兼容其他格式
        if "data" in result or "json" in result:
            raw_data = result.get("json") or result.get("data", {})
            return AgentResult(
                reply=f"✅ 消息已处理\n\n响应数据:\n```\n{raw_data}\n```",
                session_id=response_session_id,
                project_id=forward_config.project_id,
                project_name=forward_config.project_name
            )
        
        # 默认返回原始响应
        return AgentResult(
            reply=f"✅ Agent 响应:\n```\n{json_module.dumps(result, ensure_ascii=False, indent=2)[:500]}\n```",
            session_id=response_session_id,
            project_id=forward_config.project_id,
            project_name=forward_config.project_name
        )
        
    except Exception as e:
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"[{request_id}] 隧道转发失败: {e}, 耗时: {duration_ms}ms", exc_info=True)
        return AgentResult(
            reply=f"⚠️ 隧道转发失败: {str(e)}",
            msg_type="text",
            project_id=forward_config.project_id,
            project_name=forward_config.project_name
        )
