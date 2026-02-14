"""
Bot 注册与管理命令处理

处理 Bot owner 的管理斜杠命令：
- /register <名称> <URL> — 首次注册 Bot（设置名称、转发URL、owner）
- /bot set url <URL> — 修改转发 URL（仅 owner）
- /bot set name <名称> — 修改 Bot 名称（仅 owner）
- /bot set api-key <Key> — 修改 API Key（仅 owner）
- /bot set timeout <秒> — 修改超时时间（仅 owner）
- /bot info — 查看 Bot 配置信息（所有人可用）
"""
import logging
import re
from typing import Tuple, Optional

from ..config import config
from ..database import get_db_manager
from ..repository import get_chatbot_repository

logger = logging.getLogger(__name__)


# ============== 命令正则匹配 ==============

# /register <名称> <URL>
REGISTER_RE = re.compile(
    r'^/register\s+(\S+)\s+(https?://\S+)',
    re.IGNORECASE
)

# /bot set <field> <value>
BOT_SET_RE = re.compile(
    r'^/bot\s+set\s+(url|name|api-key|apikey|timeout)\s+(.+)',
    re.IGNORECASE
)

# /bot info
BOT_INFO_RE = re.compile(
    r'^/bot\s+info\s*$',
    re.IGNORECASE
)


def is_bot_command(message: str) -> bool:
    """判断消息是否是 Bot 管理命令"""
    message = message.strip()
    return bool(
        REGISTER_RE.match(message) or
        BOT_SET_RE.match(message) or
        BOT_INFO_RE.match(message)
    )


async def handle_bot_command(
    bot_key: str,
    message: str,
    from_user_id: str,
) -> Tuple[bool, str]:
    """
    处理 Bot 管理命令

    Args:
        bot_key: 当前 Bot 的 key
        message: 用户消息
        from_user_id: 发送者用户 ID

    Returns:
        (success, response_message)
    """
    message = message.strip()

    if REGISTER_RE.match(message):
        return await handle_register(bot_key, message, from_user_id)
    elif BOT_SET_RE.match(message):
        return await handle_bot_set(bot_key, message, from_user_id)
    elif BOT_INFO_RE.match(message):
        return await handle_bot_info(bot_key, from_user_id)
    else:
        return False, "❌ 未知的 Bot 命令"


# ============== /register 命令 ==============

async def handle_register(
    bot_key: str,
    message: str,
    from_user_id: str,
) -> Tuple[bool, str]:
    """
    处理 /register <名称> <URL> 命令

    首次注册 Bot：设置名称、转发 URL、启用 Bot、绑定 owner。
    仅在 Bot 尚未注册（无 owner）时可用。
    """
    match = REGISTER_RE.match(message.strip())
    if not match:
        return False, (
            "❌ 命令格式错误\n\n"
            "用法: `/register <Bot名称> <Agent URL>`\n"
            "示例: `/register my-agent https://my-agent.com/a2a`"
        )

    bot_name = match.group(1)
    target_url = match.group(2)

    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_chatbot_repository(session)
            bot = await repo.get_by_bot_key(bot_key)

            if not bot:
                return False, "❌ Bot 不存在，请先发送一条消息让系统自动发现"

            # 检查是否已注册
            if bot.owner_id:
                return False, (
                    f"⚠️ 此 Bot 已被注册\n\n"
                    f"• 名称: {bot.name}\n"
                    f"• 管理员: {bot.owner_id}\n\n"
                    f"如需修改配置，请联系 Bot 管理员使用 `/bot set` 命令"
                )

            # 注册：更新 Bot 配置
            await repo.update(
                bot.id,
                name=bot_name,
                target_url=target_url,
                url_template=target_url,  # 同步更新兼容字段
                enabled=True,
                owner_id=from_user_id,
            )
            await session.commit()

        # 刷新内存缓存
        await config.reload_config()

        logger.info(f"Bot 注册成功: bot_key={bot_key[:10]}..., name={bot_name}, owner={from_user_id}")

        return True, (
            f"✅ Bot 注册成功！\n\n"
            f"• 名称: {bot_name}\n"
            f"• 转发地址: {target_url}\n"
            f"• 管理员: {from_user_id}\n\n"
            f"后续消息将转发到上述地址。\n"
            f"💡 使用 `/bot info` 查看配置，`/bot set url <新URL>` 修改转发地址"
        )

    except Exception as e:
        logger.error(f"注册 Bot 失败: {e}")
        return False, f"❌ 注册失败: {str(e)}"


# ============== /bot set 命令 ==============

async def handle_bot_set(
    bot_key: str,
    message: str,
    from_user_id: str,
) -> Tuple[bool, str]:
    """
    处理 /bot set <field> <value> 命令

    仅 Bot owner 可操作。
    """
    match = BOT_SET_RE.match(message.strip())
    if not match:
        return False, (
            "❌ 命令格式错误\n\n"
            "用法:\n"
            "  `/bot set url <新URL>` - 修改转发地址\n"
            "  `/bot set name <新名称>` - 修改名称\n"
            "  `/bot set api-key <新Key>` - 修改 API Key\n"
            "  `/bot set timeout <秒>` - 修改超时"
        )

    field = match.group(1).lower()
    value = match.group(2).strip()

    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_chatbot_repository(session)
            bot = await repo.get_by_bot_key(bot_key)

            if not bot:
                return False, "❌ Bot 不存在"

            # 权限检查：只有 owner 可以修改
            if not bot.owner_id:
                return False, "⚠️ 此 Bot 尚未注册，请先使用 `/register <名称> <URL>` 注册"

            if bot.owner_id != from_user_id:
                return False, f"⚠️ 仅 Bot 管理员可修改配置（管理员: {bot.owner_id}）"

            # 根据字段更新
            if field == "url":
                if not value.startswith(("http://", "https://")):
                    return False, "❌ URL 必须以 http:// 或 https:// 开头"
                await repo.update(bot.id, target_url=value, url_template=value)
                msg = f"✅ 转发地址已更新:\n{value}"

            elif field == "name":
                await repo.update(bot.id, name=value)
                msg = f"✅ Bot 名称已更新: {value}"

            elif field in ("api-key", "apikey"):
                await repo.update(bot.id, api_key=value)
                masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else value
                msg = f"✅ API Key 已更新: {masked}"

            elif field == "timeout":
                try:
                    timeout_val = int(value)
                    if timeout_val < 10 or timeout_val > 600:
                        return False, "❌ 超时时间范围: 10-600 秒"
                    await repo.update(bot.id, timeout=timeout_val)
                    msg = f"✅ 超时时间已更新: {timeout_val} 秒"
                except ValueError:
                    return False, "❌ 超时时间必须是数字"

            else:
                return False, f"❌ 未知字段: {field}"

            await session.commit()

        # 刷新内存缓存
        await config.reload_config()

        return True, msg + "\n\n⚠️ 配置已立即生效"

    except Exception as e:
        logger.error(f"修改 Bot 配置失败: {e}")
        return False, f"❌ 修改失败: {str(e)}"


# ============== /bot info 命令 ==============

async def handle_bot_info(
    bot_key: str,
    from_user_id: str,
) -> Tuple[bool, str]:
    """
    处理 /bot info 命令

    所有人可查看 Bot 基本配置信息。
    """
    try:
        # 从内存缓存获取
        bot_config = config.get_bot(bot_key)
        if not bot_config:
            return False, "❌ Bot 配置未找到"

        url = bot_config.forward_config.get_url() or "未设置"
        api_key = bot_config.forward_config.api_key
        masked_key = (
            f"{api_key[:4]}...{api_key[-4:]}"
            if api_key and len(api_key) > 8
            else (api_key if api_key else "未设置")
        )
        status = "✅ 已注册" if bot_config.is_registered else "⏳ 待注册"
        owner = bot_config.owner_id or "无"

        lines = [
            f"🤖 **{bot_config.name}** 配置信息",
            "",
            f"• 状态: {status}",
            f"• 管理员: {owner}",
            f"• 转发地址: {url}",
            f"• API Key: {masked_key}",
            f"• 超时: {bot_config.forward_config.timeout}秒",
            f"• 启用: {'✅' if bot_config.enabled else '❌'}",
        ]

        # 如果是 owner，显示管理命令
        if bot_config.owner_id == from_user_id:
            lines.extend([
                "",
                "💡 管理命令:",
                "  `/bot set url <新URL>` - 修改转发地址",
                "  `/bot set name <新名称>` - 修改名称",
                "  `/bot set api-key <新Key>` - 修改 API Key",
                "  `/bot set timeout <秒>` - 修改超时",
            ])

        return True, "\n".join(lines)

    except Exception as e:
        logger.error(f"获取 Bot 信息失败: {e}")
        return False, f"❌ 获取 Bot 信息失败: {str(e)}"


# ============== 帮助信息 ==============

def get_register_help() -> str:
    """获取未配置 Bot 的引导信息"""
    return (
        "👋 这个 Bot 还未配置转发目标。\n\n"
        "请发送以下命令完成设置：\n"
        "```\n"
        "/register <Bot名称> <Agent URL>\n"
        "```\n\n"
        "示例：\n"
        "```\n"
        "/register my-agent https://my-agent.com/a2a\n"
        "```\n\n"
        "💡 注册后，所有发送给此 Bot 的消息将转发到指定地址"
    )
