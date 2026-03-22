"""
T014: outbound short_id 生成逻辑单元测试

测试覆盖：
- 格式校验: ob_ 前缀、8 字符总长、hex 后缀
- 多次调用唯一性
- generate_unique_outbound_short_id 的碰撞重试和最大重试失败
"""
import re

import pytest

from forward_service.utils.short_id import (
    OB_PREFIX,
    generate_outbound_short_id,
    generate_unique_outbound_short_id,
)


class TestGenerateOutboundShortId:
    def test_starts_with_ob_prefix(self):
        sid = generate_outbound_short_id()
        assert sid.startswith(OB_PREFIX)

    def test_total_length_is_9(self):
        sid = generate_outbound_short_id()
        assert len(sid) == len("ob_") + 6  # ob_ (3) + 6 hex = 9

    def test_hex_suffix_valid(self):
        sid = generate_outbound_short_id()
        hex_part = sid[len(OB_PREFIX):]
        assert re.fullmatch(r"[a-f0-9]{6}", hex_part), f"Invalid hex suffix: {hex_part}"

    def test_multiple_calls_produce_different_ids(self):
        ids = {generate_outbound_short_id() for _ in range(100)}
        assert len(ids) == 100, "Expected 100 unique IDs from 100 calls"


class TestGenerateUniqueOutboundShortId:
    @pytest.mark.asyncio
    async def test_no_checker_returns_immediately(self):
        sid = await generate_unique_outbound_short_id(exists_checker=None)
        assert sid.startswith(OB_PREFIX)

    @pytest.mark.asyncio
    async def test_retries_on_collision(self):
        call_count = 0

        async def exists_first_two(short_id: str) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count <= 2

        sid = await generate_unique_outbound_short_id(exists_checker=exists_first_two)
        assert sid.startswith(OB_PREFIX)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        async def always_exists(_: str) -> bool:
            return True

        with pytest.raises(RuntimeError, match="无法在"):
            await generate_unique_outbound_short_id(
                exists_checker=always_exists, max_retries=3
            )

    @pytest.mark.asyncio
    async def test_checker_never_collides(self):
        async def never_exists(_: str) -> bool:
            return False

        sid = await generate_unique_outbound_short_id(exists_checker=never_exists)
        assert sid.startswith(OB_PREFIX)
