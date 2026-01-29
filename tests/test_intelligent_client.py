"""
企业微信智能机器人客户端单元测试

测试内容:
- XML 消息解析
- XML 响应构建（文本、流式、模板卡片）
- ID 生成
"""
import pytest
from forward_service.clients.wecom_intelligent import WeComIntelligentClient


class TestWeComIntelligentClient:
    """测试企微智能机器人客户端"""
    
    def setup_method(self):
        """每个测试方法前执行"""
        self.client = WeComIntelligentClient(bot_key="test-bot")
    
    # ============== XML 解析测试 ==============
    
    def test_parse_text_message(self):
        """测试解析文本消息"""
        xml = """<xml>
    <ToUserName><![CDATA[ww123]]></ToUserName>
    <FromUserName><![CDATA[user123]]></FromUserName>
    <CreateTime>1234567890</CreateTime>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[今天天气怎么样？]]></Content>
    <MsgId>1234567890123456</MsgId>
</xml>"""
        
        result = self.client.parse_xml(xml)
        
        assert result["ToUserName"] == "ww123"
        assert result["FromUserName"] == "user123"
        assert result["MsgType"] == "text"
        assert result["Content"] == "今天天气怎么样？"
        assert result["MsgId"] == "1234567890123456"
    
    def test_parse_event_message(self):
        """测试解析事件消息"""
        xml = """<xml>
    <ToUserName><![CDATA[ww123]]></ToUserName>
    <FromUserName><![CDATA[user123]]></FromUserName>
    <CreateTime>1234567890</CreateTime>
    <MsgType><![CDATA[event]]></MsgType>
    <Event><![CDATA[enter_session]]></Event>
    <EventKey><![CDATA[session_001]]></EventKey>
</xml>"""
        
        result = self.client.parse_xml(xml)
        
        assert result["MsgType"] == "event"
        assert result["Event"] == "enter_session"
        assert result["EventKey"] == "session_001"
    
    def test_parse_xml_bytes(self):
        """测试解析字节格式的 XML"""
        xml_bytes = b"""<xml>
    <ToUserName><![CDATA[ww123]]></ToUserName>
    <FromUserName><![CDATA[user123]]></FromUserName>
    <CreateTime>1234567890</CreateTime>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[hello]]></Content>
    <MsgId>123</MsgId>
</xml>"""
        
        result = self.client.parse_xml(xml_bytes)
        assert result["Content"] == "hello"
    
    def test_parse_invalid_xml(self):
        """测试解析无效 XML"""
        invalid_xml = "not a valid xml"
        
        with pytest.raises(ValueError, match="Invalid XML"):
            self.client.parse_xml(invalid_xml)
    
    # ============== XML 构建测试 ==============
    
    def test_build_text_xml(self):
        """测试构建文本消息 XML"""
        xml = self.client.build_text_xml(
            to_user="user123",
            from_user="ww123",
            content="你好！"
        )
        
        assert "<xml>" in xml
        assert "<MsgType><![CDATA[text]]></MsgType>" in xml
        assert "<ToUserName><![CDATA[user123]]></ToUserName>" in xml
        assert "<FromUserName><![CDATA[ww123]]></FromUserName>" in xml
        assert "<Content><![CDATA[你好！]]></Content>" in xml
        assert "<CreateTime>" in xml
    
    def test_build_stream_xml_basic(self):
        """测试构建基础流式消息 XML"""
        xml = self.client.build_stream_xml(
            to_user="user123",
            from_user="ww123",
            stream_id="stream_001",
            content="广州今天天气 29°C",
            finish=False
        )
        
        assert "<MsgType><![CDATA[stream]]></MsgType>" in xml
        assert "<Stream>" in xml
        assert "<Id><![CDATA[stream_001]]></Id>" in xml
        assert "<Finish>0</Finish>" in xml
        assert "<Content><![CDATA[广州今天天气 29°C]]></Content>" in xml
    
    def test_build_stream_xml_with_finish(self):
        """测试构建完成状态的流式消息"""
        xml = self.client.build_stream_xml(
            to_user="user123",
            from_user="ww123",
            stream_id="stream_001",
            content="完整消息",
            finish=True
        )
        
        assert "<Finish>1</Finish>" in xml
    
    def test_build_stream_xml_with_feedback(self):
        """测试构建带反馈 ID 的流式消息"""
        xml = self.client.build_stream_xml(
            to_user="user123",
            from_user="ww123",
            stream_id="stream_001",
            content="测试内容",
            finish=True,
            feedback_id="fb_stream_001"
        )
        
        assert "<Feedback>" in xml
        assert "<Id><![CDATA[fb_stream_001]]></Id>" in xml
    
    def test_build_stream_xml_with_images(self):
        """测试构建带图片的流式消息"""
        msg_items = [
            {
                "msgtype": "image",
                "image": {
                    "base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                    "md5": "abc123def456"
                }
            }
        ]
        
        xml = self.client.build_stream_xml(
            to_user="user123",
            from_user="ww123",
            stream_id="stream_001",
            content="这是图片",
            finish=True,
            msg_items=msg_items
        )
        
        assert "<MsgItem>" in xml
        assert "<MsgType><![CDATA[image]]></MsgType>" in xml
        assert "<Base64>" in xml
        assert "<Md5><![CDATA[abc123def456]]></Md5>" in xml
    
    def test_build_template_card_xml(self):
        """测试构建模板卡片 XML"""
        card_data = {
            "card_type": "text_notice",
            "title": "测试卡片",
            "desc": "这是一个测试卡片"
        }
        
        xml = self.client.build_template_card_xml(
            to_user="user123",
            from_user="ww123",
            card_data=card_data,
            feedback_id="fb_card_001"
        )
        
        assert "<MsgType><![CDATA[template_card]]></MsgType>" in xml
        assert "<TemplateCard>" in xml
        assert "<CardType><![CDATA[text_notice]]></CardType>" in xml
        assert "<Feedback>" in xml
    
    # ============== 辅助方法测试 ==============
    
    def test_generate_stream_id(self):
        """测试生成流式消息 ID"""
        stream_id = self.client.generate_stream_id("user123", timestamp=1234567890)
        
        assert stream_id == "stream_user123_1234567890"
    
    def test_generate_stream_id_auto_timestamp(self):
        """测试自动生成时间戳的流式消息 ID"""
        stream_id = self.client.generate_stream_id("user123")
        
        assert stream_id.startswith("stream_user123_")
        assert len(stream_id) > 20  # stream_user123_1234567890
    
    def test_generate_feedback_id(self):
        """测试生成反馈 ID"""
        feedback_id = self.client.generate_feedback_id("stream_001")
        
        assert feedback_id == "fb_stream_001"
    
    # ============== 边界情况测试 ==============
    
    def test_parse_xml_with_missing_fields(self):
        """测试解析缺少字段的 XML"""
        xml = """<xml>
    <ToUserName><![CDATA[ww123]]></ToUserName>
    <MsgType><![CDATA[text]]></MsgType>
</xml>"""
        
        result = self.client.parse_xml(xml)
        
        assert result["ToUserName"] == "ww123"
        assert result["FromUserName"] is None
        assert result["Content"] is None
    
    def test_build_stream_xml_empty_content(self):
        """测试构建空内容的流式消息"""
        xml = self.client.build_stream_xml(
            to_user="user123",
            from_user="ww123",
            stream_id="stream_001",
            content="",
            finish=True
        )
        
        assert "<Content><![CDATA[]]></Content>" in xml
    
    def test_build_stream_xml_special_characters(self):
        """测试构建包含特殊字符的流式消息"""
        content_with_special = "测试 <>&\"' 特殊字符"
        
        xml = self.client.build_stream_xml(
            to_user="user123",
            from_user="ww123",
            stream_id="stream_001",
            content=content_with_special,
            finish=True
        )
        
        # CDATA 应该正确处理特殊字符
        assert content_with_special in xml
        assert "<Content><![CDATA[" in xml
