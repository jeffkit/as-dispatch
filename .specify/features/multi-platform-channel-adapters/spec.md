# Feature Specification: Multi-Platform IM ChannelAdapter Unification

**Feature Branch**: `feature/im-integration`  
**Created**: 2026-03-02  
**Status**: Draft  
**Project**: `platform/as-dispatch` (intelligent-bot worktree)

---

## Background

The `as-dispatch` service dispatches incoming IM messages to an AI backend and returns responses to users. It already has a production-ready unified architecture:

- A `ChannelAdapter` abstract base class that standardizes how any IM platform's messages are parsed and sent
- A unified 10-step processing pipeline that is platform-agnostic
- A `WeComAdapter` (WeCom/企业微信) that is complete and in production

Four other IM platforms — **Telegram**, **Lark (飞书)**, **Discord**, and **Slack** — each have their own client and route code, but none are wired into the unified adapter architecture or pipeline. As a result, these platforms either have no AI processing, or require separate, duplicated processing code that diverges from the production-grade WeChat path.

This feature connects all four remaining platforms to the same unified architecture that WeChat already uses, so that all five platforms share identical processing quality, observability, and maintainability.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Telegram Bot Receives and Replies to Messages (Priority: P1)

A Telegram user sends a text or image message to the bot. The bot parses the message into the unified format, runs it through the AI processing pipeline, and replies directly in the same Telegram chat.

**Why this priority**: Telegram is one of the most widely used platforms in the target user group. Delivering a working AI bot on Telegram provides immediate, high-visibility value and validates that the adapter pattern works for a new platform end-to-end.

**Independent Test**: Deploy the Telegram adapter in isolation, send a "hello" message to the bot on Telegram, and verify the bot replies with a coherent AI-generated response.

**Acceptance Scenarios**:

1. **Given** a Telegram user sends a plain text message to the bot, **When** the bot receives the update webhook, **Then** the bot replies with an AI-generated response in the same chat within 30 seconds.
2. **Given** a Telegram user sends a message containing an image, **When** the bot processes the update, **Then** the image URL is included in the message passed to the AI pipeline, and the bot acknowledges the image in its reply.
3. **Given** another Telegram bot sends a message to the chat, **When** the webhook fires, **Then** the bot silently ignores the message and sends no reply.
4. **Given** a Telegram user sends a message that the bot cannot process (e.g., sticker only), **When** the error occurs, **Then** the error is logged and no unhandled exception propagates; other platforms continue to function normally.

---

### User Story 2 — Lark (飞书) Bot Receives and Replies to Messages (Priority: P2)

A Lark user sends a text or image message in a Lark group where the bot is a member. The bot responds with an AI-generated reply using Lark's card or text message format.

**Why this priority**: Lark is the primary collaboration platform for many Chinese enterprise teams. Its event-based callback structure (with AES encryption and URL verification handshakes) is more complex than Telegram, so it is tackled second to ensure the adapter pattern handles non-trivial parsing requirements.

**Independent Test**: Configure the Lark adapter with a test Lark app, send a message in a test group, and verify an AI reply appears in the group.

**Acceptance Scenarios**:

1. **Given** a Lark group member sends a text message, **When** the `p2.im.message.receive_v1` event arrives, **Then** the bot decrypts the event, parses the message, and sends an AI reply in the same group.
2. **Given** the Lark platform sends a URL verification challenge, **When** the callback is received, **Then** the adapter immediately returns the required challenge response without passing the event to the AI pipeline.
3. **Given** a Lark message contains an image, **When** the adapter parses the event, **Then** the image is extracted and included in the `images` field of the unified message.
4. **Given** an encrypted Lark callback arrives, **When** AES decryption fails due to a wrong key, **Then** the error is logged with a `WARNING` and the request returns a safe HTTP error response rather than an unhandled 500.

---

### User Story 3 — Discord Bot Receives and Replies to Messages (Priority: P3)

A Discord user interacts with the bot in a Discord channel. The bot processes the message via the AI pipeline and sends a text reply back to the channel.

**Why this priority**: Discord's interaction webhook format differs structurally from event-based platforms, providing a third distinct adapter pattern to validate. It is ranked P3 because Discord usage is lower than Telegram and Lark in the current target audience.

**Independent Test**: Set up a Discord bot in a test server, send a message, and confirm the bot posts an AI reply in the same channel.

**Acceptance Scenarios**:

1. **Given** a Discord user sends a text message in a channel where the bot is present, **When** the Discord interaction webhook fires, **Then** the bot sends an AI-generated reply in that channel.
2. **Given** a Discord message contains one or more image attachments, **When** the adapter parses the payload, **Then** all image attachment URLs are included in the unified message's `images` field.
3. **Given** the bot itself posts a message, **When** the webhook fires, **Then** the adapter identifies the bot as the sender and silently ignores the message.

---

### User Story 4 — Slack Bot Receives and Replies to Messages (Priority: P4)

A Slack user sends a message in a Slack channel where the bot is installed. The bot processes the message and replies using Slack's message API.

**Why this priority**: Slack is P4 because it is the fourth distinct platform pattern and also requires URL verification handling similar to Lark. It is lower priority than Discord because of lower internal adoption, but all four platforms are committed to this release.

**Independent Test**: Install the Slack bot in a test workspace channel, send a message, and confirm the bot replies in thread or channel.

**Acceptance Scenarios**:

1. **Given** a Slack user sends a message in a channel where the bot is installed, **When** the Slack event callback arrives, **Then** the bot replies with an AI-generated response.
2. **Given** Slack sends an `url_verification` challenge, **When** the callback is received, **Then** the adapter returns the challenge response immediately without processing through the pipeline.
3. **Given** the `X-Slack-Retry-Num` HTTP header is present on an incoming request, **When** the callback is received, **Then** the adapter ignores the retry and returns 200 without forwarding to the pipeline.
4. **Given** a Slack bot posts a message, **When** the event fires, **Then** the adapter identifies the message as a bot message and silently ignores it.
5. **Given** a Slack message contains image file attachments, **When** the adapter parses the event, **Then** the image file URLs are included in the unified message's `images` field.

---

### User Story 5 — Unified Callback Entry Routes to Any Registered Platform (Priority: P1)

An operator registers any of the five supported platforms. All five platforms share the same unified callback endpoint, which dynamically routes to the appropriate adapter based on a platform identifier — without requiring new code for each new platform.

**Why this priority**: This is the architectural backbone that multiplies the value of all other user stories. Without it, each new platform requires its own routing logic and the unified pipeline provides no leverage.

**Independent Test**: Register two platforms (e.g., WeChat and Telegram), send a message from each, and confirm both are processed correctly through the same unified endpoint code path.

**Acceptance Scenarios**:

1. **Given** all five adapters are registered at service startup, **When** a callback arrives for any registered platform, **Then** the unified endpoint dynamically dispatches to the correct adapter without any platform-specific conditional logic in the route handler.
2. **Given** a callback arrives for an unregistered platform name, **When** the unified endpoint handles it, **Then** the system returns a clear error response and logs a `WARNING`; no other platform is affected.
3. **Given** WeChat is already processing messages via the unified pipeline, **When** the new adapters are deployed, **Then** WeChat message processing continues to function exactly as before with no regression.
4. **Given** all five platforms are registered, **When** any single platform's adapter raises an exception during processing, **Then** the exception is contained within that adapter; the other four platforms continue to process their messages normally.

---

### Edge Cases

- What happens when a platform sends a duplicate message ID (retry)? The system must de-duplicate to avoid sending the AI pipeline the same message twice.
- What happens when the AI backend is temporarily unavailable? The adapter returns an error response to the platform; the error is logged; no message is silently dropped.
- What happens when a message's text is empty (image-only message)? The adapter populates `images` and leaves `text` as an empty string; the pipeline handles image-only input gracefully.
- What happens when an adapter receives a callback type it does not recognize (e.g., a new Slack event type)? The `should_ignore()` method returns `True` or the adapter logs a `DEBUG` message and returns a safe 200 response.
- What happens when a platform's AES key or bot token is misconfigured? The adapter catches the error, logs it at `ERROR` level, and returns a non-200 response; other platforms are unaffected.

---

## Requirements *(mandatory)*

### Functional Requirements

**Telegram Adapter**

- **FR-001**: The system MUST parse Telegram `Update` objects into `InboundMessage`, extracting sender ID, sender name, chat ID, message text, and any photo URLs.
- **FR-002**: The system MUST filter out Telegram bot-originated messages so they are never forwarded to the AI pipeline.
- **FR-003**: The system MUST include all photo attachments from a Telegram message in the `InboundMessage.images` list.
- **FR-004**: The `TelegramAdapter` MUST delegate all outbound HTTP calls to the existing `TelegramClient` in `forward_service/clients/telegram.py`.

**Lark (飞书) Adapter**

- **FR-005**: The system MUST handle Lark's `p2.im.message.receive_v1` event structure, correctly extracting sender, chat, and message content.
- **FR-006**: The system MUST perform AES decryption on encrypted Lark event payloads before parsing.
- **FR-007**: The system MUST respond to Lark URL verification challenges immediately, without passing them through the AI pipeline.
- **FR-008**: The system MUST extract image content from Lark messages and populate `InboundMessage.images`. **Note**: For Lark, the MVP implementation stores the Lark `image_key` (not a public URL) in `images` due to Lark's access-controlled image download API. URL resolution requires an authenticated call to Lark's file API and is deferred to a follow-up iteration.
- **FR-009**: The `LarkAdapter` MUST delegate all outbound calls to the existing `LarkClient` in `forward_service/clients/lark.py`.

**Discord Adapter**

- **FR-010**: The system MUST parse Discord's interaction webhook payload format into `InboundMessage`.
- **FR-011**: The system MUST filter out messages sent by the bot itself (self-messages).
- **FR-012**: The system MUST extract image attachment URLs from Discord messages into `InboundMessage.images`.
- **FR-013**: The `DiscordAdapter` MUST delegate all outbound calls to the existing `DiscordBotClient` in `forward_service/clients/discord.py`.

**Slack Adapter**

- **FR-014**: The system MUST parse Slack's event callback format (event type: `message`) into `InboundMessage`.
- **FR-015**: The system MUST respond to Slack URL verification challenges immediately.
- **FR-016**: The system MUST ignore message retries identified by the `X-Slack-Retry-Num` HTTP header.
- **FR-017**: The system MUST filter out bot-originated Slack messages.
- **FR-018**: The system MUST extract image file URLs from Slack messages into `InboundMessage.images`.
- **FR-019**: The `SlackAdapter` MUST delegate all outbound calls to the existing `SlackClient` in `forward_service/clients/slack.py`.

**Unified Routing**

- **FR-020**: All four new adapters (Telegram, Lark, Discord, Slack) MUST be registered in the adapter registry at service startup.
- **FR-021**: The unified callback endpoint MUST dynamically look up the adapter by platform name from the registry — no hardcoded platform-name checks in the route handler.
- **FR-022**: The existing independent routes for Telegram, Lark, Discord, and Slack MUST remain operational for backward compatibility. The route **paths** and **WebSocket lifecycle code** (e.g., Discord's `on_message` gateway connection) are immutable. Handler function bodies may be updated to delegate to the unified pipeline where doing so is the only way to integrate the adapter; such changes are additive and do not break the external contract.
- **FR-023**: The existing WeComAdapter registration and all WeChat message-processing flows MUST be entirely unmodified.

**Cross-Cutting**

- **FR-024**: Each new adapter MUST implement all five members of the `ChannelAdapter` contract: `platform`, `parse_inbound()`, `send_outbound()`, `extract_bot_key()`, and `should_ignore()`.
- **FR-025**: Each adapter MUST contain its own exception handling such that a failure in one adapter does not affect other adapters or the service as a whole.
- **FR-026**: Each adapter MUST produce structured log output: `INFO` for inbound/outbound events, `DEBUG` for ignored messages, `WARNING` for unexpected input, `ERROR` (with stack trace) for failures.

### Key Entities

- **InboundMessage**: The unified internal representation of a user-sent message. Key attributes: `platform`, `bot_key`, `user_id`, `user_name`, `chat_id`, `chat_type`, `text`, `images`, `msg_type`, `message_id`, `raw_data`.
- **OutboundMessage**: The unified internal representation of a reply to be sent. Key attributes: `chat_id`, `text`, `msg_type`, `bot_key`, `mentioned_user_ids`, `extra`.
- **SendResult**: The outcome of an outbound send operation. Attributes: `success`, `parts_sent`, `error`.
- **ChannelAdapter**: The abstract interface that every platform adapter implements. Defines the five-member contract.
- **AdapterRegistry**: The registry that maps platform name strings (e.g., `"telegram"`, `"lark"`) to their corresponding adapter instances.
- **Platform Client**: An existing client module (`telegram.py`, `lark.py`, `discord.py`, `slack.py`) that handles the raw HTTP communication with each platform's API.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All five IM platforms (WeChat, Telegram, Lark, Discord, Slack) can receive user messages and deliver AI-generated replies end-to-end, verified by a functional test for each platform.
- **SC-002**: A message sent on any of the four new platforms reaches the AI pipeline and receives a reply within 30 seconds under normal load conditions.
- **SC-003**: Zero regressions in WeChat message handling — all existing WeChat functional tests continue to pass after the new adapters are deployed.
- **SC-004**: An error in one platform's adapter (e.g., a malformed Telegram payload) does not prevent the other four platforms from processing their messages, verified by injecting a parse error on one adapter while the other four process concurrent messages.
- **SC-005**: Each adapter has unit test coverage for `parse_inbound()` (happy path + at least one error path) and `send_outbound()` (success + failure), so that any single adapter can be validated without running external services.
- **SC-006**: Image messages from all four new platforms are correctly forwarded to the AI pipeline with at least one entry in the `images` field. For Telegram, Discord, and Slack this will be a public URL; for Lark this will be an `image_key` (see FR-008 note).
- **SC-007**: URL verification challenges from Lark and Slack are acknowledged within the platform's required response window (typically under 3 seconds).
- **SC-008**: Bot-originated messages on Telegram, Discord, and Slack are filtered and never forwarded to the AI pipeline, verified by sending bot messages and confirming no AI reply is generated.

---

## Assumptions

- The existing `forward_service/clients/telegram.py`, `lark.py`, `discord.py`, and `slack.py` already provide adequate API coverage (send text, send image reference, handle auth) for the adapter's outbound needs. If a required client method is missing, it will be treated as a dependency that must be resolved before the corresponding adapter can be completed.
- The `forward_service/pipeline.py` unified pipeline requires no changes to accommodate the new adapters; it is already platform-agnostic.
- The `unified_callback.py` route requires only a small, localized change (registry lookup instead of hardcoded platform check) to support dynamic dispatch; no new route files are needed for the four new platforms.
- Bot tokens and app credentials for each platform are already provisioned or will be provisioned by the operator; credential management is out of scope for this feature.
- The existing `WeComAdapter` serves as the canonical structural reference; all new adapters will follow its internal layout.

## Out of Scope

- DingTalk, WhatsApp, Microsoft Teams, Line (planned for Phase 2/3)
- Changes to the database-backed bot configuration model
- New management UI or configuration interfaces
- Any modifications to `WeComAdapter`, `pipeline.py`, or `forward_service/channel/base.py`
- Rate limiting, quota management, or per-platform message throttling
- End-to-end encryption beyond what each platform already provides
