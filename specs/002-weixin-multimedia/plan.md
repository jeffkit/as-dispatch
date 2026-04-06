# Implementation Plan: 微信个人号多媒体消息收发

**Feature Branch**: `002-weixin-multimedia`
**Created**: 2026-03-23
**Status**: Draft
**Spec**: `specs/002-weixin-multimedia/spec.md`

---

## Technical Context

### Technology Stack

| Component | Technology | Version |
|---|---|---|
| Language | Python | 3.11+ |
| Web Framework | FastAPI | ≥0.115 |
| HTTP Client | httpx (AsyncClient) | ≥0.27 |
| AES Crypto | cryptography | ≥44.0 (新增) |
| Async Runtime | asyncio + uvicorn | — |

### Architecture Patterns

- **Adapter Pattern**: `ChannelAdapter` 抽象基类 → `WeixinAdapter` 实现
- **Client Delegation**: 所有 HTTP 调用通过 `WeixinClient` (Principle 7)
- **Pipeline Pattern**: 统一消息管线 `pipeline.process_message()` 处理所有平台消息
- **Error Isolation**: 每个适配器异常自包含 (Principle 3)

### Existing Integration Points

| Module | Path | Role |
|---|---|---|
| WeixinClient | `forward_service/clients/weixin.py` | iLinkAI HTTP API 封装 |
| WeixinAdapter | `forward_service/channel/weixin.py` | 通道适配器 |
| WeixinPoller + Routes | `forward_service/routes/weixin.py` | 长轮询 + Admin API |
| Pipeline | `forward_service/pipeline.py` | 统一消息管线 |
| InboundMessage | `forward_service/channel/base.py` | 入站消息 dataclass |
| OutboundMessage | `forward_service/channel/base.py` | 出站消息 dataclass |
| Forwarder | `forward_service/services/forwarder.py` | Agent 转发（已支持 images 字段）|

### CDN Infrastructure

| Item | Value |
|---|---|
| CDN Base URL | `https://novac2c.cdn.weixin.qq.com/c2c` (可配置) |
| Download URL | `{cdnBaseUrl}/download?encrypted_query_param={param}` |
| Upload URL | `{cdnBaseUrl}/upload?encrypted_query_param={uploadParam}&filekey={filekey}` |
| 加密算法 | AES-128-ECB, PKCS7 padding |
| 密钥 | 随机 16 字节，上传时提交给 `getuploadurl` |
| Upload API | `POST /ilink/bot/getuploadurl` (获取预签名上传 URL) |

---

## Constitution Check

### Principle-by-Principle Validation

| # | Principle | Status | Notes |
|---|---|---|---|
| P1 | Python 3.11+ / FastAPI | ✅ PASS | 全部代码 Python 3.11+, 无新路由需求 |
| P2 | Mandatory type annotations | ✅ PASS | 所有新增函数/方法均带完整类型注解 |
| P3 | Per-adapter exception containment | ✅ PASS | 媒体操作失败回退为文本占位，不影响管线 |
| P4 | ChannelAdapter interface compliance | ✅ PASS | 不修改基类签名，仅扩展 WeixinAdapter 内部实现 |
| P5 | WeComAdapter as canonical pattern | ✅ PASS | WeixinAdapter 已有规范结构，新增代码放入私有方法区 |
| P6 | Structured per-module logging | ✅ PASS | 每个新模块使用 `logger = logging.getLogger(__name__)` |
| P7 | Use existing clients | ✅ PASS | 新增 API 方法全部加入 `WeixinClient`，不创建新 HTTP 客户端 |
| P8 | Independent adapter testability | ✅ PASS | 所有 CDN 和 API 调用可 mock，单元测试不依赖网络 |
| P9 | No breaking changes | ✅ PASS | 纯增量变更，不修改 base.py 签名或现有路由 |
| P10 | Non-blocking async I/O | ✅ PASS | 所有网络调用使用 httpx.AsyncClient，cryptography 为 C 实现（<1ms）不需 executor |

### Violations & Justifications

无违规。所有设计决策均符合 10 项原则。

---

## Design Decision: 不修改 base.py 的消息类型

### 决策

不在 `InboundMessage` / `OutboundMessage` dataclass 中添加新字段来表示媒体附件，而是通过以下方式传递媒体数据：

- **入站**：图片通过已有的 `images: list[str]` 字段传递（base64 data URI 或临时文件路径）；语音/文件/视频通过 `raw_data` 字典的扩展字段传递（`media_files`）
- **出站**：Agent 回复中的图片 URL 通过 `OutboundMessage.extra` 字典传递（已有字段，Principle 9 合规）

### 理由

1. Principle 9 明确禁止修改 `ChannelAdapter` 抽象方法签名
2. `InboundMessage.images` 已存在且 Agent 转发逻辑 (`forwarder.py`) 已支持该字段
3. `OutboundMessage.extra` 已为平台特定扩展预留

### 替代方案

- 方案 B：在 `base.py` 添加 `attachments: list[Attachment]` 通用字段 — 需要 MAJOR 版本升级宪法，影响所有现有适配器
- 方案 C：创建 `MultimediaMessage` 子类继承 `InboundMessage` — 引入不必要的继承层次，管线需添加 isinstance 判断

---

## Phase 0: Research

### Research 1: `cryptography` vs `pycryptodome` for AES-128-ECB

**决策**: 使用 `cryptography` 库

**理由**:
- `pycryptodome` 已在 `pyproject.toml` 中（`pycryptodome>=3.20.0`），但 `cryptography` 是 Python 生态更主流的加密库（PyPI 下载量 10x 以上）
- `cryptography` 的 `hazmat` 接口提供更好的类型安全和更清晰的 API
- 实际检查发现 `pyproject.toml` 中有 `pycryptodome`，可以复用

**最终决策**: 使用已有的 `pycryptodome`，避免引入新依赖。API 使用 `Crypto.Cipher.AES`。

### Research 2: AES Key 编码格式（入站 vs 出站）

来自参考实现 `pic-decrypt.ts::parseAesKey`:

- **图片入站**: `image_item.aeskey` 为 hex 字符串（16 字节 → 32 hex 字符），需要 hex decode
- **图片入站备选**: `image_item.media.aes_key` 为 base64 编码，base64 decode 得到 16 字节
- **语音/文件/视频入站**: `media.aes_key` 为 base64 编码，base64 decode 后：
  - 如果 16 字节 → 直接使用
  - 如果 32 字节且全为 hex 字符 → 先 ascii decode 得到 hex 字符串，再 hex decode 得到 16 字节
- **出站**: 随机生成 16 字节 key，hex 编码后传给 `getuploadurl` API

### Research 3: CDN Base URL 配置

**决策**: CDN Base URL 存储在 `platform_config` 字典中（数据库 ChatBot 表的 JSON 字段）

```python
platform_config = {
    "bot_token": "...",
    "ilink_bot_id": "...",
    "cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c",  # 可覆盖
    ...
}
```

默认值: `https://novac2c.cdn.weixin.qq.com/c2c`

### Research 4: 临时文件管理策略

**决策**: 使用 Python `tempfile` 模块创建临时文件，处理完成后立即清理

- 入站：下载解密后的媒体文件存为临时文件，图片转为 base64 data URI 后删除临时文件
- 出站：从 URL 下载的文件存为临时文件，上传 CDN 后删除

不使用持久化存储，避免磁盘空间管理问题。

### Research 5: 消息 item_list 多项处理

来自参考实现 `inbound.ts::bodyFromItemList`:

- `item_list` 可能包含多个 item
- 文本 item 和媒体 item 可以共存（如引用回复中文本+图片）
- 处理策略：遍历所有 item，分别处理文本和媒体
- 优先级（参考实现）：image > video > file > voice

---

## Phase 1: Design Artifacts

### 1. Data Model

#### 新增类型定义: `forward_service/channel/weixin_media.py`

```python
@dataclass
class CDNMedia:
    """CDN 媒体引用信息"""
    encrypt_query_param: str
    aes_key: str              # base64 编码
    encrypt_type: int = 0

@dataclass
class MediaDownloadResult:
    """媒体下载解密结果"""
    data: bytes
    media_type: str           # MIME type (e.g. "image/jpeg")
    file_name: str = ""       # 原始文件名（文件类型时）
    success: bool = True
    error: str = ""

@dataclass
class MediaUploadResult:
    """媒体上传结果"""
    filekey: str
    download_encrypted_query_param: str
    aes_key_hex: str          # hex 编码的 AES key
    file_size: int            # 明文大小
    file_size_ciphertext: int # 密文大小
    success: bool = True
    error: str = ""

class WeixinMediaType(IntEnum):
    """iLinkAI 上传媒体类型"""
    IMAGE = 1
    VIDEO = 2
    FILE = 3
    VOICE = 4
```

#### 配置常量

```python
DEFAULT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
WEIXIN_MEDIA_MAX_BYTES = 100 * 1024 * 1024  # 100MB
WEIXIN_UPLOAD_MAX_RETRIES = 3
WEIXIN_MEDIA_DOWNLOAD_TIMEOUT = 60.0  # 秒
WEIXIN_MEDIA_UPLOAD_TIMEOUT = 60.0    # 秒
```

### 2. API Contracts

#### 新增 WeixinClient 方法

```python
# forward_service/clients/weixin.py — 新增方法

async def get_upload_url(
    self,
    filekey: str,
    media_type: int,
    to_user_id: str,
    rawsize: int,
    rawfilemd5: str,
    filesize: int,
    aeskey: str,
    no_need_thumb: bool = True,
) -> dict[str, Any]:
    """
    获取 CDN 预签名上传 URL

    POST /ilink/bot/getuploadurl

    Returns:
        {"upload_param": "...", "thumb_upload_param": "..."}
    """

async def send_media_message(
    self,
    to_user_id: str,
    context_token: str,
    item_list: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    发送含媒体项的消息

    POST /ilink/bot/sendmessage

    item_list 可包含：
    - {"type": 1, "text_item": {"text": "..."}}
    - {"type": 2, "image_item": {...}}
    - {"type": 4, "file_item": {...}}
    - {"type": 5, "video_item": {...}}
    """
```

#### CDN Operations（新模块）

```python
# forward_service/clients/weixin_cdn.py

async def download_and_decrypt(
    http_client: httpx.AsyncClient,
    cdn_base_url: str,
    encrypt_query_param: str,
    aes_key_base64: str,
) -> bytes:
    """下载并解密 CDN 媒体文件"""

async def encrypt_and_upload(
    http_client: httpx.AsyncClient,
    cdn_base_url: str,
    upload_param: str,
    filekey: str,
    plaintext: bytes,
    aes_key: bytes,
) -> str:
    """加密并上传文件到 CDN，返回 download_encrypted_query_param"""
```

#### AES Crypto（新模块）

```python
# forward_service/clients/weixin_crypto.py

def encrypt_aes_ecb(plaintext: bytes, key: bytes) -> bytes:
    """AES-128-ECB 加密 (PKCS7 padding)"""

def decrypt_aes_ecb(ciphertext: bytes, key: bytes) -> bytes:
    """AES-128-ECB 解密 (PKCS7 padding)"""

def aes_ecb_padded_size(plaintext_size: int) -> int:
    """计算 AES-128-ECB 密文大小"""

def parse_aes_key(aes_key_base64: str) -> bytes:
    """解析 CDN 媒体的 AES key（支持两种编码格式）"""
```

### 3. Implementation Structure

#### 文件变更清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `forward_service/clients/weixin_crypto.py` | **新建** | AES-128-ECB 加解密工具 |
| `forward_service/clients/weixin_cdn.py` | **新建** | CDN 上传/下载操作 |
| `forward_service/clients/weixin.py` | **修改** | 新增 `get_upload_url()` + `send_media_message()` |
| `forward_service/channel/weixin_media.py` | **新建** | 媒体类型定义 + 入站/出站媒体处理 |
| `forward_service/channel/weixin.py` | **修改** | `parse_inbound()` 支持媒体解析，`send_outbound()` 支持媒体发送 |
| `forward_service/routes/weixin.py` | **修改** | `_parse_weixin_message()` 传递原始 item_list 数据 |
| `pyproject.toml` | **不变** | `pycryptodome` 已存在，无需添加 `cryptography` |
| `tests/unit/test_weixin_crypto.py` | **新建** | AES 加解密单元测试 |
| `tests/unit/test_weixin_cdn.py` | **新建** | CDN 操作单元测试 |
| `tests/unit/test_channel_weixin_media.py` | **新建** | 媒体消息解析/发送单元测试 |

#### 模块依赖关系

```
weixin_crypto.py          ← 纯函数，无外部依赖
    ↑
weixin_cdn.py             ← 依赖 weixin_crypto + httpx
    ↑
weixin_media.py           ← 依赖 weixin_cdn + weixin_crypto
    ↑
weixin.py (WeixinAdapter) ← 调用 weixin_media 的高层接口
    ↑
routes/weixin.py          ← 传递 raw item_list 给 adapter
```

### 4. Detailed Flow Design

#### 入站多媒体消息流

```
getupdates 响应 (WeixinPoller._poll_loop)
  │
  ├── raw_msg.item_list[0].type == 2 (IMAGE)
  │     │
  │     ▼
  │   _parse_weixin_message() — 提取 item_list 原始数据，放入 raw_data
  │     │
  │     ▼
  │   WeixinAdapter.parse_inbound()
  │     │
  │     ├── 检测 raw_data["_media_items"] 存在
  │     │
  │     ├── 调用 weixin_media.process_inbound_media()
  │     │     │
  │     │     ├── 解析 image_item → 提取 encrypt_query_param + aes_key
  │     │     │
  │     │     ├── weixin_cdn.download_and_decrypt()
  │     │     │     ├── 构建 CDN download URL
  │     │     │     ├── httpx GET 下载密文
  │     │     │     └── weixin_crypto.decrypt_aes_ecb() 解密
  │     │     │
  │     │     └── 转为 base64 data URI → 填入 InboundMessage.images[]
  │     │
  │     └── 返回 InboundMessage(images=["data:image/jpeg;base64,..."])
  │
  ├── raw_msg.item_list[0].type == 3 (VOICE)
  │     │
  │     ├── 优先路径: voice_item.text 存在 → 直接用转写文本
  │     │     └── InboundMessage(text=voice_text, msg_type="voice")
  │     │
  │     └── 降级路径: 下载解密 → raw_data["_voice_data"] = base64
  │           └── InboundMessage(text="[语音消息]", msg_type="voice")
  │
  ├── raw_msg.item_list[0].type == 4 (FILE)
  │     │
  │     ├── 下载解密文件 → base64
  │     └── InboundMessage(text="[文件: xxx.pdf]",
  │           raw_data={"_file_data": base64, "_file_name": "xxx.pdf"})
  │
  └── raw_msg.item_list[0].type == 5 (VIDEO)
        │
        ├── 下载解密视频 → base64
        └── InboundMessage(text="[视频消息]",
              raw_data={"_video_data": base64})

  ▼
pipeline.process_message()
  │
  ▼
forward_to_agent_with_user_project()
  │
  ├── images 字段已有数据 → request_body["images"] (已有逻辑)
  └── raw_data 中的文件/语音/视频 → 未来可扩展
```

#### 出站多媒体消息流

```
Agent 回复 (pipeline → _send → WeixinAdapter.send_outbound)
  │
  ├── OutboundMessage.extra.get("image_urls") 存在
  │     │
  │     ▼
  │   WeixinAdapter.send_outbound()
  │     │
  │     ├── 遍历 image_urls
  │     │     │
  │     │     ├── httpx GET 下载图片（支持 http/https URL 和 data: URI）
  │     │     │
  │     │     ├── weixin_media.upload_media()
  │     │     │     ├── 生成 16 字节随机 AES key
  │     │     │     ├── 计算 MD5 + 文件大小
  │     │     │     ├── WeixinClient.get_upload_url() → 获取 upload_param
  │     │     │     ├── weixin_crypto.encrypt_aes_ecb() 加密
  │     │     │     └── weixin_cdn.encrypt_and_upload() → 获取 download_param
  │     │     │
  │     │     └── WeixinClient.send_media_message() 发送图片消息
  │     │
  │     ├── 发送文本消息（如果有 text）
  │     └── 返回 SendResult(success=True, parts_sent=N)
  │
  ├── OutboundMessage.extra.get("file_path") 存在
  │     └── 类似图片流程，使用 FILE media_type
  │
  └── 纯文本 → 现有 send_message() 逻辑不变
```

#### 错误处理策略

| 场景 | 处理方式 | 影响 |
|---|---|---|
| CDN 下载超时 | 回退为占位文本 `[图片下载失败]` | 不影响后续消息 |
| AES 解密失败 | 回退为占位文本 `[图片解密失败]` | 不影响后续消息 |
| CDN 上传失败（出站）| 回退为发送文本 URL（如有）或错误提示 | 返回 SendResult(success=False) |
| getuploadurl API 失败 | 重试 1 次后回退 | 返回 SendResult(success=False) |
| 文件超过大小限制 | 跳过下载，发送 `[文件过大]` 提示 | 不影响后续消息 |
| 未知媒体类型 | 保持现有占位符逻辑 | 不影响后续消息 |

### 5. Implementation Phases Mapping to User Stories

| Phase | User Stories | Priority | 模块 |
|---|---|---|---|
| Phase A: 加解密基础 | (基础设施) | — | `weixin_crypto.py` |
| Phase B: CDN 操作 | (基础设施) | — | `weixin_cdn.py` |
| Phase C: 入站图片 | US1 | P1 | `weixin_media.py` + `weixin.py` + `routes/weixin.py` |
| Phase D: 出站图片 | US2 | P1 | `weixin_media.py` + `weixin.py` + `weixin.py (client)` |
| Phase E: 入站语音 | US3 | P2 | `weixin_media.py` |
| Phase F: 文件收发 | US4 | P2 | `weixin_media.py` + `weixin.py` |
| Phase G: 视频收发 | US5 | P3 | `weixin_media.py` + `weixin.py` |
| Phase H: 测试 | (质量保证) | — | `tests/unit/test_weixin_*.py` |

---

## Quickstart

### 开发环境准备

```bash
cd platform/as-dispatch/.worktrees/weixin

# 安装依赖（pycryptodome 已在 pyproject.toml 中）
uv sync

# 验证 pycryptodome 可用
python -c "from Crypto.Cipher import AES; print('AES OK')"
```

### 运行测试

```bash
# 运行所有微信媒体相关测试
uv run pytest tests/unit/test_weixin_crypto.py -v
uv run pytest tests/unit/test_weixin_cdn.py -v
uv run pytest tests/unit/test_channel_weixin_media.py -v

# 运行全量测试确保无回归
uv run pytest
```

### 手动验证流程

1. **入站图片**：通过微信发送一张图片给 Bot，检查日志输出：
   - `[weixin] 媒体下载成功: type=image, size=XXXbytes`
   - Agent 是否收到 `images` 字段

2. **出站图片**：向 Agent 发送 "画一只猫" 等图片生成指令：
   - 检查日志：`[weixin] 媒体上传成功: filekey=XXX`
   - 微信聊天中是否出现图片（而非文本链接）

3. **语音转写**：发送语音消息，检查 Agent 是否收到文本内容

4. **错误回退**：断开网络后发送图片，验证不崩溃且后续文本消息正常

---

## Complexity Tracking

| Area | Estimated Effort | Risk | Notes |
|---|---|---|---|
| AES-128-ECB crypto | 低 | 低 | 标准算法，pycryptodome 直接支持 |
| CDN download/decrypt | 中 | 中 | AES key 编码格式需仔细处理（hex vs base64） |
| CDN upload pipeline | 中 | 中 | getuploadurl API 未有文档，依赖参考实现 |
| 入站消息解析重构 | 中 | 低 | 需重构 `_parse_weixin_message()` 传递 item_list |
| 出站图片发送 | 高 | 中 | 完整 pipeline: 下载→加密→上传→构建消息→发送 |
| 语音转写优先路径 | 低 | 低 | 直接读取 `voice_item.text` 字段 |
| 文件/视频收发 | 中 | 低 | 与图片流程类似，增加 file_name 等元数据 |
| `_parse_weixin_message` 原始数据传递 | 低 | 低 | 将 item_list 完整传入 raw_data |

---

## Key Technical Decisions Summary

1. **不修改 `base.py`** — 通过已有的 `images[]` 和 `extra` 字段传递媒体数据 (Principle 9)
2. **使用 `pycryptodome`** — 已在依赖中，无需引入新库
3. **分层架构** — crypto → cdn → media → adapter，每层可独立测试
4. **临时文件策略** — 媒体转为 base64 内存处理，图片走 `InboundMessage.images`，避免磁盘 I/O 管理
5. **CDN Base URL 可配置** — 存储在 `platform_config` JSON 字段，默认 `novac2c.cdn.weixin.qq.com/c2c`
6. **出站媒体通过 `extra` 字典传递** — `OutboundMessage.extra["image_urls"]` / `extra["file_path"]`
7. **AES key 双格式兼容** — 入站时自动检测 base64(raw bytes) vs base64(hex string) 两种编码

---

## Readiness for Task Breakdown

✅ **Ready** — 所有技术决策已明确，无未解决的 NEEDS CLARIFICATION 项。

已完成的设计产物：
- `plan.md` (本文件) — 完整技术方案
- 数据模型定义 — `CDNMedia`, `MediaDownloadResult`, `MediaUploadResult`, `WeixinMediaType`
- API 合约 — `get_upload_url()`, `send_media_message()`, CDN 操作接口
- 实现分阶段计划 — Phase A~H 对应 User Stories
- 错误处理策略 — 全覆盖 graceful degradation
- 宪法合规 — 10 项原则全部 PASS
