"""
管理 API 路由

/admin/* 相关接口
"""
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pathlib import Path

from ..config import config
from ..database import get_db_manager
from ..repository import get_forward_log_repository, get_user_project_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ============== 请求日志（持久化到数据库） ==============

@dataclass
class RequestLogData:
    """请求日志数据（用于创建日志）"""
    chat_id: str
    from_user_id: str
    from_user_name: str
    content: str
    target_url: str
    msg_type: str = "text"
    bot_key: Optional[str] = None
    bot_name: Optional[str] = None
    session_id: Optional[str] = None
    status: str = "pending"
    response: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0


async def add_request_log(log_data: RequestLogData) -> int | None:
    """
    添加请求日志到数据库
    
    Returns:
        日志 ID，用于后续更新响应信息
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            log = await repo.create(
                chat_id=log_data.chat_id,
                from_user_id=log_data.from_user_id,
                from_user_name=log_data.from_user_name,
                content=log_data.content,
                target_url=log_data.target_url,
                msg_type=log_data.msg_type,
                bot_key=log_data.bot_key,
                bot_name=log_data.bot_name,
                session_id=log_data.session_id,
                status=log_data.status,
                response=log_data.response,
                error=log_data.error,
                duration_ms=log_data.duration_ms,
            )
            return log.id
    except Exception as e:
        logger.error(f"添加请求日志失败: {e}")
        return None


async def update_request_log(
    log_id: int,
    status: str,
    response: str = None,
    error: str = None,
    session_id: str = None,
    duration_ms: int = None,
):
    """更新请求日志的响应信息"""
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            await repo.update_response(
                log_id=log_id,
                status=status,
                response=response,
                error=error,
                session_id=session_id,
                duration_ms=duration_ms,
            )
    except Exception as e:
        logger.error(f"更新请求日志失败: {e}")


# ============== 静态文件 ==============

STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("")
async def admin_page():
    """管理台页面"""
    admin_html = STATIC_DIR / "admin.html"
    if admin_html.exists():
        return FileResponse(admin_html)
    return {"error": "Admin page not found"}


@router.get("/user-projects/page")
async def user_projects_page():
    """用户项目管理页面"""
    user_projects_html = STATIC_DIR / "user-projects.html"
    if user_projects_html.exists():
        return FileResponse(user_projects_html)
    return {"error": "User projects page not found"}


# ============== 状态和配置 API ==============

@router.get("/status")
async def admin_status():
    """获取服务状态（管理台用）"""
    return {
        "service": "Forward Service",
        "version": "3.0.0",
        "config": {
            "default_bot_key": config.default_bot_key[:10] + "..." if config.default_bot_key else None,
            "bots_count": len(config.bots),
            "timeout": config.timeout,
            "port": config.port
        },
        "stats": {
            "total_requests": len(request_logs),
            "recent_success": sum(1 for log in request_logs if log.status == "success"),
            "recent_error": sum(1 for log in request_logs if log.status == "error")
        }
    }


@router.get("/config")
async def get_config():
    """获取完整配置（管理台用）"""
    return config.get_config_dict()


@router.put("/config")
async def update_config(request: Request):
    """更新完整配置（管理台用）"""
    try:
        data = await request.json()
        result = await config.update_from_dict(data)
        return result
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return {"success": False, "error": str(e)}


@router.post("/config/reload")
async def reload_config():
    """重新加载配置"""
    return await config.reload_config()


# ============== 兼容性 API（旧版规则管理） ==============

@router.get("/rules")
async def admin_rules():
    """
    获取所有 Bot 配置（兼容旧 API）
    
    为了与旧版管理台兼容，将 bots 格式转换为类似 rules 的格式
    以 bot_key 作为 key，bot 配置作为 value
    """
    bots_dict = {}
    
    for bot_key, bot in config.bots.items():
        bots_dict[bot_key] = {
            "url_template": bot.forward_config.url_template,
            "agent_id": bot.forward_config.agent_id,
            "api_key": bot.forward_config.api_key,
            "name": bot.name,
            "timeout": bot.forward_config.timeout,
            "bot_name": bot.name,
            "description": bot.description,
            "access_mode": bot.access_control.mode,
            "enabled": bot.enabled,
            "is_default": bot_key == config.default_bot_key
        }
    
    return {
        "default_url": config.default_bot_key,
        "default_bot_key": config.default_bot_key,
        "rules": bots_dict,
        "bots": bots_dict
    }


@router.get("/logs")
async def admin_logs(limit: int = 100):
    """获取最近的请求日志（管理台用）"""
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            logs = await repo.get_recent(limit=limit)
            total = await repo.count()
            
            return {
                "total": total,
                "logs": [log.to_dict() for log in logs]
            }
    except Exception as e:
        logger.error(f"获取日志失败: {e}")
        return {
            "total": 0,
            "logs": [],
            "error": str(e)
        }


@router.get("/mode")
async def get_mode():
    """获取当前配置模式（管理台用）"""
    return {
        "mode": "database",
        "supports_bot_api": True,
        "version": "3.0.0"
    }


# ============== 统计 API ==============

@router.get("/stats")
async def get_stats(days: int = 7):
    """
    获取日志统计数据
    
    Args:
        days: 统计最近多少天的数据，默认 7 天
    """
    from datetime import timedelta
    from sqlalchemy import func, case
    from ..models import ForwardLog
    
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_forward_log_repository(session)
            
            # 计算时间范围
            now = datetime.now(timezone.utc)
            start_date = now - timedelta(days=days)
            
            # 总数统计
            total_count = await repo.count()
            
            # 按状态统计
            from sqlalchemy import select
            status_stmt = (
                select(
                    ForwardLog.status,
                    func.count(ForwardLog.id).label('count')
                )
                .where(ForwardLog.timestamp >= start_date)
                .group_by(ForwardLog.status)
            )
            status_result = await session.execute(status_stmt)
            status_counts = {row.status: row.count for row in status_result}
            
            # 按 Bot 统计
            bot_stmt = (
                select(
                    ForwardLog.bot_name,
                    ForwardLog.bot_key,
                    func.count(ForwardLog.id).label('count')
                )
                .where(ForwardLog.timestamp >= start_date)
                .group_by(ForwardLog.bot_name, ForwardLog.bot_key)
            )
            bot_result = await session.execute(bot_stmt)
            bot_stats = [
                {"bot_name": row.bot_name or "Unknown", "bot_key": row.bot_key, "count": row.count}
                for row in bot_result
            ]
            
            # 平均响应时间
            avg_stmt = (
                select(func.avg(ForwardLog.duration_ms))
                .where(ForwardLog.timestamp >= start_date)
                .where(ForwardLog.status == "success")
            )
            avg_result = await session.execute(avg_stmt)
            avg_duration = avg_result.scalar() or 0
            
            # 每日统计（最近 N 天）
            daily_stats = []
            for i in range(days):
                day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)
                
                day_stmt = (
                    select(func.count(ForwardLog.id))
                    .where(ForwardLog.timestamp >= day_start)
                    .where(ForwardLog.timestamp < day_end)
                )
                day_result = await session.execute(day_stmt)
                day_count = day_result.scalar() or 0
                
                daily_stats.append({
                    "date": day_start.strftime("%Y-%m-%d"),
                    "count": day_count
                })
            
            # 反转顺序（从旧到新）
            daily_stats.reverse()
            
            # 活跃用户 Top 10
            user_stmt = (
                select(
                    ForwardLog.from_user_name,
                    ForwardLog.from_user_id,
                    func.count(ForwardLog.id).label('count')
                )
                .where(ForwardLog.timestamp >= start_date)
                .group_by(ForwardLog.from_user_name, ForwardLog.from_user_id)
                .order_by(func.count(ForwardLog.id).desc())
                .limit(10)
            )
            user_result = await session.execute(user_stmt)
            top_users = [
                {"user_name": row.from_user_name or row.from_user_id, "count": row.count}
                for row in user_result
            ]
            
            # 计算成功率
            success_count = status_counts.get("success", 0)
            error_count = status_counts.get("error", 0) + status_counts.get("timeout", 0)
            total_in_period = success_count + error_count
            success_rate = (success_count / total_in_period * 100) if total_in_period > 0 else 100
            
            return {
                "success": True,
                "period_days": days,
                "total_count": total_count,
                "period_count": sum(status_counts.values()),
                "status_counts": status_counts,
                "success_rate": round(success_rate, 2),
                "avg_duration_ms": round(avg_duration, 2),
                "bot_stats": bot_stats,
                "daily_stats": daily_stats,
                "top_users": top_users,
            }
    except Exception as e:
        logger.error(f"获取统计数据失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


# ============== 系统配置 API ==============

@router.get("/system/admin-users")
async def get_admin_users():
    """获取管理员用户列表"""
    import json
    from ..repository import get_system_config_repository
    
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_system_config_repository(session)
            admin_users_json = await repo.get_value("admin_users", "[]")
            admin_users = json.loads(admin_users_json)
            
            return {
                "success": True,
                "admin_users": admin_users
            }
    except Exception as e:
        logger.error(f"获取管理员列表失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "admin_users": []
        }


@router.put("/system/admin-users")
async def update_admin_users(request: Request):
    """
    更新管理员用户列表
    
    请求体格式:
    {
        "admin_users": ["user_id_1", "alias_1", ...]
    }
    """
    import json
    from ..repository import get_system_config_repository
    
    try:
        data = await request.json()
        admin_users = data.get("admin_users", [])
        
        # 验证格式
        if not isinstance(admin_users, list):
            return {"success": False, "error": "admin_users 必须是数组"}
        
        # 过滤空值
        admin_users = [u.strip() for u in admin_users if u and u.strip()]
        
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_system_config_repository(session)
            await repo.set(
                key="admin_users",
                value=json.dumps(admin_users),
                description="管理员用户列表（支持 user_id 或 alias）"
            )
            
            return {
                "success": True,
                "admin_users": admin_users,
                "message": f"已更新 {len(admin_users)} 个管理员"
            }
    except Exception as e:
        logger.error(f"更新管理员列表失败: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ============== 用户项目配置 API ==============

@router.get("/user-projects/by-bot")
async def get_user_projects_by_bot(
    bot_key: str,
    enabled_only: bool = False
):
    """
    获取某个 Bot 下的所有用户配置

    Args:
        bot_key: Bot Key
        enabled_only: 是否只返回启用的配置
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)
            projects = await repo.get_all_by_bot_key(bot_key, enabled_only=enabled_only)

            # 按 chat_id 分组
            users: dict[str, list[dict]] = {}
            for p in projects:
                if p.chat_id not in users:
                    users[p.chat_id] = []
                users[p.chat_id].append(p.to_dict())

            return {
                "success": True,
                "bot_key": bot_key,
                "users": users,
                "total_users": len(users),
                "total_projects": len(projects)
            }
    except Exception as e:
        logger.error(f"获取 Bot 用户配置失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "users": {}
        }


@router.get("/user-projects")
async def get_user_projects(
    bot_key: str,
    chat_id: str
):
    """
    获取指定用户在指定 Bot 下的所有项目配置

    Args:
        bot_key: Bot Key
        chat_id: 用户/群 ID
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)
            projects = await repo.get_user_projects(bot_key, chat_id, enabled_only=False)

            return {
                "success": True,
                "bot_key": bot_key,
                "chat_id": chat_id,
                "projects": [p.to_dict() for p in projects],
                "count": len(projects)
            }
    except Exception as e:
        logger.error(f"获取用户项目配置失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "projects": []
        }


@router.post("/user-projects")
async def create_user_project(request: Request):
    """
    创建用户项目配置

    请求体格式:
    {
        "bot_key": "bot1",
        "chat_id": "user123",
        "project_id": "test",
        "url_template": "https://api.test.com/webhook",
        "api_key": "sk-test-123",
        "project_name": "测试环境",
        "timeout": 300,
        "is_default": false
    }
    """
    try:
        data = await request.json()

        # 验证必填字段
        required_fields = ["bot_key", "chat_id", "project_id", "url_template"]
        for field in required_fields:
            if field not in data:
                return {"success": False, "error": f"缺少必填字段: {field}"}

        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)

            # 检查是否已存在
            existing = await repo.get_by_project_id(
                data["bot_key"],
                data["chat_id"],
                data["project_id"]
            )
            if existing:
                return {
                    "success": False,
                    "error": f"项目 {data['project_id']} 已存在"
                }

            # 创建项目配置
            project = await repo.create(
                bot_key=data["bot_key"],
                chat_id=data["chat_id"],
                project_id=data["project_id"],
                url_template=data["url_template"],
                api_key=data.get("api_key"),
                project_name=data.get("project_name"),
                timeout=data.get("timeout", 300),
                is_default=data.get("is_default", False),
                enabled=data.get("enabled", True)
            )

            return {
                "success": True,
                "message": "项目配置创建成功",
                "project": project.to_dict()
            }
    except Exception as e:
        logger.error(f"创建用户项目配置失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


@router.put("/user-projects/{project_id}")
async def update_user_project(
    project_id: int,
    request: Request
):
    """
    更新用户项目配置

    Args:
        project_id: 项目配置 ID（数据库主键）

    请求体格式:
    {
        "url_template": "https://new-url.com",
        "api_key": "new-key",
        "project_name": "新名称",
        "timeout": 30,
        "is_default": true,
        "enabled": true
    }
    """
    try:
        data = await request.json()

        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)

            # 更新项目配置
            project = await repo.update(
                config_id=project_id,
                url_template=data.get("url_template"),
                api_key=data.get("api_key"),
                project_name=data.get("project_name"),
                timeout=data.get("timeout"),
                is_default=data.get("is_default"),
                enabled=data.get("enabled")
            )

            if not project:
                return {
                    "success": False,
                    "error": f"项目配置 ID {project_id} 不存在"
                }

            return {
                "success": True,
                "message": "项目配置更新成功",
                "project": project.to_dict()
            }
    except Exception as e:
        logger.error(f"更新用户项目配置失败: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


@router.delete("/user-projects/{project_id}")
async def delete_user_project(project_id: int):
    """
    删除用户项目配置

    Args:
        project_id: 项目配置 ID（数据库主键）
    """
    try:
        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)

            success = await repo.delete(project_id)

            if not success:
                return {
                    "success": False,
                    "error": f"项目配置 ID {project_id} 不存在"
                }

            return {
                "success": True,
                "message": "项目配置删除成功"
            }
    except Exception as e:
        logger.error(f"删除用户项目配置失败: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/user-projects/set-default")
async def set_default_user_project(request: Request):
    """
    设置用户的默认项目

    请求体格式:
    {
        "bot_key": "bot1",
        "chat_id": "user123",
        "project_id": "test"
    }
    """
    try:
        data = await request.json()

        # 验证必填字段
        required_fields = ["bot_key", "chat_id", "project_id"]
        for field in required_fields:
            if field not in data:
                return {"success": False, "error": f"缺少必填字段: {field}"}

        db_manager = get_db_manager()
        async with db_manager.get_session() as session:
            repo = get_user_project_repository(session)

            success = await repo.set_default(
                bot_key=data["bot_key"],
                chat_id=data["chat_id"],
                project_id=data["project_id"]
            )

            if not success:
                return {
                    "success": False,
                    "error": "设置默认项目失败，项目可能不存在"
                }

            return {
                "success": True,
                "message": f"已将项目 {data['project_id']} 设为默认"
            }
    except Exception as e:
        logger.error(f"设置默认项目失败: {e}")
        return {
            "success": False,
            "error": str(e)
        }
