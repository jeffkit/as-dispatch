# Implementation Plan: 个人微信通道接入 (Weixin Channel)

**Branch**: `001-weixin-channel` | **Date**: 2026-03-22 | **Spec**: `specs/001-weixin-channel/spec.md`
**Input**: Feature specification from `/specs/001-weixin-channel/spec.md`

## Summary

Integrate personal WeChat (个人微信) as a new messaging channel in as-dispatch via the Tencent iLinkAI protocol (`https://ilinkai.weixin.qq.com`). The implementation follows the established QQBot adapter pattern (HTTP long-polling background task, admin lifecycle API, pipeline injection) and fully complies with the ChannelAdapter interface contract. Three new modules are introduced: `WeixinClient` (HTTP client), `WeixinAdapter` (channel adapter), and `weixin` routes (admin API + long-poll lifecycle). Three existing files are modified additively (app.py, channel/__init__.py, routes/__init__.py).

## Technical Context

**Language/Version**: Python 3.11+ with FastAPI (per constitution P1)
**Primary Dependencies**: `httpx` (AsyncClient for iLinkAI HTTP API), FastAPI, existing `forward_service` modules
**Storage**: SQLAlchemy (existing as-dispatch DB) for bot credentials + `get_updates_buf` cursor persistence; in-memory dict for `context_token` cache
**Testing**: pytest with httpx mock fixtures; test path `tests/unit/test_channel_weixin.py`
**Target Platform**: Linux server (same as-dispatch deployment)
**Project Type**: Single project — additive module within `forward_service/`
**Performance Goals**: ≤5s channel overhead per message round-trip; sustain 10 concurrent WeChat accounts
**Constraints**: 35s server-side long-poll timeout (40s client timeout); session expiry pause 1 hour; only private chat (no group)
**Scale/Scope**: Up to 10 simultaneous WeChat bot accounts per as-dispatch instance

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

*Source: `.specify/memory/constitution.md` v1.0.0*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| P1 | Python 3.11+, FastAPI, async handlers only | ✅ | All route handlers and client methods are async. Long-poll loop uses `asyncio.Task`. |
| P2 | All functions have type annotations | ✅ | Every function/method will carry full type annotations including return types. |
| P3 | Exceptions caught per-adapter; `send_outbound` returns `SendResult` on error | ✅ | `send_outbound` wraps all send logic in try/except, returns `SendResult(success=False, error=...)`. `parse_inbound` catches and logs, re-raises as ValueError. |
| P4 | Subclass `ChannelAdapter`; all 5 members implemented | ✅ | `WeixinAdapter` implements: `platform` property, `should_ignore()`, `extract_bot_key()`, `parse_inbound()`, `send_outbound()`. |
| P5 | Mirrors WeComAdapter structure (docstring → constants → methods → helpers) | ✅ | Module follows: docstring → constants → adapter class (platform → should_ignore → extract_bot_key → parse_inbound → send_outbound) → `# ===== 内部方法 =====` section. |
| P6 | `logger = logging.getLogger(__name__)` in each module; mandatory log events | ✅ | All 3 new modules declare module-level logger. INFO for inbound/outbound, DEBUG for ignored, WARNING for parse failures, ERROR with exc_info for send/network failures. Token values truncated. |
| P7 | Uses existing `forward_service/clients/`; no raw HTTP sessions in adapters | ✅ | New `forward_service/clients/weixin.py` created first. Adapter delegates all HTTP calls to `WeixinClient`. No raw httpx usage in adapter or routes. |
| P8 | Adapter unit-testable in isolation; tests in `tests/unit/test_channel_weixin.py` | ✅ | `parse_inbound` / `extract_bot_key` testable with plain dicts. `send_outbound` testable with mocked `WeixinClient`. |
| P9 | Additive only; existing routes and WeComAdapter unchanged | ✅ | Only additive changes: new adapter registered in app.py lifespan, new import in channel/__init__.py, new router in routes/__init__.py. Zero modifications to existing adapters/routes. |
| P10 | All network calls async; no blocking I/O in event loop | ✅ | `httpx.AsyncClient` for all iLinkAI API calls. `asyncio.sleep` for backoff/pause. No `time.sleep` or synchronous HTTP. |

## Project Structure

### Documentation (this feature)

```text
specs/001-weixin-channel/
├── spec.md              # Feature specification (already exists)
├── plan.md              # This file
├── research.md          # Phase 0: technical decisions
├── data-model.md        # Phase 1: entity definitions
├── quickstart.md        # Phase 1: run & test guide
├── contracts/           # Phase 1: API endpoint definitions
│   └── admin-api.md     # Admin REST API for Weixin bot management
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
forward_service/
├── clients/
│   └── weixin.py          # [NEW] WeixinClient — iLinkAI HTTP API client
├── channel/
│   ├── __init__.py         # [MODIFY] Add WeixinAdapter export
│   └── weixin.py           # [NEW] WeixinAdapter — ChannelAdapter implementation
├── routes/
│   ├── __init__.py         # [MODIFY] Add weixin_admin_router export
│   └── weixin.py           # [NEW] Admin routes + long-poll lifecycle + QR login API
└── app.py                  # [MODIFY] Register WeixinAdapter + lifespan startup

tests/
└── unit/
    └── test_channel_weixin.py  # [NEW] Unit tests for WeixinAdapter
```

**Structure Decision**: Follows the established QQBot pattern exactly — client module for HTTP API encapsulation, channel module for adapter logic, routes module for lifecycle and admin endpoints. This is the canonical pattern for long-poll/WebSocket-based adapters in as-dispatch.

## Architecture Overview

### Message Flow

```
┌──────────────┐     long-poll (35s)     ┌──────────────────────┐
│  iLinkAI     │ ◄──────────────────────► │  WeixinClient        │
│  Protocol    │      POST /getupdates    │  (clients/weixin.py) │
│  Server      │                          └──────────┬───────────┘
│              │ ◄── POST /sendmessage ──             │
│              │ ◄── POST /sendtyping ──              │
│              │ ◄── GET /get_bot_qrcode ──           │
└──────────────┘                          ┌───────────┴──────────┐
                                          │  WeixinPoller        │
                                          │  (routes/weixin.py)  │
                                          │  asyncio.Task loop   │
                                          └───────────┬──────────┘
                                                      │ raw_msg dict
                                          ┌───────────┴──────────┐
                                          │  WeixinAdapter       │
                                          │  (channel/weixin.py) │
                                          │  parse_inbound()     │
                                          └───────────┬──────────┘
                                                      │ InboundMessage
                                          ┌───────────┴──────────┐
                                          │  pipeline.py         │
                                          │  process_message()   │
                                          └───────────┬──────────┘
                                                      │ OutboundMessage
                                          ┌───────────┴──────────┐
                                          │  WeixinAdapter       │
                                          │  send_outbound()     │
                                          │    → WeixinClient    │
                                          │      .send_message() │
                                          └──────────────────────┘
```

### Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| **WeixinClient** | `clients/weixin.py` | HTTP API encapsulation: QR login, status polling, getupdates, sendmessage, typing. Manages httpx.AsyncClient lifecycle, auth headers, error classification. |
| **WeixinAdapter** | `channel/weixin.py` | ChannelAdapter interface: parse iLinkAI messages → InboundMessage, convert OutboundMessage → iLinkAI send. context_token cache management. |
| **WeixinPoller** | `routes/weixin.py` | Background long-poll loop (asyncio.Task). Retry/backoff logic. Session expiry detection. Injects messages into pipeline via `handle_weixin_message()`. |
| **Admin Routes** | `routes/weixin.py` | FastAPI endpoints: QR login trigger, QR status poll, bot start/stop/status. |

### Key Design Decisions

1. **Long-poll vs. background task**: Like QQBot's WebSocket Gateway, the long-poll loop runs as a background `asyncio.Task` per bot account. This is managed by `WeixinPoller` in routes/weixin.py.

2. **context_token cache**: In-memory `dict[(account_id, user_id)] → context_token` stored on the `WeixinPoller` instance. Updated on every inbound message. Used by `send_outbound()` to echo the token. Acceptable to lose on restart (next inbound message repopulates it).

3. **get_updates_buf persistence**: Stored in the bot's `platform_config` JSON field in the database (same pattern as QQBot credentials). Persisted after each successful poll cycle. On startup, loaded from DB to resume without message gap.

4. **Session expiry handling**: When `errcode=-14` is detected, the poller enters a 1-hour `asyncio.sleep` pause. After pause, it retries with existing credentials. If retry also fails, it transitions the bot to `expired` status requiring re-login.

5. **QR login flow**: Stateless from the server perspective — the admin triggers QR generation, polls status, and the system captures credentials on confirmation. Credentials are persisted to DB for subsequent startups.

6. **Multi-account isolation**: Each WeChat account gets its own `WeixinPoller` instance with independent state (polling cursor, context_token cache, backoff counter). Stored in a module-level `weixin_pollers: dict[str, WeixinPoller]` dict.

## Complexity Tracking

No constitution violations — no entries needed.
