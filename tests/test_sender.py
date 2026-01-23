"""
sender.py 消息发送模块单元测试

测试 send_to_wecom 和 send_reply 函数
"""
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, patch, AsyncMock


class TestSendToWecom:
    """测试 send_to_wecom 函数"""

    def test_send_text_message_success(self):
        """测试成功发送文本消息"""
        from forward_service.sender import send_to_wecom

        mock_bot = MagicMock()
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={"errcode": 0, "errmsg": "ok"})
        mock_bot.text = MagicMock(return_value=mock_response)

        with patch('forward_service.sender.Bot', return_value=mock_bot):
            result = send_to_wecom(
                message="Hello World",
                chat_id="test_chat_123",
                msg_type="text",
                bot_key="test_key"
            )

            assert result["errcode"] == 0
            mock_bot.text.assert_called_once()

    def test_send_markdown_message_success(self):
        """测试成功发送 Markdown 消息"""
        from forward_service.sender import send_to_wecom

        mock_bot = MagicMock()
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={"errcode": 0, "errmsg": "ok"})
        mock_bot.markdown = MagicMock(return_value=mock_response)

        with patch('forward_service.sender.Bot', return_value=mock_bot):
            result = send_to_wecom(
                message="# Hello\n\n**World**",
                chat_id="test_chat_123",
                msg_type="markdown",
                bot_key="test_key"
            )

            assert result["errcode"] == 0
            mock_bot.markdown.assert_called_once()

    def test_send_message_no_bot_key(self):
        """测试没有 bot_key 时抛出异常"""
        from forward_service.sender import send_to_wecom

        with patch('forward_service.sender.config') as mock_config:
            mock_config.bot_key = None

            with pytest.raises(ValueError, match="未配置 bot_key"):
                send_to_wecom(
                    message="Hello",
                    chat_id="test_chat",
                    msg_type="text",
                    bot_key=None
                )

    def test_send_message_use_default_bot_key(self):
        """测试使用默认 bot_key"""
        from forward_service.sender import send_to_wecom

        mock_bot = MagicMock()
        mock_response = {"errcode": 0, "errmsg": "ok"}
        mock_bot.text = MagicMock(return_value=mock_response)

        with patch('forward_service.sender.Bot', return_value=mock_bot), \
             patch('forward_service.sender.config') as mock_config:
            mock_config.bot_key = "default_key"

            result = send_to_wecom(
                message="Hello",
                chat_id="test_chat",
                msg_type="text",
                bot_key=None
            )

            assert result["errcode"] == 0

    def test_send_message_error_response(self):
        """测试发送消息返回错误"""
        from forward_service.sender import send_to_wecom

        mock_bot = MagicMock()
        mock_response = MagicMock()
        mock_response.json = MagicMock(return_value={
            "errcode": 93000,
            "errmsg": "access token is invalid"
        })
        mock_bot.text = MagicMock(return_value=mock_response)

        with patch('forward_service.sender.Bot', return_value=mock_bot):
            result = send_to_wecom(
                message="Hello",
                chat_id="test_chat",
                msg_type="text",
                bot_key="test_key"
            )

            assert result["errcode"] == 93000

    def test_send_message_exception(self):
        """测试发送消息抛出异常"""
        from forward_service.sender import send_to_wecom

        mock_bot = MagicMock()
        mock_bot.text = MagicMock(side_effect=Exception("Network error"))

        with patch('forward_service.sender.Bot', return_value=mock_bot):
            with pytest.raises(Exception, match="Network error"):
                send_to_wecom(
                    message="Hello",
                    chat_id="test_chat",
                    msg_type="text",
                    bot_key="test_key"
                )

    def test_send_message_dict_response(self):
        """测试返回 dict 类型的响应"""
        from forward_service.sender import send_to_wecom

        mock_bot = MagicMock()
        mock_bot.text = MagicMock(return_value={"errcode": 0, "errmsg": "ok"})

        with patch('forward_service.sender.Bot', return_value=mock_bot):
            result = send_to_wecom(
                message="Hello",
                chat_id="test_chat",
                msg_type="text",
                bot_key="test_key"
            )

            assert result["errcode"] == 0

    def test_send_message_no_json_method(self):
        """测试响应对象没有 json 方法"""
        from forward_service.sender import send_to_wecom

        mock_bot = MagicMock()
        mock_response = "plain string response"
        mock_bot.text = MagicMock(return_value=mock_response)

        with patch('forward_service.sender.Bot', return_value=mock_bot):
            result = send_to_wecom(
                message="Hello",
                chat_id="test_chat",
                msg_type="text",
                bot_key="test_key"
            )

            assert result["errcode"] == 0
            assert result["errmsg"] == "ok"


class TestSendReply:
    """测试 send_reply 异步函数"""

    @pytest.mark.asyncio
    async def test_send_reply_success(self):
        """测试成功发送回复"""
        from forward_service.sender import send_reply

        with patch('forward_service.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 0, "errmsg": "ok"}

            result = await send_reply(
                chat_id="test_chat",
                message="Hello",
                msg_type="text",
                bot_key="test_key"
            )

            assert result["success"] is True
            mock_send.assert_called_once_with(
                message="Hello",
                chat_id="test_chat",
                msg_type="text",
                bot_key="test_key"
            )

    @pytest.mark.asyncio
    async def test_send_reply_failure(self):
        """测试发送回复失败"""
        from forward_service.sender import send_reply

        with patch('forward_service.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 93000, "errmsg": "invalid token"}

            result = await send_reply(
                chat_id="test_chat",
                message="Hello",
                msg_type="text",
                bot_key="test_key"
            )

            assert result["success"] is False
            assert "invalid token" in result["error"]

    @pytest.mark.asyncio
    async def test_send_reply_exception(self):
        """测试发送回复抛出异常"""
        from forward_service.sender import send_reply

        with patch('forward_service.sender.send_to_wecom') as mock_send:
            mock_send.side_effect = Exception("Connection error")

            result = await send_reply(
                chat_id="test_chat",
                message="Hello",
                msg_type="text"
            )

            assert result["success"] is False
            assert "Connection error" in result["error"]

    @pytest.mark.asyncio
    async def test_send_reply_markdown(self):
        """测试发送 Markdown 回复"""
        from forward_service.sender import send_reply

        with patch('forward_service.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 0}

            result = await send_reply(
                chat_id="test_chat",
                message="# Title\n\n**Bold**",
                msg_type="markdown",
                bot_key="test_key"
            )

            assert result["success"] is True
            mock_send.assert_called_once_with(
                message="# Title\n\n**Bold**",
                chat_id="test_chat",
                msg_type="markdown",
                bot_key="test_key"
            )

    @pytest.mark.asyncio
    async def test_send_reply_default_msg_type(self):
        """测试默认消息类型为 text"""
        from forward_service.sender import send_reply

        with patch('forward_service.sender.send_to_wecom') as mock_send:
            mock_send.return_value = {"errcode": 0}

            await send_reply(
                chat_id="test_chat",
                message="Hello"
            )

            mock_send.assert_called_once_with(
                message="Hello",
                chat_id="test_chat",
                msg_type="text",
                bot_key=None
            )
