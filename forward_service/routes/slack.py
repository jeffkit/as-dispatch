"""
Slack 集成路由

处理 Slack Events API webhook:
- URL verification
- 消息事件处理
- @mention 事件处理
"""
import hashlib
import hmac
import logging
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks

from ..config import config
from ..clients.slack import SlackClient
from ..services.forwarder import forward_to_agent_with_user_project, AgentResult
from ..database import get_db_manager
from ..session_manager import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["slack"])


def verify_slack_signature(
    signing_secret: str,
    request_body: str,
    timestamp: str,
    signature: str
) -> bool:
    """
    验证 Slack 请求签名
    
    https://api.slack.com/authentication/verifying-requests-from-slack
    
    Args:
        signing_secret: Slack Signing Secret
        request_body: 原始请求体
        timestamp: X-Slack-Request-Timestamp 头
        signature: X-Slack-Signature 头
    
    Returns:
        签名是否有效
    """
    # 防止重放攻击（请求必须在 5 分钟内）
    now = int(time.time())
    if abs(now - int(timestamp)) > 300:
        logger.warning("⚠️ Slack 请求时间戳过旧")
        return False
    
    # 计算期望的签名
    sig_basestring = f"v0:{timestamp}:{request_body}"
    my_signature = 'v0=' + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # 比较签名（使用 timing-safe 比较）
    return hmac.compare_digest(my_signature, signature)


@router.post("/callback/slack")
async def handle_slack_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    x_slack_signature: Optional[str] = Header(None, alias="x-slack-signature"),
    x_slack_request_timestamp: Optional[str] = Header(None, alias="x-slack-request-timestamp")
):
    """
    处理 Slack Events API 回调
    
    支持:
    - URL verification challenge
    - message 事件
    - app_mention 事件
    """
    # 读取原始请求体
    raw_body = await request.body()
    request_body = raw_body.decode("utf-8")
    
    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"解析 Slack 请求失败: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # 获取事件类型
    event_type = data.get("type")
    
    # 处理 URL 验证挑战
    if event_type == "url_verification":
        challenge = data.get("challenge")
        logger.info("✅ Slack URL 验证挑战收到")
        return {"challenge": challenge}
    
    # 获取 Bot 配置（从 webhook URL 或其他方式识别）
    # 这里假设使用 team_id 来识别 Bot
    team_id = data.get("team_id")
    if not team_id:
        logger.warning("⚠️ Slack 请求缺少 team_id")
        raise HTTPException(status_code=400, detail="Missing team_id")
    
    # 查找对应的 Slack Bot 配置
    # 暂时使用默认 Bot (后续可以扩展为多 Bot 支持)
    bot = config.get_bot_or_default(config.default_bot_key)
    if not bot or bot.platform != "slack":
        logger.warning(f"未找到 Slack Bot 配置: team_id={team_id}")
        raise HTTPException(status_code=404, detail="Slack bot not found")
    
    # 获取平台配置
    platform_config = bot.get_platform_config()
    signing_secret = platform_config.get("signing_secret")
    bot_token = platform_config.get("bot_token")
    
    if not signing_secret or not bot_token:
        logger.error("Slack Bot 配置不完整")
        raise HTTPException(status_code=500, detail="Slack bot configuration incomplete")
    
    # 验证签名
    if not x_slack_signature or not x_slack_request_timestamp:
        logger.warning("⚠️ 缺少 Slack 签名头")
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    if not verify_slack_signature(signing_secret, request_body, x_slack_request_timestamp, x_slack_signature):
        logger.warning("⚠️ 无效的 Slack 签名")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # 处理事件回调
    if event_type == "event_callback":
        event = data.get("event", {})
        event_subtype = event.get("type")
        
        logger.info(f"📨 收到 Slack 事件: {event_subtype}")
        
        # 忽略 bot 消息
        if event.get("bot_id") or event.get("subtype"):
            logger.info("🤖 忽略 bot 消息或子类型消息")
            return {"ok": True}
        
        # 立即响应 200 OK（Slack 要求 3 秒内响应）
        # 使用后台任务异步处理消息
        if event_subtype in ("message", "app_mention"):
            background_tasks.add_task(handle_message_event, bot, bot_token, event)
        
        return {"ok": True}
    
    logger.warning(f"⚠️ 未知的 Slack payload 类型: {event_type}")
    return {"ok": True}


async def handle_slash_command(
    slack_client: SlackClient,
    session_mgr,
    channel: str,
    thread_ts: str,
    user: str,
    bot,
    cmd_type: str,
    cmd_arg: Optional[str],
    extra_msg: Optional[str],
    session_key: str,
    current_session_id: Optional[str]
):
    """
    处理 Slash 命令
    """
    try:
        if cmd_type == "list":
            # /sess 或 /s - 列出会话
            sessions = await session_mgr.list_sessions(user, session_key, bot_key=bot.bot_key)
            reply_msg = session_mgr.format_session_list(sessions)
            await slack_client.post_message(
                channel=channel,
                text=reply_msg,
                thread_ts=thread_ts
            )
        
        elif cmd_type == "reset":
            # /reset 或 /r - 重置会话
            success = await session_mgr.reset_session(user, session_key, bot.bot_key)
            if success:
                reply_msg = "✅ 会话已重置，下次发送消息将开始新对话"
            else:
                reply_msg = "✅ 已准备好开始新对话，请发送消息"
            await slack_client.post_message(
                channel=channel,
                text=reply_msg,
                thread_ts=thread_ts
            )
        
        elif cmd_type == "id":
            await slack_client.post_message(
                channel=channel,
                text=f"🆔 Chat ID: `{channel}`",
                thread_ts=thread_ts
            )

        elif cmd_type == "change":
            # /change <short_id> 或 /c <short_id> - 切换会话
            if not cmd_arg:
                await slack_client.post_message(
                    channel=channel,
                    text="❌ 请提供会话 ID，例如: `/c abc123`",
                    thread_ts=thread_ts
                )
                return
            
            target_session = await session_mgr.change_session(user, session_key, cmd_arg, bot_key=bot.bot_key)
            if not target_session:
                await slack_client.post_message(
                    channel=channel,
                    text=f"❌ 未找到会话 `{cmd_arg}`\n使用 `/s` 查看可用会话",
                    thread_ts=thread_ts
                )
                return
            
            reply_msg = f"✅ 已切换到会话 `{target_session.short_id}`\n最后消息: {target_session.last_message or '(无)'}"
            
            # 如果有附带消息，继续处理
            if extra_msg:
                reply_msg += f"\n\n继续处理消息: {extra_msg}"
                # 这里可以选择继续转发消息到 Agent
                # 暂时只是提示用户
            
            await slack_client.post_message(
                channel=channel,
                text=reply_msg,
                thread_ts=thread_ts
            )
        
        else:
            await slack_client.post_message(
                channel=channel,
                text=f"❓ 未知命令: `/{cmd_type}`",
                thread_ts=thread_ts
            )
    
    except Exception as e:
        logger.error(f"处理 Slack 命令失败: {e}", exc_info=True)
        await slack_client.post_message(
            channel=channel,
            text=f"❌ 命令执行失败: {str(e)}",
            thread_ts=thread_ts
        )


async def handle_message_event(bot, bot_token: str, event: dict):
    """
    处理 Slack 消息事件
    
    Args:
        bot: Bot 配置对象
        bot_token: Slack Bot Token
        event: 事件数据
    """
    slack_client = SlackClient(bot_token)
    
    channel = event.get("channel")
    user = event.get("user")
    text = event.get("text", "")
    ts = event.get("ts")
    thread_ts = event.get("thread_ts", ts)  # 如果没有 thread_ts，使用消息自己的 ts
    files = event.get("files", [])
    
    # 移除 bot mention 标记
    text = text.replace(f"<@{event.get('bot_id', '')}>", "").strip()
    
    if not text and not files:
        logger.warning("消息内容和文件均为空，跳过处理")
        return
    
    logger.info(f"处理消息: channel={channel}, user={user}, text={text[:50] if text else '(image)'}...")
    
    # 发送"正在思考..."占位消息
    try:
        placeholder_msg = await slack_client.post_message(
            channel=channel,
            text="🤔 正在思考...",
            thread_ts=thread_ts
        )
        placeholder_ts = placeholder_msg.get("ts")
    except Exception as e:
        logger.error(f"发送占位消息失败: {e}")
        return
    
    # 获取会话管理器
    session_mgr = get_session_manager()
    
    # 获取或创建会话
    # Slack 使用 channel + thread_ts 作为会话上下文
    session_key = f"{channel}:{thread_ts}"
    active_session = await session_mgr.get_active_session(user, session_key, bot.bot_key)
    current_session_id = active_session.session_id if active_session else None
    current_project_id = active_session.current_project_id if active_session else None
    
    # 检查是否为 Slash 命令
    if text:
        slash_cmd = session_mgr.parse_slash_command(text)
        if slash_cmd:
            await handle_slash_command(
                slack_client=slack_client,
                session_mgr=session_mgr,
                channel=channel,
                thread_ts=thread_ts,
                user=user,
                bot=bot,
                cmd_type=slash_cmd[0],
                cmd_arg=slash_cmd[1],
                extra_msg=slash_cmd[2],
                session_key=session_key,
                current_session_id=current_session_id
            )
            return
    
    try:
        # 处理图片附件
        image_data = None
        if files:
            logger.info(f"检测到 {len(files)} 个文件附件")
            # 目前只处理第一个图片
            for file in files:
                if file.get("mimetype", "").startswith("image/"):
                    try:
                        url = file.get("url_private_download")
                        if url:
                            file_content = await slack_client.download_file(url)
                            import base64
                            image_data = {
                                "data": base64.b64encode(file_content).decode("utf-8"),
                                "mediaType": file.get("mimetype", "image/png"),
                                "filename": file.get("name", "image.png")
                            }
                            logger.info(f"成功处理图片: {file.get('name')}")
                            break
                    except Exception as e:
                        logger.error(f"下载 Slack 文件失败: {e}")
        
        # 转发消息到 Agent（TODO: 支持图片）
        # 当前 forward_to_agent_with_user_project 不支持图片，需要扩展
        result = await forward_to_agent_with_user_project(
            bot_key=bot.bot_key,
            chat_id=session_key,  # 使用 channel:thread_ts 作为 chat_id
            content=text or "(图片消息)",
            timeout=config.timeout,
            session_id=current_session_id,
            current_project_id=current_project_id
        )
        
        if not result:
            await slack_client.update_message(
                channel=channel,
                ts=placeholder_ts,
                text="⚠️ 处理请求时发生错误，请稍后重试"
            )
            return
        
        # 更新占位消息为 Agent 响应
        await slack_client.update_message(
            channel=channel,
            ts=placeholder_ts,
            text=result.reply
        )
        
        # 记录会话
        if result.session_id:
            await session_mgr.record_session(
                user_id=user,
                chat_id=session_key,
                bot_key=bot.bot_key,
                session_id=result.session_id,
                last_message=text,
                current_project_id=current_project_id
            )
            logger.info(f"会话已记录: session={result.session_id[:8]}...")
        
    except Exception as e:
        logger.error(f"处理 Slack 消息失败: {e}", exc_info=True)
        try:
            await slack_client.update_message(
                channel=channel,
                ts=placeholder_ts,
                text=f"❌ 错误: {str(e)}"
            )
        except Exception:
            pass
