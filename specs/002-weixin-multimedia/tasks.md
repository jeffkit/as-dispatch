# Tasks: 微信个人号多媒体消息收发

**Input**: Design documents from `/specs/002-weixin-multimedia/`
**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Tests**: Unit tests are included as the plan explicitly specifies test files for crypto, CDN, and media modules.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: 验证开发环境和依赖可用性

- [X] T001 验证 `pycryptodome` 依赖可用：运行 `python -c "from Crypto.Cipher import AES; print('OK')"` 确认 AES 模块就绪（pyproject.toml 已包含 pycryptodome>=3.20.0，无需新增依赖）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 加解密基础设施 + CDN 操作 + 媒体类型定义，所有 User Story 的共享基础层

**⚠️ CRITICAL**: 所有 User Story 均依赖此阶段的三个模块完成

### 2A: AES 加解密工具

- [X] T002 [P] 创建 AES-128-ECB 加解密模块 `forward_service/clients/weixin_crypto.py`，实现以下纯函数：`encrypt_aes_ecb(plaintext, key) -> bytes`（PKCS7 padding）、`decrypt_aes_ecb(ciphertext, key) -> bytes`（PKCS7 unpadding）、`aes_ecb_padded_size(plaintext_size) -> int`（计算密文大小）、`parse_aes_key(raw_key_str) -> bytes`（支持 hex 字符串和 base64 双格式自动检测：16 字节直接用、32 字节 hex 字符先 hex decode），使用 `Crypto.Cipher.AES` + `Crypto.Util.Padding`
- [X] T003 [P] 创建 AES 加解密单元测试 `tests/unit/test_weixin_crypto.py`：覆盖加密-解密往返、PKCS7 padding 正确性、parse_aes_key hex 格式、parse_aes_key base64 格式、parse_aes_key 32 字节 hex-in-base64 格式、空输入和错误密钥的异常处理

### 2B: CDN 上传/下载操作

- [X] T004 创建 CDN 媒体操作模块 `forward_service/clients/weixin_cdn.py`，实现：`download_and_decrypt(http_client, cdn_base_url, encrypt_query_param, aes_key_raw) -> bytes`（构建 CDN download URL，httpx GET 下载，调用 weixin_crypto.decrypt_aes_ecb 解密）、`encrypt_and_upload(http_client, cdn_base_url, upload_param, filekey, plaintext, aes_key) -> str`（调用 weixin_crypto.encrypt_aes_ecb 加密，httpx PUT 上传到预签名 URL），所有操作设置超时（WEIXIN_MEDIA_DOWNLOAD_TIMEOUT=60s / WEIXIN_MEDIA_UPLOAD_TIMEOUT=60s）
- [X] T005 创建 CDN 操作单元测试 `tests/unit/test_weixin_cdn.py`：mock httpx 请求，覆盖下载成功+解密、下载超时、下载 404、上传成功、上传超时等场景

### 2C: 媒体类型定义

- [X] T006 [P] 创建媒体类型和处理模块 `forward_service/channel/weixin_media.py`，定义 dataclass：`CDNMedia(encrypt_query_param, aes_key, encrypt_type)`、`MediaDownloadResult(data, media_type, file_name, success, error)`、`MediaUploadResult(filekey, download_encrypted_query_param, aes_key_hex, file_size, file_size_ciphertext, success, error)`，定义 IntEnum `WeixinMediaType(IMAGE=1, VIDEO=2, FILE=3, VOICE=4)`，以及配置常量 `DEFAULT_CDN_BASE_URL`、`WEIXIN_MEDIA_MAX_BYTES`

**Checkpoint**: 基础设施就绪 — crypto/CDN/types 三个模块可独立运行和测试，User Story 实现可以开始

---

## Phase 3: User Story 1 — 接收并处理图片消息 (Priority: P1) 🎯 MVP

**Goal**: 用户通过微信发送图片给 Bot，系统下载解密图片并通过 `InboundMessage.images` 字段传递给 Agent，替代当前的"暂不支持"占位文本

**Independent Test**: 通过微信发送一张图片给 Bot，验证 Agent 是否收到 base64 data URI 格式的图片数据（Agent 可对图片内容进行文字回复）

### Implementation for User Story 1

- [X] T007 [US1] 修改 `forward_service/routes/weixin.py` 的 `_parse_weixin_message()` 函数：当 `item_type` 为非文本类型（2/3/4/5）时，将完整 `item_list` 存入返回 dict 的 `_media_items` 字段，同时保留文本占位符作为 `content` 的降级值（兼容后续 adapter 未处理时的回退）
- [X] T008 [US1] 在 `forward_service/channel/weixin_media.py` 中实现入站图片处理函数 `process_inbound_image(http_client, cdn_base_url, image_item) -> MediaDownloadResult`：从 `image_item` 提取 `encrypt_query_param`（优先 `image_item.aeskey` hex 格式，备选 `image_item.media.aes_key` base64 格式），调用 `weixin_cdn.download_and_decrypt()`，检测 MIME 类型，返回解密后的图片 bytes
- [X] T009 [US1] 在 `forward_service/channel/weixin_media.py` 中实现入站媒体调度函数 `process_inbound_media(http_client, cdn_base_url, media_items) -> tuple[str, list[str], dict]`：遍历 media_items，按类型分发处理（Phase 3 仅实现图片分支），图片转为 `data:image/jpeg;base64,...` 格式存入 images 列表，返回 `(text, images, extra_raw_data)`
- [X] T010 [US1] 修改 `forward_service/channel/weixin.py` 的 `WeixinAdapter.parse_inbound()` 方法：检测 `raw_data` 中是否存在 `_media_items` 字段，若存在则获取 WeixinClient 的 httpx 实例和 `platform_config` 中的 `cdn_base_url`，调用 `weixin_media.process_inbound_media()` 处理媒体，将返回的 images 填入 `InboundMessage.images`。失败时回退为占位文本（Principle 3 错误隔离）
- [X] T011 [US1] 添加入站图片单元测试到 `tests/unit/test_channel_weixin_media.py`：mock CDN 下载，验证 image_item 解析、base64 data URI 生成、下载失败回退为占位文本、解密失败回退为占位文本

**Checkpoint**: 用户发送图片给 Bot → Agent 收到 `images` 字段中的 base64 图片数据 → 可独立验证

---

## Phase 4: User Story 2 — 发送图片消息给用户 (Priority: P1) 🎯 MVP

**Goal**: Agent 生成图片后，系统将图片加密上传到 CDN 并通过微信图片消息发送给用户，用户在微信中直接看到图片

**Independent Test**: 向 Agent 发送"画一只猫"等图片生成指令，验证微信聊天中是否出现图片消息（而非文本链接）

### Implementation for User Story 2

- [X] T012 [US2] 在 `forward_service/clients/weixin.py` 的 `WeixinClient` 中新增 `get_upload_url(filekey, media_type, to_user_id, rawsize, rawfilemd5, filesize, aeskey, no_need_thumb) -> dict` 方法：POST `/ilink/bot/getuploadurl`，传入文件元信息和 hex 编码的 AES key，返回 `{"upload_param": "...", "thumb_upload_param": "..."}`
- [X] T013 [US2] 在 `forward_service/clients/weixin.py` 的 `WeixinClient` 中新增 `send_media_message(to_user_id, context_token, item_list) -> dict` 方法：POST `/ilink/bot/sendmessage`，`item_list` 支持 `type=2`（image_item）等媒体项，复用已有认证头和 base_info 结构
- [X] T014 [US2] 在 `forward_service/channel/weixin_media.py` 中实现出站图片上传函数 `upload_media(http_client, weixin_client, cdn_base_url, to_user_id, data, media_type, file_name) -> MediaUploadResult`：生成随机 16 字节 AES key → 计算明文 MD5 和大小 → 调用 `weixin_client.get_upload_url()` 获取预签名 URL → 调用 `weixin_cdn.encrypt_and_upload()` → 返回 `MediaUploadResult`
- [X] T015 [US2] 在 `forward_service/channel/weixin_media.py` 中实现出站图片消息构建函数 `build_image_item(upload_result) -> dict`：根据 `MediaUploadResult` 构建 `{"type": 2, "image_item": {...}}` 结构体，包含 filekey、encrypt_query_param、aeskey 等字段
- [X] T016 [US2] 修改 `forward_service/channel/weixin.py` 的 `WeixinAdapter.send_outbound()` 方法：检测 `OutboundMessage.extra` 中是否存在 `image_urls` 列表，若存在则遍历 URL 列表（支持 http/https URL 和 data: URI），下载图片数据 → 调用 `upload_media()` → 调用 `build_image_item()` → 调用 `weixin_client.send_media_message()` 发送；文本和图片分别发送。上传失败时回退为发送文本 URL 或错误提示（Principle 3）
- [X] T017 [US2] 添加出站图片单元测试到 `tests/unit/test_channel_weixin_media.py`：mock WeixinClient 和 CDN 上传，验证 upload_media 流程、build_image_item 结构、send_outbound 图片+文本混合消息、上传失败回退

**Checkpoint**: Agent 返回图片 → 系统加密上传 CDN → 用户在微信中看到图片消息 → US1+US2 形成完整图片双向通信闭环（MVP 完成）

---

## Phase 5: User Story 3 — 接收语音消息并转为文本 (Priority: P2)

**Goal**: 用户通过微信发送语音消息，系统优先使用平台转写文本传递给 Agent；若无转写则传递原始语音数据

**Independent Test**: 通过微信发送一段语音消息给 Bot，验证 Agent 是否收到语音对应的文本内容

### Implementation for User Story 3

- [X] T018 [US3] 在 `forward_service/channel/weixin_media.py` 中实现入站语音处理函数 `process_inbound_voice(http_client, cdn_base_url, voice_item) -> tuple[str, dict]`：优先路径 — 检查 `voice_item.text` 或 `voice_item.voice_to_text` 字段，存在则直接使用转写文本返回 `(transcribed_text, {})`；降级路径 — 下载解密语音文件，返回 `("[语音消息]", {"_voice_data": base64_encoded})`
- [X] T019 [US3] 扩展 `forward_service/channel/weixin_media.py` 中 `process_inbound_media()` 的语音分支：当 item type=3 时调用 `process_inbound_voice()`，将转写文本设为消息 text，将可能的原始语音数据存入 extra_raw_data
- [X] T020 [US3] 添加入站语音单元测试到 `tests/unit/test_channel_weixin_media.py`：覆盖有转写文本直接使用、无转写文本下载语音、语音下载失败回退占位文本三个场景

**Checkpoint**: 用户发送语音 → Agent 收到转写文本或语音数据 → 可独立验证

---

## Phase 6: User Story 4 — 接收和发送文件 (Priority: P2)

**Goal**: 用户通过微信发送文件（PDF/Excel/Word 等）给 Bot，系统下载解密并转发给 Agent；Agent 生成文件时通过微信发送给用户

**Independent Test**: 通过微信发送一个 PDF 文件给 Bot，验证 Agent 是否收到文件数据和文件名

### Implementation for User Story 4

- [X] T021 [US4] 在 `forward_service/channel/weixin_media.py` 中实现入站文件处理函数 `process_inbound_file(http_client, cdn_base_url, file_item) -> tuple[str, dict]`：提取 `file_item.file_name`，检查文件大小是否超过 `WEIXIN_MEDIA_MAX_BYTES`（超限则跳过下载返回 "[文件过大]" 提示），下载解密文件，返回 `("[文件: xxx.pdf]", {"_file_data": base64, "_file_name": "xxx.pdf"})`
- [X] T022 [US4] 扩展 `forward_service/channel/weixin_media.py` 中 `process_inbound_media()` 的文件分支：当 item type=4 时调用 `process_inbound_file()`
- [X] T023 [US4] 在 `forward_service/channel/weixin_media.py` 中实现出站文件消息构建函数 `build_file_item(upload_result, file_name) -> dict`：构建 `{"type": 4, "file_item": {...}}` 结构体，包含文件名元数据
- [X] T024 [US4] 扩展 `forward_service/channel/weixin.py` 的 `WeixinAdapter.send_outbound()` 方法：检测 `OutboundMessage.extra` 中是否存在 `file_path` 或 `file_url`，存在则读取/下载文件数据 → 调用 `upload_media()` (media_type=FILE) → 调用 `build_file_item()` → 调用 `send_media_message()` 发送
- [X] T025 [US4] 添加文件收发单元测试到 `tests/unit/test_channel_weixin_media.py`：覆盖入站文件下载解密、文件过大跳过、文件名保留、出站文件上传发送

**Checkpoint**: 文件双向传输正常 → 文件名完整保留 → 超大文件优雅拒绝 → 可独立验证

---

## Phase 7: User Story 5 — 接收和发送视频消息 (Priority: P3)

**Goal**: 用户通过微信发送视频给 Bot，或 Agent 生成视频后通过微信发送给用户

**Independent Test**: 通过微信发送一段短视频给 Bot，验证 Agent 是否收到视频数据

### Implementation for User Story 5

- [X] T026 [US5] 在 `forward_service/channel/weixin_media.py` 中实现入站视频处理函数 `process_inbound_video(http_client, cdn_base_url, video_item) -> tuple[str, dict]`：下载解密视频，返回 `("[视频消息]", {"_video_data": base64})`；超时或过大时回退为占位文本
- [X] T027 [US5] 扩展 `forward_service/channel/weixin_media.py` 中 `process_inbound_media()` 的视频分支：当 item type=5 时调用 `process_inbound_video()`
- [X] T028 [US5] 在 `forward_service/channel/weixin_media.py` 中实现出站视频消息构建函数 `build_video_item(upload_result) -> dict`：构建 `{"type": 5, "video_item": {...}}` 结构体
- [X] T029 [US5] 扩展 `forward_service/channel/weixin.py` 的 `WeixinAdapter.send_outbound()` 方法：检测 `OutboundMessage.extra` 中是否存在 `video_url` 或 `video_path`，存在则下载/读取视频 → 调用 `upload_media()` (media_type=VIDEO) → 调用 `build_video_item()` → 发送
- [X] T030 [US5] 添加视频收发单元测试到 `tests/unit/test_channel_weixin_media.py`：覆盖入站视频下载、视频超时回退、出站视频上传

**Checkpoint**: 视频双向传输正常 → 五种消息类型（文本/图片/语音/文件/视频）全部覆盖

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 跨 User Story 的质量保障和边界场景加固

- [X] T031 [P] 在 `forward_service/channel/weixin_media.py` 中处理 `item_list` 多项共存场景：遍历所有 item 而非仅取 first_item，支持文本+图片混合消息、引用回复中的文本+媒体等组合
- [X] T032 [P] 在 `forward_service/channel/weixin.py` 中为 `cdn_base_url` 添加可配置支持：从 `platform_config.get("cdn_base_url", DEFAULT_CDN_BASE_URL)` 读取，确保不硬编码（FR-017）
- [X] T033 [P] 为所有媒体操作添加文件大小校验：入站下载前检查 Content-Length / 元数据中的 size 字段，超过 `WEIXIN_MEDIA_MAX_BYTES` 则跳过并返回友好提示（FR-018）
- [X] T034 运行全量测试 `uv run pytest` 确保无回归，验证所有现有文本消息测试用例通过率 100%（SC-007）
- [X] T035 [P] 更新 `forward_service/channel/weixin.py` 模块级 docstring，补充多媒体消息处理的架构说明

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖 — 立即开始
- **Foundational (Phase 2)**: 依赖 Phase 1 — **阻塞所有 User Story**
- **US1 (Phase 3)**: 依赖 Phase 2 完成
- **US2 (Phase 4)**: 依赖 Phase 2 完成；与 US1 可并行
- **US3 (Phase 5)**: 依赖 Phase 2 完成；与 US1/US2 可并行
- **US4 (Phase 6)**: 依赖 Phase 2 完成；与其他 Story 可并行
- **US5 (Phase 7)**: 依赖 Phase 2 完成；与其他 Story 可并行
- **Polish (Phase 8)**: 依赖所有 User Story 完成

### User Story Dependencies

- **US1 (P1)**: Phase 2 完成后可立即开始 — 无跨 Story 依赖
- **US2 (P1)**: Phase 2 完成后可立即开始 — 与 US1 独立（US2 需要额外的 WeixinClient 方法 T012/T013，但不依赖 US1 的入站逻辑）
- **US3 (P2)**: Phase 2 完成后可立即开始 — 复用 process_inbound_media 框架（如 US1 先完成则更顺畅，但非必须）
- **US4 (P2)**: Phase 2 完成后可立即开始 — 出站部分复用 upload_media（如 US2 先完成则更顺畅，但非必须）
- **US5 (P3)**: Phase 2 完成后可立即开始 — 与 US4 模式相同

### Within Each User Story

- 入站处理先于出站处理（US4/US5 内部）
- weixin_media.py 中的处理函数先于 weixin.py 中的 adapter 集成
- 单元测试作为 Story 的最后一个任务

### Parallel Opportunities

- **Phase 2**: T002 (crypto) 和 T006 (types) 可并行；T003 (crypto tests) 和 T006 可并行
- **Phase 3-7**: 所有 User Story 之间理论上可并行（共享 Phase 2 基础设施，修改不同的代码分支）
- **Phase 8**: T031、T032、T033、T035 可并行

---

## Parallel Example: Phase 2 Foundation

```bash
# 两个模块完全独立，可同时开发：
Task: "T002 — 创建 weixin_crypto.py (AES 加解密)"
Task: "T006 — 创建 weixin_media.py (类型定义)"

# crypto 完成后，CDN 和 crypto tests 可并行：
Task: "T003 — AES 单元测试"
Task: "T004 — 创建 weixin_cdn.py (CDN 操作)"
```

## Parallel Example: User Stories

```bash
# Phase 2 完成后，US1 和 US2 可并行开发（不同代码路径）：
Developer A: "T007→T008→T009→T010→T011 (US1 入站图片)"
Developer B: "T012→T013→T014→T015→T016→T017 (US2 出站图片)"
```

---

## Implementation Strategy

### MVP First (User Story 1 + 2 = 图片双向通信)

1. Complete Phase 1: Setup（验证环境）
2. Complete Phase 2: Foundational（crypto + CDN + types）
3. Complete Phase 3: US1 — 入站图片
4. Complete Phase 4: US2 — 出站图片
5. **STOP and VALIDATE**: 测试图片双向通信闭环
6. 部署/演示 MVP

### Incremental Delivery

1. Setup + Foundational → 基础设施就绪
2. US1 (入站图片) → 用户图片可被 Agent 理解 → 部署
3. US2 (出站图片) → Agent 可发送图片 → 部署（MVP 完成！）
4. US3 (语音接收) → 用户可发语音 → 部署
5. US4 (文件收发) → 办公文件双向传输 → 部署
6. US5 (视频收发) → 完整多媒体覆盖 → 部署
7. Polish → 边界场景加固 → 最终交付

---

## Notes

- [P] tasks = 不同文件、无依赖关系，可并行执行
- [Story] label 映射到 spec.md 中的 User Story 编号
- 所有新增代码须遵循 Constitution 10 项原则（plan.md 中已全部 PASS）
- 不修改 `base.py` — 图片走已有 `InboundMessage.images`，其他媒体走 `raw_data` 扩展字段
- 出站媒体通过 `OutboundMessage.extra` 字典传递（`image_urls` / `file_path` / `video_url`）
- 使用已有 `pycryptodome`，不引入新依赖
- 每个 Story 实现后可独立验证，避免回归风险
