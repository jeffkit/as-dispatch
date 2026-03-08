"""
隧道配置单元测试

测试 forward_service/tunnel.py 中的配置加载逻辑，包括：
- 默认配置值
- JSON 文件覆盖
- 环境变量覆盖
- jwt_secret 配置项（向后兼容）
- URL 解析工具函数
"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

# Mock tunely 模块以避免导入错误
if 'tunely' not in sys.modules:
    sys.modules['tunely'] = MagicMock()
    sys.modules['tunely.server'] = MagicMock()

import pytest


class TestLoadTunnelConfig:
    """测试 load_tunnel_config 函数"""

    def _load_config(self, env_vars: dict | None = None, config_file_content: dict | None = None):
        """辅助方法：在指定环境变量和配置文件下加载配置"""
        # Need to import fresh each time because module has side effects
        from forward_service.tunnel import load_tunnel_config

        env = env_vars or {}

        if config_file_content is not None:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', delete=False
            ) as f:
                json.dump(config_file_content, f)
                config_path = f.name
            env["TUNNEL_CONFIG_FILE"] = config_path
        else:
            # Point to non-existent file so JSON loading is skipped
            env["TUNNEL_CONFIG_FILE"] = "/tmp/nonexistent_tunnel_config.json"

        with patch.dict(os.environ, env, clear=False):
            # Clear any existing env vars that might interfere
            for key in ["TUNNEL_DOMAIN", "TUNNEL_WS_URL", "TUNNEL_ADMIN_API_KEY",
                        "WS_TUNNEL_ADMIN_API_KEY", "WS_TUNNEL_INSTRUCTION", "TUNNEL_JWT_SECRET"]:
                if key not in env:
                    os.environ.pop(key, None)
            return load_tunnel_config()

    def test_default_values(self):
        """默认值正确"""
        config = self._load_config()
        assert config["ws_path"] == "/ws/tunnel"
        assert config["domain"] == "tunnel"
        assert config["admin_api_key"] is None
        assert config["instruction"] is None
        assert config["jwt_secret"] is None

    def test_jwt_secret_default_is_none(self):
        """jwt_secret 默认为 None（向后兼容）"""
        config = self._load_config()
        assert config["jwt_secret"] is None

    def test_jwt_secret_from_env(self):
        """环境变量 TUNNEL_JWT_SECRET 加载"""
        config = self._load_config(env_vars={"TUNNEL_JWT_SECRET": "my-secret-key"})
        assert config["jwt_secret"] == "my-secret-key"

    def test_jwt_secret_from_json_file(self):
        """JSON 配置文件中的 jwt_secret"""
        config = self._load_config(config_file_content={"jwt_secret": "json-secret"})
        assert config["jwt_secret"] == "json-secret"

    def test_env_overrides_json_for_jwt_secret(self):
        """环境变量优先级高于 JSON 配置"""
        config = self._load_config(
            env_vars={"TUNNEL_JWT_SECRET": "env-secret"},
            config_file_content={"jwt_secret": "json-secret"},
        )
        assert config["jwt_secret"] == "env-secret"

    def test_json_without_jwt_secret_keeps_default(self):
        """JSON 配置不包含 jwt_secret 时保持默认 None"""
        config = self._load_config(config_file_content={"domain": "custom-domain"})
        assert config["jwt_secret"] is None
        assert config["domain"] == "custom-domain"

    def test_domain_from_env(self):
        """环境变量 TUNNEL_DOMAIN 加载"""
        config = self._load_config(env_vars={"TUNNEL_DOMAIN": "custom"})
        assert config["domain"] == "custom"

    def test_instruction_from_env(self):
        """环境变量 WS_TUNNEL_INSTRUCTION 加载"""
        config = self._load_config(env_vars={"WS_TUNNEL_INSTRUCTION": "须知内容"})
        assert config["instruction"] == "须知内容"

    def test_full_json_config(self):
        """完整 JSON 配置加载"""
        full_config = {
            "ws_path": "/ws/custom",
            "domain": "custom-tunnel",
            "ws_url": "wss://custom.example.com/ws",
            "admin_api_key": "admin-key",
            "instruction": "使用说明",
            "jwt_secret": "jwt-key",
        }
        config = self._load_config(config_file_content=full_config)
        assert config["ws_path"] == "/ws/custom"
        assert config["domain"] == "custom-tunnel"
        assert config["ws_url"] == "wss://custom.example.com/ws"
        assert config["admin_api_key"] == "admin-key"
        assert config["instruction"] == "使用说明"
        assert config["jwt_secret"] == "jwt-key"


class TestTunnelUrlHelpers:
    """测试隧道 URL 工具函数"""

    def test_is_tunnel_url(self):
        from forward_service.tunnel import is_tunnel_url

        assert is_tunnel_url("http://my-agent.tunnel/api/chat") is True
        assert is_tunnel_url("http://my-agent.tunnel:8080/api/chat") is True
        assert is_tunnel_url("https://example.com/api/chat") is False
        assert is_tunnel_url("not-a-url") is False

    def test_extract_tunnel_domain(self):
        from forward_service.tunnel import extract_tunnel_domain

        assert extract_tunnel_domain("http://my-agent.tunnel/api/chat") == "my-agent"
        assert extract_tunnel_domain("http://dev-1.tunnel:8080/") == "dev-1"
        assert extract_tunnel_domain("https://example.com/api") is None

    def test_extract_tunnel_path(self):
        from forward_service.tunnel import extract_tunnel_path

        assert extract_tunnel_path("http://my-agent.tunnel/api/chat") == "/api/chat"
        assert extract_tunnel_path("http://my-agent.tunnel/path?key=val") == "/path?key=val"
        assert extract_tunnel_path("http://my-agent.tunnel") == "/"
