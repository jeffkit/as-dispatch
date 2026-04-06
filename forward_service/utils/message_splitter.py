"""
将长文本拆成多条企微可发送的片段（单条有长度上限）。
"""


def split_message(text: str, max_len: int = 2048) -> list[str]:
    if not text:
        return [""]
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        window = remaining[:max_len]
        split_at = -1
        for sep in ("\n\n", "\n", "。", "！", "？", ". ", "! ", "? "):
            idx = window.rfind(sep)
            if idx > max_len // 4:
                split_at = idx + len(sep)
                break

        if split_at <= 0:
            split_at = max_len

        part = remaining[:split_at].rstrip()
        if not part:
            part = remaining[:max_len]
            split_at = max_len

        chunks.append(part)
        remaining = remaining[split_at:].lstrip()

    return chunks
