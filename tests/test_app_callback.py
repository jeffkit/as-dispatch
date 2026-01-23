"""
app.py callback 处理单元测试

测试多 Bot 支持的回调处理逻辑
"""
import pytest
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from forward_service.config import ConfigDB as ConfigV2, BotConfig, ForwardConfig, AccessControl


class TestCallbackBotKeyExtraction:
    """测试 Bot Key 提取逻辑"""
    
    @pytest.mark.asyncio
    async def test_extract_bot_key_from_callback_data(self):
        """测试从回调数据中提取 bot_key"""
        config = ConfigV2()
        
        # 模拟回调数据
        callback_data = {
            "chatid": "wokSFfCgAAtest",
            "chattype": "group",
            "msgtype": "text",
            "from": {"userid": "user1", "name": "User 1"},
            "webhook_url": "http://in.qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test_bot_key_123",
            "text": {"content": "test message"}
        }
        
        # 提取 bot_key
        webhook_url = callback_data.get("webhook_url", "")
        bot_key = config.extract_bot_key_from_webhook_url(webhook_url)
        
        assert bot_key == "test_bot_key_123"


class TestCallbackAccessControl:
    """测试回调中的访问控制逻辑"""
    
    def test_allow_all_access(self):
        """测试 allow_all 模式"""
        bot = BotConfig(
            bot_key="bot1",
            name="Bot 1",
            access_control=AccessControl(mode="allow_all")
        )
        
        config = ConfigV2()
        allowed, reason = config.check_access(bot, "any_user")
        
        assert allowed is True
        assert reason == ""
    
    def test_whitelist_access_allowed(self):
        """测试白名单 - 允许访问"""
        bot = BotConfig(
            bot_key="bot1",
            name="Bot 1",
            access_control=AccessControl(
                mode="whitelist",
                whitelist=["user1", "user2"]
            )
        )
        
        config = ConfigV2()
        allowed, reason = config.check_access(bot, "user1")
        
        assert allowed is True
    
    def test_whitelist_access_denied(self):
        """测试白名单 - 拒绝访问"""
        bot = BotConfig(
            bot_key="bot1",
            name="Bot 1",
            access_control=AccessControl(
                mode="whitelist",
                whitelist=["user1", "user2"]
            )
        )
        
        config = ConfigV2()
        allowed, reason = config.check_access(bot, "user3")
        
        assert allowed is False
        assert "没有权限" in reason
    
    def test_blacklist_access_allowed(self):
        """测试黑名单 - 允许访问"""
        bot = BotConfig(
            bot_key="bot1",
            name="Bot 1",
            access_control=AccessControl(
                mode="blacklist",
                blacklist=["bad_user"]
            )
        )
        
        config = ConfigV2()
        allowed, reason = config.check_access(bot, "good_user")
        
        assert allowed is True
    
    def test_blacklist_access_denied(self):
        """测试黑名单 - 拒绝访问"""
        bot = BotConfig(
            bot_key="bot1",
            name="Bot 1",
            access_control=AccessControl(
                mode="blacklist",
                blacklist=["bad_user"]
            )
        )
        
        config = ConfigV2()
        allowed, reason = config.check_access(bot, "bad_user")
        
        assert allowed is False
        assert "没有权限" in reason
    
    def test_disabled_bot_access(self):
        """测试禁用的 Bot"""
        bot = BotConfig(
            bot_key="bot1",
            name="Bot 1",
            access_control=AccessControl(mode="allow_all"),
            enabled=False
        )
        
        config = ConfigV2()
        allowed, reason = config.check_access(bot, "any_user")
        
        assert allowed is False
        assert "禁用" in reason


class TestCallbackBotSelection:
    """测试回调中的 Bot 选择逻辑（使用内存缓存）"""
    
    def test_get_bot_by_key(self):
        """测试根据 bot_key 获取 Bot (从内存缓存)"""
        config = ConfigV2()
        # 直接设置内存缓存
        config.bots = {
            "bot1": BotConfig(bot_key="bot1", name="Bot 1"),
            "bot2": BotConfig(bot_key="bot2", name="Bot 2")
        }
        
        # 从内存缓存获取
        bot = config.bots.get("bot1")
        assert bot is not None
        assert bot.name == "Bot 1"
    
    def test_fallback_to_default_bot(self):
        """测试回退到默认 Bot"""
        config = ConfigV2()
        config.default_bot_key = "default"
        config.bots = {
            "default": BotConfig(bot_key="default", name="Default Bot"),
            "bot1": BotConfig(bot_key="bot1", name="Bot 1")
        }
        
        # 不存在的 bot_key，应该回退到默认
        bot = config.bots.get("non_existent") or config.bots.get(config.default_bot_key)
        assert bot is not None
        assert bot.name == "Default Bot"
    
    def test_no_default_bot(self):
        """测试没有默认 Bot 的情况"""
        config = ConfigV2()
        config.default_bot_key = ""
        config.bots = {
            "bot1": BotConfig(bot_key="bot1", name="Bot 1")
        }
        
        # 不存在的 bot_key，且无默认 Bot
        bot = config.get_bot_or_default("non_existent")
        assert bot is None


class TestCallbackMessageExtraction:
    """测试消息内容提取（已有功能，确保兼容性）"""
    
    def test_extract_text_message(self):
        """测试提取文本消息"""
        # 这个测试确保现有的 extract_content 函数继续工作
        from forward_service.utils import extract_content
        
        data = {
            "msgtype": "text",
            "text": {"content": "@Bot hello"}
        }
        
        content, image_url = extract_content(data)
        assert content == "hello"  # 应该去除 @Bot
        assert image_url is None
    
    def test_extract_image_message(self):
        """测试提取图片消息"""
        from forward_service.utils import extract_content
        
        data = {
            "msgtype": "image",
            "image": {"image_url": "https://example.com/image.png"}
        }
        
        content, image_url = extract_content(data)
        assert content is None
        assert image_url == "https://example.com/image.png"
    
    def test_extract_mixed_message(self):
        """测试提取混合消息（文本+图片）"""
        from forward_service.utils import extract_content
        
        data = {
            "msgtype": "mixed",
            "mixed_message": {
                "msg_item": [
                    {
                        "msg_type": "text",
                        "text": {"content": "@Bot text content"}
                    },
                    {
                        "msg_type": "image",
                        "image": {"image_url": "https://example.com/image.png"}
                    }
                ]
            }
        }
        
        content, image_url = extract_content(data)
        assert content == "text content"  # 应该去除 @Bot
        assert image_url == "https://example.com/image.png"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
