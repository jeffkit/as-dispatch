"""
消息分拆器

企业微信消息有大小限制，当消息过长时需要分拆。
分拆后的每条消息都需要添加头部标识，方便用户回复。

配置：
- 最大消息字节数设置为 2048 字节（2K）
- 预留 150 字节用于头部和分页信息
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 企微消息最大字节数（配置为 2K）
MAX_MESSAGE_BYTES = 2048

# 预留字节数（用于头部和分页信息）
HEADER_RESERVE_BYTES = 150

# 实际可用的消息字节数
EFFECTIVE_MAX_BYTES = MAX_MESSAGE_BYTES - HEADER_RESERVE_BYTES


@dataclass
class SplitMessage:
    """分拆后的消息"""
    content: str
    part_number: int
    total_parts: int
    is_first: bool
    is_last: bool


def get_string_bytes(s: str) -> int:
    """获取字符串的 UTF-8 字节数"""
    return len(s.encode('utf-8'))


def split_message_content(
    message: str,
    max_bytes: int = EFFECTIVE_MAX_BYTES
) -> list[str]:
    """
    按字节数分拆消息内容
    
    尽量在换行符处分拆，避免在中间断开。
    如果单行超过限制，则强制按字符分拆。
    
    Args:
        message: 原始消息内容
        max_bytes: 每段最大字节数
        
    Returns:
        分拆后的消息列表
    """
    if not message:
        return [""]
    
    # 如果消息不超过限制，直接返回
    if get_string_bytes(message) <= max_bytes:
        return [message]
    
    parts = []
    lines = message.split('\n')
    current_part = []
    current_bytes = 0
    
    for line in lines:
        line_bytes = get_string_bytes(line)
        newline_bytes = 1  # '\n' 占 1 字节
        
        # 如果当前行本身超过限制，需要强制分拆
        if line_bytes > max_bytes:
            # 先保存当前累积的内容
            if current_part:
                parts.append('\n'.join(current_part))
                current_part = []
                current_bytes = 0
            
            # 按字符分拆超长行
            split_lines = _split_long_line(line, max_bytes)
            for i, split_line in enumerate(split_lines):
                if i < len(split_lines) - 1:
                    parts.append(split_line)
                else:
                    # 最后一段加入当前累积
                    current_part.append(split_line)
                    current_bytes = get_string_bytes(split_line)
            continue
        
        # 检查添加这行后是否超过限制
        additional_bytes = line_bytes + (newline_bytes if current_part else 0)
        
        if current_bytes + additional_bytes > max_bytes:
            # 超过限制，保存当前部分，开始新的部分
            if current_part:
                parts.append('\n'.join(current_part))
            current_part = [line]
            current_bytes = line_bytes
        else:
            # 未超过限制，继续累积
            current_part.append(line)
            current_bytes += additional_bytes
    
    # 保存最后一部分
    if current_part:
        parts.append('\n'.join(current_part))
    
    return parts


def _split_long_line(line: str, max_bytes: int) -> list[str]:
    """
    分拆超长的单行
    
    按字符分拆，确保每段不超过 max_bytes
    """
    if not line:
        return [""]
    
    parts = []
    current_chars = []
    current_bytes = 0
    
    for char in line:
        char_bytes = get_string_bytes(char)
        
        if current_bytes + char_bytes > max_bytes:
            # 超过限制，保存当前部分
            if current_chars:
                parts.append(''.join(current_chars))
            current_chars = [char]
            current_bytes = char_bytes
        else:
            current_chars.append(char)
            current_bytes += char_bytes
    
    # 保存最后一部分
    if current_chars:
        parts.append(''.join(current_chars))
    
    return parts


def create_message_header(
    short_id: str,
    project_name: str | None,
    part_number: int,
    total_parts: int
) -> str:
    """
    创建消息头部
    
    格式: [#short_id 项目名] (1/3)
    """
    if not short_id:
        return ""
    
    if project_name:
        base_header = f"[#{short_id} {project_name}]"
    else:
        base_header = f"[#{short_id}]"
    
    # 只有多条消息时才显示分页信息
    if total_parts > 1:
        return f"{base_header} ({part_number}/{total_parts})"
    
    return base_header


def split_and_format_message(
    message: str,
    short_id: str,
    project_name: str | None = None,
    max_bytes: int = EFFECTIVE_MAX_BYTES
) -> list[SplitMessage]:
    """
    分拆消息并格式化
    
    每条分拆的消息都会添加头部标识。
    注意：不添加「请回复」提示。
    
    Args:
        message: 原始消息内容
        short_id: 会话短 ID
        project_name: 项目名称
        max_bytes: 每段最大字节数
        
    Returns:
        分拆后的 SplitMessage 列表
    """
    # 1. 先按内容分拆
    content_parts = split_message_content(message, max_bytes)
    total_parts = len(content_parts)
    
    # 2. 为每部分添加头部和格式
    result = []
    for i, content in enumerate(content_parts):
        part_number = i + 1
        is_first = (i == 0)
        is_last = (i == len(content_parts) - 1)
        
        # 创建头部
        header = create_message_header(short_id, project_name, part_number, total_parts)
        
        # 组装消息
        if header:
            formatted_content = f"{header}\n{content}"
        else:
            formatted_content = content
        
        result.append(SplitMessage(
            content=formatted_content,
            part_number=part_number,
            total_parts=total_parts,
            is_first=is_first,
            is_last=is_last
        ))
    
    return result


def needs_split(message: str, short_id: str, project_name: str | None = None) -> bool:
    """
    检查消息是否需要分拆
    
    考虑头部的开销后判断。
    """
    # 计算完整格式化后的消息长度
    header = create_message_header(short_id, project_name, 1, 1)
    
    full_message = f"{header}\n{message}" if header else message
    
    return get_string_bytes(full_message) > MAX_MESSAGE_BYTES
