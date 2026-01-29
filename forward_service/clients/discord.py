"""
Discord Bot 客户端

封装 Discord Bot API 的常用操作:
- 启动 Bot 并监听消息
- 发送消息
- 处理 DM (Direct Message)
"""
import logging
from typing import Optional, Callable
import discord

logger = logging.getLogger(__name__)


class DiscordBotClient(discord.Client):
    """Discord Bot 客户端，处理 DM 消息"""
    
    def __init__(
        self,
        bot_token: str,
        on_message_callback: Callable,
        bot_key: str
    ):
        """
        初始化 Discord 客户端
        
        Args:
            bot_token: Discord Bot Token
            on_message_callback: 消息处理回调函数
            bot_key: Bot 标识（用于日志）
        """
        # 配置 Intents
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.dm_messages = True
        intents.guilds = True  # 用于未来扩展频道功能
        
        super().__init__(intents=intents)
        self.bot_token = bot_token
        self.on_message_callback = on_message_callback
        self.bot_key = bot_key
    
    async def on_ready(self):
        """Bot 就绪事件"""
        logger.info(f"✅ Discord Bot 已启动: {self.user} (ID: {self.user.id})")
        logger.info(f"   Bot Key: {self.bot_key}")
        logger.info(f"   Guilds: {len(self.guilds)}")
    
    async def on_message(self, message: discord.Message):
        """
        处理消息事件
        
        Args:
            message: Discord 消息对象
        """
        # 忽略自己发的消息
        if message.author == self.user:
            return
        
        # 只处理 DM（私信）
        if not isinstance(message.channel, discord.DMChannel):
            logger.debug(f"忽略非 DM 消息: channel_type={type(message.channel).__name__}")
            return
        
        logger.info(f"📨 收到 DM: user={message.author} (ID: {message.author.id})")
        
        # 调用回调处理消息
        try:
            await self.on_message_callback(message, self)
        except Exception as e:
            logger.error(f"处理消息回调失败: {e}", exc_info=True)
    
    async def send_dm(
        self,
        user_id: int,
        content: str,
        embed: Optional[discord.Embed] = None
    ) -> Optional[discord.Message]:
        """
        发送 DM 消息给用户
        
        Args:
            user_id: 用户 ID
            content: 消息内容
            embed: Discord Embed 对象（可选）
        
        Returns:
            发送的消息对象，失败返回 None
        """
        try:
            user = await self.fetch_user(user_id)
            if not user:
                logger.error(f"无法找到用户: {user_id}")
                return None
            
            # 创建 DM 频道
            dm_channel = await user.create_dm()
            
            # 发送消息
            return await dm_channel.send(content=content, embed=embed)
        
        except discord.Forbidden:
            logger.error(f"无权限向用户发送 DM: {user_id}")
            return None
        except Exception as e:
            logger.error(f"发送 DM 失败: {e}", exc_info=True)
            return None
    
    async def start_bot(self):
        """启动 Bot（阻塞式）"""
        try:
            logger.info(f"正在启动 Discord Bot: {self.bot_key}")
            await self.start(self.bot_token)
        except discord.LoginFailure:
            logger.error("Discord Bot Token 无效，登录失败")
            raise
        except Exception as e:
            logger.error(f"启动 Discord Bot 失败: {e}", exc_info=True)
            raise
