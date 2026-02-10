"""
消息内容提取工具

从企微回调数据中提取文本和图片内容
"""


def extract_content(data: dict) -> tuple[str | None, list[str]]:
    """
    从回调数据中提取消息内容
    
    Args:
        data: 飞鸽回调原始数据
    
    Returns:
        (text_content, image_urls) - image_urls 是图片 URL 列表
    """
    msg_type = data.get("msgtype", "")
    
    if msg_type == "text":
        text_data = data.get("text", {})
        content = text_data.get("content", "")
        # 去除 @机器人
        if content.startswith("@"):
            parts = content.split(" ", 1)
            if len(parts) > 1:
                content = parts[1].strip()
        return content, []
    
    elif msg_type == "image":
        image_data = data.get("image", {})
        image_url = image_data.get("image_url", "")
        return None, [image_url] if image_url else []
    
    elif msg_type == "mixed":
        mixed = data.get("mixed_message", {})
        msg_items = mixed.get("msg_item", [])
        
        contents = []
        images = []
        
        for item in msg_items:
            item_type = item.get("msg_type", "")
            if item_type == "text":
                text = item.get("text", {}).get("content", "")
                # 去除 @机器人
                if text.startswith("@"):
                    parts = text.split(" ", 1)
                    if len(parts) > 1:
                        text = parts[1].strip()
                if text:
                    contents.append(text)
            elif item_type == "image":
                img_url = item.get("image", {}).get("image_url", "")
                if img_url:
                    images.append(img_url)
        
        content = "\n".join(contents) if contents else None
        return content, images
    
    return None, []
