"""
企业微信智能机器人客户端

封装企业微信智能机器人 API 的常用操作:
- XML 消息解析
- XML 响应构建（流式消息、模板卡片）
- 加解密支持
"""
import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class WeComIntelligentClient:
    """企业微信智能机器人客户端"""
    
    def __init__(self, bot_key: str):
        """
        初始化客户端
        
        Args:
            bot_key: Bot 标识（用于日志）
        """
        self.bot_key = bot_key
    
    # ============== XML 解析 ==============
    
    def parse_xml(self, xml_data: bytes | str) -> Dict[str, Any]:
        """
        解析企微 XML 回调消息
        
        Args:
            xml_data: XML 字符串或字节
        
        Returns:
            解析后的消息字典
        """
        try:
            if isinstance(xml_data, bytes):
                xml_data = xml_data.decode('utf-8')
            
            root = ET.fromstring(xml_data)
            
            # 提取基础字段
            message = {
                "ToUserName": self._get_text(root, "ToUserName"),
                "FromUserName": self._get_text(root, "FromUserName"),
                "CreateTime": self._get_text(root, "CreateTime"),
                "MsgType": self._get_text(root, "MsgType"),
                "MsgId": self._get_text(root, "MsgId"),
            }
            
            # 根据消息类型提取内容
            msg_type = message["MsgType"]
            
            if msg_type == "text":
                message["Content"] = self._get_text(root, "Content")
            elif msg_type == "event":
                message["Event"] = self._get_text(root, "Event")
                message["EventKey"] = self._get_text(root, "EventKey")
            
            return message
        
        except Exception as e:
            logger.error(f"解析 XML 失败: {e}", exc_info=True)
            raise ValueError(f"Invalid XML: {e}")
    
    def _get_text(self, element: ET.Element, tag: str) -> Optional[str]:
        """获取 XML 标签的文本内容"""
        child = element.find(tag)
        return child.text if child is not None else None
    
    # ============== XML 构建 ==============
    
    def build_text_xml(
        self,
        to_user: str,
        from_user: str,
        content: str
    ) -> str:
        """
        构建文本消息 XML
        
        Args:
            to_user: 接收用户 ID
            from_user: 发送用户 ID
            content: 消息内容
        
        Returns:
            XML 字符串
        """
        timestamp = int(time.time())
        
        xml = f"""<xml>
    <ToUserName><![CDATA[{to_user}]]></ToUserName>
    <FromUserName><![CDATA[{from_user}]]></FromUserName>
    <CreateTime>{timestamp}</CreateTime>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[{content}]]></Content>
</xml>"""
        
        return xml
    
    def build_stream_xml(
        self,
        to_user: str,
        from_user: str,
        stream_id: str,
        content: str,
        finish: bool,
        feedback_id: Optional[str] = None,
        msg_items: Optional[list] = None
    ) -> str:
        """
        构建流式消息 XML
        
        Args:
            to_user: 接收用户 ID
            from_user: 发送用户 ID
            stream_id: 流式消息 ID
            content: 消息内容
            finish: 是否结束
            feedback_id: 反馈 ID（可选）
            msg_items: 图文混排消息列表（可选）
        
        Returns:
            XML 字符串
        """
        timestamp = int(time.time())
        finish_value = 1 if finish else 0
        
        # 构建 Feedback 标签
        feedback_xml = ""
        if feedback_id:
            feedback_xml = f"""
        <Feedback>
            <Id><![CDATA[{feedback_id}]]></Id>
        </Feedback>"""
        
        # 构建 MsgItem 标签
        msg_items_xml = ""
        if msg_items and finish:
            items = []
            for item in msg_items[:10]:  # 最多 10 个
                if item.get("msgtype") == "image":
                    image = item.get("image", {})
                    items.append(f"""
            <MsgItem>
                <MsgType><![CDATA[image]]></MsgType>
                <Image>
                    <Base64><![CDATA[{image.get("base64", "")}]]></Base64>
                    <Md5><![CDATA[{image.get("md5", "")}]]></Md5>
                </Image>
            </MsgItem>""")
            msg_items_xml = "".join(items)
        
        xml = f"""<xml>
    <ToUserName><![CDATA[{to_user}]]></ToUserName>
    <FromUserName><![CDATA[{from_user}]]></FromUserName>
    <CreateTime>{timestamp}</CreateTime>
    <MsgType><![CDATA[stream]]></MsgType>
    <Stream>
        <Id><![CDATA[{stream_id}]]></Id>
        <Finish>{finish_value}</Finish>
        <Content><![CDATA[{content}]]></Content>{feedback_xml}{msg_items_xml}
    </Stream>
</xml>"""
        
        return xml
    
    def build_template_card_xml(
        self,
        to_user: str,
        from_user: str,
        card_data: Dict[str, Any],
        feedback_id: Optional[str] = None
    ) -> str:
        """
        构建模板卡片消息 XML
        
        Args:
            to_user: 接收用户 ID
            from_user: 发送用户 ID
            card_data: 卡片数据
            feedback_id: 反馈 ID（可选）
        
        Returns:
            XML 字符串
        """
        timestamp = int(time.time())
        
        # 构建 Feedback 标签
        feedback_xml = ""
        if feedback_id:
            feedback_xml = f"""
        <Feedback>
            <Id><![CDATA[{feedback_id}]]></Id>
        </Feedback>"""
        
        # TODO: 根据 card_data 构建完整的卡片 XML
        # 这里先提供一个简化版本
        card_type = card_data.get("card_type", "text_notice")
        
        xml = f"""<xml>
    <ToUserName><![CDATA[{to_user}]]></ToUserName>
    <FromUserName><![CDATA[{from_user}]]></FromUserName>
    <CreateTime>{timestamp}</CreateTime>
    <MsgType><![CDATA[template_card]]></MsgType>
    <TemplateCard>
        <CardType><![CDATA[{card_type}]]></CardType>
        <!-- TODO: 添加更多卡片内容 -->{feedback_xml}
    </TemplateCard>
</xml>"""
        
        return xml
    
    # ============== 辅助方法 ==============
    
    def generate_stream_id(self, user_id: str, timestamp: Optional[int] = None) -> str:
        """
        生成流式消息 ID
        
        Args:
            user_id: 用户 ID
            timestamp: 时间戳（可选）
        
        Returns:
            流式消息 ID
        """
        if timestamp is None:
            timestamp = int(time.time())
        return f"stream_{user_id}_{timestamp}"
    
    def generate_feedback_id(self, stream_id: str) -> str:
        """
        生成反馈 ID
        
        Args:
            stream_id: 流式消息 ID
        
        Returns:
            反馈 ID
        """
        return f"fb_{stream_id}"
