"""
消息内容提取工具

从企微回调数据中提取文本和图片内容。
支持引用消息解析：自动剥离引用部分，只保留用户实际回复。
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# 企微引用消息格式：
#   \u201c被引用的消息内容\u201d
#   ------
#   @机器人 用户实际回复
#
# 其中：
# - \u201c ... \u201d 是中文左右双引号
# - ------ 是 6 个减号作为分隔线
# - 引用内容中可能包含 [#short_id] 或 [#short_id project_name] 的会话标识
QUOTE_SEPARATOR = "\n------\n"
SHORT_ID_PATTERN = re.compile(r'\[#([a-f0-9]{6,8})(?:\s+\S+)?\]')


@dataclass
class ExtractedContent:
    """提取的消息内容"""
    text: Optional[str]
    image_urls: list[str]
    quoted_short_id: Optional[str] = None  # 从引用内容中解析出的会话短 ID


def strip_quote_content(text: str) -> tuple[str, Optional[str]]:
    """
    剥离引用消息内容，只保留用户实际回复。
    
    企微引用回复格式:
        \u201c被引用的消息...\u201d
        ------
        @机器人 用户实际回复
    
    Args:
        text: 原始文本内容
    
    Returns:
        (clean_text, quoted_short_id)
        - clean_text: 去掉引用后的用户实际回复
        - quoted_short_id: 从引用内容中提取的 short_id（如果有）
    """
    if not text or QUOTE_SEPARATOR not in text:
        return text, None
    
    # 查找分隔线位置
    sep_index = text.find(QUOTE_SEPARATOR)
    if sep_index < 0:
        return text, None
    
    quoted_part = text[:sep_index]
    user_reply = text[sep_index + len(QUOTE_SEPARATOR):]
    
    # 验证引用部分是否以中文左双引号开头（确认是引用格式）
    if not quoted_part.startswith("\u201c"):
        return text, None
    
    # 从引用内容中提取 short_id
    quoted_short_id = None
    match = SHORT_ID_PATTERN.search(quoted_part)
    if match:
        quoted_short_id = match.group(1)
        logger.info(f"从引用消息中提取到 short_id: {quoted_short_id}")
    
    # 用户回复部分去掉末尾空格
    user_reply = user_reply.strip()
    
    if not user_reply:
        # 用户只引用了消息但没有写回复内容
        logger.warning("引用回复中用户实际内容为空")
        return "", quoted_short_id
    
    logger.info(f"剥离引用消息，用户实际回复: {user_reply[:50]}...")
    return user_reply, quoted_short_id


def _strip_at_prefix(text: str) -> str:
    """去除文本开头的 @机器人 前缀"""
    if text.startswith("@"):
        parts = text.split(" ", 1)
        if len(parts) > 1:
            return parts[1].strip()
    return text


def extract_content(data: dict) -> ExtractedContent:
    """
    从回调数据中提取消息内容
    
    自动处理引用消息：剥离引用部分，只保留用户实际回复。
    如果引用内容中包含 [#short_id]，会提取出来用于会话路由。
    
    Args:
        data: 飞鸽回调原始数据
    
    Returns:
        ExtractedContent: 包含 text, image_urls, quoted_short_id
    """
    msg_type = data.get("msgtype", "")
    
    if msg_type == "text":
        text_data = data.get("text", {})
        content = text_data.get("content", "")
        
        # 先剥离引用内容
        content, quoted_short_id = strip_quote_content(content)
        
        # 去除 @机器人
        content = _strip_at_prefix(content)
        
        return ExtractedContent(text=content, image_urls=[], quoted_short_id=quoted_short_id)
    
    elif msg_type == "image":
        image_data = data.get("image", {})
        image_url = image_data.get("image_url", "")
        return ExtractedContent(text=None, image_urls=[image_url] if image_url else [])
    
    elif msg_type == "mixed":
        mixed = data.get("mixed_message", {})
        msg_items = mixed.get("msg_item", [])
        
        contents = []
        images = []
        quoted_short_id = None
        
        for item in msg_items:
            item_type = item.get("msg_type", "")
            if item_type == "text":
                text = item.get("text", {}).get("content", "")
                
                # 对第一段文本尝试剥离引用
                if not contents and not quoted_short_id:
                    text, quoted_short_id = strip_quote_content(text)
                
                # 去除 @机器人
                text = _strip_at_prefix(text)
                
                if text:
                    contents.append(text)
            elif item_type == "image":
                img_url = item.get("image", {}).get("image_url", "")
                if img_url:
                    images.append(img_url)
        
        content = "\n".join(contents) if contents else None
        return ExtractedContent(text=content, image_urls=images, quoted_short_id=quoted_short_id)
    
    return ExtractedContent(text=None, image_urls=[])
