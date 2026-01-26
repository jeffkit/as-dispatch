"""
测试消息分拆器
"""
import pytest

from forward_service.message_splitter import (
    get_string_bytes,
    split_message_content,
    split_and_format_message,
    create_message_header,
    needs_split,
    MAX_MESSAGE_BYTES,
    EFFECTIVE_MAX_BYTES,
)


class TestGetStringBytes:
    """测试字节数计算"""
    
    def test_ascii_string(self):
        """ASCII 字符串"""
        assert get_string_bytes("hello") == 5
    
    def test_chinese_string(self):
        """中文字符串（UTF-8 中每个中文字符占 3 字节）"""
        assert get_string_bytes("你好") == 6
    
    def test_mixed_string(self):
        """混合字符串"""
        assert get_string_bytes("hello 你好") == 12  # 5 + 1 + 6
    
    def test_empty_string(self):
        """空字符串"""
        assert get_string_bytes("") == 0


class TestSplitMessageContent:
    """测试消息内容分拆"""
    
    def test_short_message(self):
        """短消息不需要分拆"""
        message = "Hello, world!"
        result = split_message_content(message, max_bytes=100)
        assert len(result) == 1
        assert result[0] == message
    
    def test_empty_message(self):
        """空消息"""
        result = split_message_content("", max_bytes=100)
        assert len(result) == 1
        assert result[0] == ""
    
    def test_split_by_newlines(self):
        """按换行符分拆"""
        message = "Line 1\nLine 2\nLine 3"
        result = split_message_content(message, max_bytes=15)
        # 每行大约 6-7 字节，应该分成多段
        assert len(result) >= 2
    
    def test_long_single_line(self):
        """超长单行强制分拆"""
        message = "x" * 200  # 200 字节
        result = split_message_content(message, max_bytes=50)
        assert len(result) >= 4  # 至少分成 4 段
        # 验证每段不超过限制
        for part in result:
            assert get_string_bytes(part) <= 50
    
    def test_chinese_text_split(self):
        """中文文本分拆"""
        # 每个中文字符 3 字节，"测试" 占 6 字节
        message = "测试" * 20  # 120 字节
        result = split_message_content(message, max_bytes=50)
        assert len(result) >= 3
        for part in result:
            assert get_string_bytes(part) <= 50
    
    def test_multiline_with_long_lines(self):
        """多行文本，包含超长行"""
        lines = [
            "Short line",
            "x" * 100,  # 超长行
            "Another short line"
        ]
        message = "\n".join(lines)
        result = split_message_content(message, max_bytes=50)
        
        # 超长行应该被分拆
        assert len(result) >= 3
        
        # 验证每段不超过限制
        for part in result:
            assert get_string_bytes(part) <= 50


class TestCreateMessageHeader:
    """测试消息头部创建"""
    
    def test_header_with_project_name(self):
        """带项目名的头部"""
        header = create_message_header("abc12345", "测试项目", 1, 1)
        assert header == "[#abc12345 测试项目]"
    
    def test_header_without_project_name(self):
        """不带项目名的头部"""
        header = create_message_header("abc12345", None, 1, 1)
        assert header == "[#abc12345]"
    
    def test_header_with_pagination(self):
        """带分页信息的头部"""
        header = create_message_header("abc12345", "项目", 1, 3)
        assert header == "[#abc12345 项目] (1/3)"
    
    def test_header_no_short_id(self):
        """没有 short_id 时不生成头部"""
        header = create_message_header("", "项目", 1, 1)
        assert header == ""


class TestSplitAndFormatMessage:
    """测试消息分拆和格式化"""
    
    def test_short_message_with_header(self):
        """短消息添加头部"""
        message = "Hello, world!"
        result = split_and_format_message(
            message=message,
            short_id="abc12345",
            project_name="测试项目"
        )
        
        assert len(result) == 1
        assert result[0].part_number == 1
        assert result[0].total_parts == 1
        assert result[0].is_first is True
        assert result[0].is_last is True
        assert "[#abc12345 测试项目]" in result[0].content
        assert message in result[0].content
    
    def test_long_message_split(self):
        """长消息分拆"""
        # 创建一个超过 EFFECTIVE_MAX_BYTES 的消息
        message = "测试内容\n" * 500  # 约 5000 字节
        result = split_and_format_message(
            message=message,
            short_id="abc12345",
            project_name="项目"
        )
        
        # 应该分成多条
        assert len(result) > 1
        
        # 验证每条消息
        for i, split_msg in enumerate(result):
            assert split_msg.part_number == i + 1
            assert split_msg.total_parts == len(result)
            assert split_msg.is_first == (i == 0)
            assert split_msg.is_last == (i == len(result) - 1)
            
            # 每条都应该有头部
            assert f"[#abc12345 项目] ({i+1}/{len(result)})" in split_msg.content
            
            # 验证字节数不超过限制
            assert get_string_bytes(split_msg.content) <= MAX_MESSAGE_BYTES
    
    def test_split_without_project_name(self):
        """没有项目名的分拆"""
        message = "A" * 3000
        result = split_and_format_message(
            message=message,
            short_id="abc12345"
        )
        
        assert len(result) > 1
        for split_msg in result:
            assert "[#abc12345]" in split_msg.content


class TestNeedsSplit:
    """测试是否需要分拆的判断"""
    
    def test_short_message_no_split(self):
        """短消息不需要分拆"""
        message = "Hello, world!"
        assert needs_split(message, "abc12345", "项目") is False
    
    def test_long_message_needs_split(self):
        """长消息需要分拆"""
        # MAX_MESSAGE_BYTES = 2048
        # 创建一个肯定超过 2048 字节的消息
        message = "测试" * 800  # 约 2400 字节
        assert needs_split(message, "abc12345", "项目") is True
    
    def test_edge_case_at_limit(self):
        """边界情况：接近但不超过限制"""
        # 创建一个接近 2048 字节但不超过的消息
        # 需要考虑头部开销
        header = "[#abc12345 项目]\n"
        header_bytes = get_string_bytes(header)
        
        # 创建一个正好在限制内的消息
        message_bytes = MAX_MESSAGE_BYTES - header_bytes - 10
        message = "x" * message_bytes
        
        assert needs_split(message, "abc12345", "项目") is False
    
    def test_message_just_over_limit(self):
        """边界情况：刚好超过限制"""
        # 创建一个刚好超过 2048 字节的消息
        header = "[#abc12345 项目]\n"
        header_bytes = get_string_bytes(header)
        
        # 创建一个刚好超过限制的消息
        message_bytes = MAX_MESSAGE_BYTES - header_bytes + 10
        message = "x" * message_bytes
        
        assert needs_split(message, "abc12345", "项目") is True
