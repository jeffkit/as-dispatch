"""
管理员命令处理模块

处理 /ping, /status, /bots, /bot, /pending, /recent, /errors, /health 等命令
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select, func

from ..config import config
from ..database import get_db_manager, get_database_url, is_mysql_database
from ..models import ForwardLog
from ..repository import get_system_config_repository, get_forward_log_repository, get_chatbot_repository

logger = logging.getLogger(__name__)


# ============== 管理员权限检查 ==============

async def check_is_admin(user_id: str, alias: str = None) -> bool:
    """
    检查用户是否是管理员
    
    管理员列表存储在 system_config 表的 admin_users 键中
    格式: JSON 数组 ["user_id_1", "alias_1", ...]
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_system_config_repository(session)
            admin_users_json = await repo.get_value("admin_users", "[]")
            admin_users = json.loads(admin_users_json)
            
            # 检查 user_id 或 alias 是否在管理员列表中
            if user_id in admin_users:
                return True
            if alias and alias in admin_users:
                return True
            
            return False
    except Exception as e:
        logger.error(f"检查管理员权限失败: {e}")
        return False


# ============== 系统状态命令 ==============

async def get_system_status() -> str:
    """获取系统状态信息"""
    import sys
    from datetime import timedelta
    
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            log_repo = get_forward_log_repository(session)
            
            # 获取今日统计
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            
            # 今日请求数
            today_stmt = (
                select(func.count(ForwardLog.id))
                .where(ForwardLog.timestamp >= today_start)
            )
            today_result = await session.execute(today_stmt)
            today_count = today_result.scalar() or 0
            
            # 成功数
            success_stmt = (
                select(func.count(ForwardLog.id))
                .where(ForwardLog.timestamp >= today_start)
                .where(ForwardLog.status == "success")
            )
            success_result = await session.execute(success_stmt)
            success_count = success_result.scalar() or 0
            
            # 平均响应时间
            avg_stmt = (
                select(func.avg(ForwardLog.duration_ms))
                .where(ForwardLog.timestamp >= today_start)
                .where(ForwardLog.status == "success")
            )
            avg_result = await session.execute(avg_stmt)
            avg_duration = avg_result.scalar() or 0
        
        success_rate = (success_count / today_count * 100) if today_count > 0 else 100
        avg_str = f"{avg_duration/1000:.1f}s" if avg_duration > 1000 else f"{int(avg_duration)}ms"
        
        # 动态检测数据库类型
        db_url = get_database_url()
        db_type = "MySQL" if is_mysql_database(db_url) else "SQLite"
        
        return f"""🟢 Forward Service 状态

📊 版本: 3.0.0
🤖 Bot 数量: {len(config.bots)} 个

📈 今日统计
• 请求: {today_count} 条
• 成功率: {success_rate:.1f}%
• 平均响应: {avg_str}

🐍 Python: {sys.version.split()[0]}
💾 数据库: {db_type}"""

    except Exception as e:
        return f"⚠️ 获取系统状态失败: {e}"


async def get_admin_help() -> str:
    """生成管理员帮助信息"""
    return """📖 管理员命令帮助

🔧 系统状态
• /ping - 健康检查
• /status - 系统状态

🤖 Bot 管理
• /bots - 列出所有 Bot
• /bot <name> - 查看 Bot 详情
• /bot <name> url <新URL> - 修改 URL
• /bot <name> key <新Key> - 修改 API Key

📊 请求监控
• /pending - 正在处理的请求
• /recent - 最近 10 条日志
• /errors - 最近错误

🏥 运维
• /health - 检查 Agent 可达性

💬 会话管理（所有用户可用）
• /s - 列出会话
• /r - 重置会话
• /c <id> - 切换会话"""


def get_admin_full_help() -> str:
    """生成管理员完整帮助信息（同步函数）"""
    current_time = datetime.now().strftime("%H:%M:%S")
    return f"""📖 **管理员帮助**

📦 **项目管理**
  `/ap <ID> <URL> [--api-key KEY] [--default]` - 添加项目
  `/lp` - 查看我的项目
  `/u <ID>` - 切换项目
  `/sd <ID>` - 设为默认
  `/rp <ID>` - 删除项目
  `/cp` - 当前项目

💬 **会话管理**
  `/s` - 列出会话
  `/r` - 重置会话
  `/c <ID>` - 切换会话

🔧 **管理员命令**
  `/ping` - 健康检查
  `/status` - 系统状态
  `/bots` - 列出所有 Bot
  `/bot <name>` - 查看详情
  `/bot <name> url <URL>` - 修改 URL
  `/pending` - 处理中的请求
  `/recent` - 最近日志
  `/errors` - 错误日志
  `/health` - Agent 可达性

📖 文档: https://agentstudio.woa.com/docs/qywx-bot
⏱️ {current_time}"""


def get_regular_user_help() -> str:
    """生成普通用户帮助信息（同步函数）"""
    current_time = datetime.now().strftime("%H:%M:%S")
    return f"""📖 **用户帮助**

📦 **项目管理**
  `/ap <ID> <URL> [--api-key KEY] [--default]` - 添加项目
  `/lp` - 查看我的项目
  `/u <ID>` - 切换项目
  `/sd <ID>` - 设为默认
  `/rp <ID>` - 删除项目
  `/cp` - 当前项目

💬 **会话管理**
  `/s` - 列出会话
  `/r` - 重置会话
  `/c <ID>` - 切换会话

💡 **如何获取 URL 和 API Key**
  请参考文档：https://agentstudio.woa.com/docs/qywx-bot

⏱️ {current_time}"""


# ============== Bot 管理命令 ==============

async def get_bots_list() -> str:
    """获取所有 Bot 列表"""
    bots = config.bots
    if not bots:
        return "📭 暂无配置的 Bot"
    
    lines = ["🤖 Bot 列表\n"]
    for bot in bots.values():
        status = "✅" if bot.enabled else "❌"
        lines.append(f"{status} {bot.name}")
    
    return "\n".join(lines)


async def get_bot_detail(bot_name: str) -> str:
    """获取 Bot 详情"""
    # 查找 Bot
    bot = None
    for b in config.bots.values():
        if b.name.lower() == bot_name.lower():
            bot = b
            break
    
    if not bot:
        return f"❌ 未找到 Bot: {bot_name}"
    
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            
            # 今日请求数
            today_stmt = (
                select(func.count(ForwardLog.id))
                .where(ForwardLog.bot_key == bot.bot_key)
                .where(ForwardLog.timestamp >= today_start)
            )
            today_result = await session.execute(today_stmt)
            today_count = today_result.scalar() or 0
            
            # 成功数
            success_stmt = (
                select(func.count(ForwardLog.id))
                .where(ForwardLog.bot_key == bot.bot_key)
                .where(ForwardLog.timestamp >= today_start)
                .where(ForwardLog.status == "success")
            )
            success_result = await session.execute(success_stmt)
            success_count = success_result.scalar() or 0
            
            # 平均响应时间
            avg_stmt = (
                select(func.avg(ForwardLog.duration_ms))
                .where(ForwardLog.bot_key == bot.bot_key)
                .where(ForwardLog.timestamp >= today_start)
                .where(ForwardLog.status == "success")
            )
            avg_result = await session.execute(avg_stmt)
            avg_duration = avg_result.scalar() or 0
            
            # 最近错误
            error_stmt = (
                select(ForwardLog.error, ForwardLog.timestamp)
                .where(ForwardLog.bot_key == bot.bot_key)
                .where(ForwardLog.status != "success")
                .order_by(ForwardLog.timestamp.desc())
                .limit(1)
            )
            error_result = await session.execute(error_stmt)
            last_error = error_result.first()
        
        success_rate = (success_count / today_count * 100) if today_count > 0 else 100
        avg_str = f"{avg_duration/1000:.1f}s" if avg_duration > 1000 else f"{int(avg_duration)}ms"
        error_info = last_error[0][:50] if last_error else "无"
        
        # 脱敏 API Key
        api_key = bot.forward_config.api_key
        masked_key = f"{api_key[:4]}...{api_key[-4:]}" if api_key and len(api_key) > 8 else (api_key if api_key else "未设置")
        
        return f"""🤖 {bot.name} 详情

📊 今日统计
• 请求: {today_count} 条
• 成功率: {success_rate:.1f}%
• 平均响应: {avg_str}
• 最近错误: {error_info}

⚙️ 配置
• URL: {bot.forward_config.get_url()}
• API Key: {masked_key}
• 状态: {"✅ 启用" if bot.enabled else "❌ 禁用"}

💡 可用命令:
• /bot {bot.name} url <新URL> - 修改 URL
• /bot {bot.name} key <新Key> - 修改 API Key"""
    
    except Exception as e:
        return f"⚠️ 获取 Bot 详情失败: {e}"


async def update_bot_config(bot_name: str, field: str, value: str) -> str:
    """更新 Bot 配置"""
    # 查找 Bot
    bot = None
    bot_key = None
    for key, b in config.bots.items():
        if b.name.lower() == bot_name.lower():
            bot = b
            bot_key = key
            break
    
    if not bot:
        return f"❌ 未找到 Bot: {bot_name}"
    
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_chatbot_repository(session)
            
            # 通过 bot_key 查找数据库记录
            db_bot = await repo.get_by_bot_key(bot_key)
            if not db_bot:
                return f"❌ 数据库中未找到 Bot: {bot_name}"
            
            # 根据字段类型更新
            if field.lower() == "url":
                await repo.update(db_bot.id, url_template=value)
                msg = f"✅ 已更新 {bot.name} 的 URL:\n{value}"
            elif field.lower() == "key":
                await repo.update(db_bot.id, api_key=value)
                masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else value
                msg = f"✅ 已更新 {bot.name} 的 API Key:\n{masked}"
            else:
                return f"❌ 未知字段: {field}"
        
        # 重新加载配置
        await config.reload()
        
        return msg + "\n\n⚠️ 配置已更新，立即生效"
    
    except Exception as e:
        return f"⚠️ 更新失败: {e}"


# ============== 请求监控命令 ==============

# 存储正在处理的请求 {request_id: {bot_name, user, message, start_time}}
_pending_requests: dict = {}


def get_session_key(user_id: str, chat_id: str, bot_key: str) -> str:
    """生成会话唯一标识"""
    return f"{user_id}:{chat_id}:{bot_key}"


def add_pending_request(request_id: str, bot_name: str, user: str, message: str) -> None:
    """添加一个正在处理的请求"""
    _pending_requests[request_id] = {
        "bot_name": bot_name,
        "user": user,
        "message": message[:50] + "..." if len(message) > 50 else message,
        "start_time": datetime.now()
    }


def remove_pending_request(request_id: str) -> None:
    """移除一个已完成的请求"""
    _pending_requests.pop(request_id, None)


def get_pending_requests() -> list[dict]:
    """获取所有正在处理的请求"""
    result = []
    now = datetime.now()
    for req_id, req in _pending_requests.items():
        elapsed = (now - req["start_time"]).total_seconds()
        result.append({
            "request_id": req_id,
            "bot_name": req["bot_name"],
            "user": req["user"],
            "message": req["message"],
            "elapsed_seconds": elapsed,
            "elapsed_str": f"{int(elapsed // 60)}分{int(elapsed % 60)}秒"
        })
    return sorted(result, key=lambda x: x["elapsed_seconds"], reverse=True)


async def get_pending_list() -> str:
    """获取正在处理的请求"""
    pending = get_pending_requests()
    
    if not pending:
        return "✅ 当前没有正在处理的请求"
    
    lines = [f"⏳ 正在处理的请求 ({len(pending)} 个)\n"]
    for i, req in enumerate(pending, 1):
        lines.append(f"{i}. {req['bot_name']}")
        lines.append(f"   用户: {req['user']}")
        lines.append(f"   消息: {req['message']}")
        lines.append(f"   等待: {req['elapsed_str']}")
        lines.append("")
    
    return "\n".join(lines)


async def get_recent_logs(limit: int = 10) -> str:
    """获取最近的日志"""
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            stmt = (
                select(ForwardLog)
                .order_by(ForwardLog.timestamp.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            logs = result.scalars().all()
        
        if not logs:
            return "📭 暂无日志"
        
        lines = [f"📋 最近 {len(logs)} 条日志\n"]
        for log in logs:
            status_icon = "✅" if log.status == "success" else "❌"
            time_str = log.timestamp.strftime("%H:%M:%S")
            duration_str = f"{log.duration_ms}ms" if log.duration_ms else "-"
            lines.append(f"{status_icon} [{time_str}] {log.bot_name or 'Unknown'}")
            lines.append(f"   消息: {(log.content or '')[:30]}...")
            lines.append(f"   耗时: {duration_str}")
            lines.append("")
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"⚠️ 获取日志失败: {e}"


async def get_error_logs(limit: int = 5) -> str:
    """获取最近的错误日志"""
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            stmt = (
                select(ForwardLog)
                .where(ForwardLog.status != "success")
                .order_by(ForwardLog.timestamp.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            logs = result.scalars().all()
        
        if not logs:
            return "✅ 暂无错误"
        
        lines = [f"⚠️ 最近 {len(logs)} 条错误\n"]
        for log in logs:
            time_str = log.timestamp.strftime("%m-%d %H:%M")
            lines.append(f"[{time_str}] {log.bot_name or 'Unknown'}")
            lines.append(f"  错误: {(log.error or '未知错误')[:50]}")
            lines.append("")
        
        return "\n".join(lines)
    
    except Exception as e:
        return f"⚠️ 获取错误日志失败: {e}"


# ============== 运维命令 ==============

async def check_agents_health() -> str:
    """检查所有 Agent 的可达性"""
    bots = config.bots
    if not bots:
        return "📭 暂无配置的 Bot"
    
    results = []
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        for bot in bots.values():
            if not bot.enabled:
                results.append(f"⏸️ {bot.name}: 已禁用")
                continue
            
            url = bot.forward_config.get_url()
            if not url:
                results.append(f"⚠️ {bot.name}: URL 未配置")
                continue
            
            try:
                # 尝试 HEAD 请求
                start = datetime.now()
                response = await client.head(url)
                elapsed = (datetime.now() - start).total_seconds() * 1000
                
                if response.status_code < 500:
                    results.append(f"✅ {bot.name}: {int(elapsed)}ms")
                else:
                    results.append(f"⚠️ {bot.name}: HTTP {response.status_code}")
            except httpx.TimeoutException:
                results.append(f"❌ {bot.name}: 超时")
            except Exception as e:
                results.append(f"❌ {bot.name}: {type(e).__name__}")
    
    return "🏥 Agent 健康检查\n\n" + "\n".join(results)
