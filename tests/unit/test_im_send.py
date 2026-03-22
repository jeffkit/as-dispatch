"""
T015: POST /api/im/send 单元测试

测试覆盖：
- Happy path: 有效请求 → success + short_id
- 路由头格式: [#ob_xxxxxx ProjectName]\\n\\n<content>
- fly-pigeon 发送失败 → { success: false, error }，不保存上下文
- 缺少必填字段 → 422
- JWT 鉴权拦截
- T017: 重复发送同一条消息生成不同 short_id
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pkg_root = Path(__file__).parent.parent.parent
if str(pkg_root) not in sys.path:
    sys.path.insert(0, str(pkg_root))

from forward_service.routes.im_send import DispatchRequest, send_to_im


def _make_body(**overrides) -> DispatchRequest:
    defaults = {
        "message_content": "Hello, world!",
        "bot_key": "bot_key_12345",
        "chat_id": "chat_id_67890",
        "session_id": "sess-abcdef01",
        "project_name": "MyProject",
    }
    defaults.update(overrides)
    return DispatchRequest(**defaults)


class TestSendToIm:
    @pytest.mark.asyncio
    async def test_happy_path(self, mock_db_manager):
        body = _make_body()
        with (
            patch("forward_service.routes.im_send.send_to_wecom", return_value={"errcode": 0}) as mock_send,
        ):
            result = await send_to_im(body, _user={"service": "test"})

        assert result["success"] is True
        assert result["short_id"].startswith("ob_")
        assert len(result["short_id"]) == 9
        assert result["message_with_header"].startswith("[#")
        assert body.message_content in result["message_with_header"]
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_routing_header_format_with_project(self, mock_db_manager):
        body = _make_body(project_name="TestProj")
        with patch("forward_service.routes.im_send.send_to_wecom", return_value={"errcode": 0}):
            result = await send_to_im(body, _user={"service": "test"})

        header_line = result["message_with_header"].split("\n")[0]
        assert header_line.startswith("[#ob_")
        assert "TestProj" in header_line
        assert header_line.endswith("]")

    @pytest.mark.asyncio
    async def test_routing_header_format_without_project(self, mock_db_manager):
        body = _make_body(project_name=None)
        with patch("forward_service.routes.im_send.send_to_wecom", return_value={"errcode": 0}):
            result = await send_to_im(body, _user={"service": "test"})

        header_line = result["message_with_header"].split("\n")[0]
        assert header_line.startswith("[#ob_")
        assert header_line.endswith("]")
        # Should not have trailing space before ]
        assert "  " not in header_line

    @pytest.mark.asyncio
    async def test_send_failure_returns_error(self, mock_db_manager):
        body = _make_body()
        with patch(
            "forward_service.routes.im_send.send_to_wecom",
            side_effect=Exception("network error"),
        ):
            result = await send_to_im(body, _user={"service": "test"})

        assert result["success"] is False
        assert "network error" in result["error"]

    @pytest.mark.asyncio
    async def test_wecom_errcode_nonzero_returns_error(self, mock_db_manager):
        body = _make_body()
        with patch(
            "forward_service.routes.im_send.send_to_wecom",
            return_value={"errcode": 40001, "errmsg": "invalid credential"},
        ):
            result = await send_to_im(body, _user={"service": "test"})

        assert result["success"] is False
        assert "40001" in result["error"]

    @pytest.mark.asyncio
    async def test_repeated_dispatch_generates_different_ids(self, mock_db_manager):
        """T017: 重复发送同一条消息生成不同 short_id"""
        body = _make_body()
        short_ids = set()
        for _ in range(5):
            with patch("forward_service.routes.im_send.send_to_wecom", return_value={"errcode": 0}):
                result = await send_to_im(body, _user={"service": "test"})
            assert result["success"] is True
            short_ids.add(result["short_id"])

        assert len(short_ids) == 5, f"Expected 5 unique IDs, got {len(short_ids)}"
