# Feature Specification: 个人微信通道接入 (Weixin Channel)

**Feature Branch**: `001-weixin-channel`  
**Created**: 2026-03-22  
**Status**: Draft  
**Input**: User description: "Integrate personal WeChat (个人微信) as a new messaging channel in as-dispatch using the official Tencent iLinkAI protocol, enabling AgentStudio agents to communicate with users via their personal WeChat accounts."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - QR Code Login for WeChat Bot Account (Priority: P1)

As an admin, I need to initiate and complete a QR code login flow to bind a personal WeChat account as a bot. This is the prerequisite for all subsequent messaging — without a logged-in WeChat session, no messages can be sent or received.

**Why this priority**: Login is the gateway to the entire feature. Without a successful WeChat session, the channel is non-functional. This is the first thing any admin must do.

**Independent Test**: Can be fully tested by triggering the QR code generation API, scanning with a WeChat account, and verifying that a valid session (bot token) is obtained. Delivers the foundational capability to establish a WeChat connection.

**Acceptance Scenarios**:

1. **Given** the admin has configured a WeChat bot account in the system, **When** the admin triggers the QR code login API, **Then** the system returns a QR code image URL and a qrcode identifier within 5 seconds.
2. **Given** a QR code has been generated, **When** the admin polls the QR status endpoint, **Then** the system returns the current status: `wait`, `scaned`, `confirmed`, or `expired`.
3. **Given** a QR code is displayed, **When** the WeChat user scans and confirms the QR code on their phone, **Then** the system receives a valid bot_token, ilink_bot_id, and ilink_user_id, and transitions the bot to "logged in" state.
4. **Given** a QR code has been generated, **When** 5 minutes pass without scanning, **Then** the QR code expires and the system automatically refreshes it (up to 3 times before requiring manual re-trigger).
5. **Given** a QR code has expired after 3 refresh attempts, **When** the admin queries the login status, **Then** the system reports the login as failed and provides instructions to retry.

---

### User Story 2 - Send and Receive Text Messages (Priority: P1)

As a WeChat user, I can send a text message to the bot's personal WeChat account and receive an AI-generated text reply, just like chatting with a friend.

**Why this priority**: This is the core value proposition — enabling conversational AI via personal WeChat. Without message exchange, the channel serves no purpose. Co-equal with login as both are required for minimum viability.

**Independent Test**: Can be fully tested by sending a text message from a personal WeChat account to the logged-in bot, verifying the message is received by as-dispatch, routed to the AI agent, and the reply is delivered back to the user's WeChat.

**Acceptance Scenarios**:

1. **Given** a WeChat bot is logged in and the long-polling loop is active, **When** a user sends a text message to the bot's WeChat account, **Then** the message is received by as-dispatch within the polling interval (≤35 seconds).
2. **Given** a text message is received from a user, **When** the message is processed by the AI agent and a reply is generated, **Then** the reply text is sent back to the user's WeChat via the outbound message API, echoing the correct context_token.
3. **Given** a user sends an image, voice, file, or video message, **When** the system receives it, **Then** the system responds with a friendly placeholder message (e.g., "[收到了图片，暂不支持显示]") and does not crash or error.
4. **Given** the bot is actively exchanging messages, **When** the user sends a message, **Then** the bot shows a typing indicator before sending the actual reply.

---

### User Story 3 - Bot Lifecycle Management (Priority: P2)

As an admin, I can start, stop, and check the status of WeChat bot instances through the admin API, allowing me to manage multiple WeChat accounts simultaneously.

**Why this priority**: Lifecycle management enables operational control. Once login and messaging work, admins need to manage bot instances without restarting the entire service. Less critical than core messaging but essential for production readiness.

**Independent Test**: Can be tested by starting a bot instance, verifying it appears in the status list as "running", stopping it, and confirming it transitions to "stopped" — all without affecting other running bots.

**Acceptance Scenarios**:

1. **Given** a WeChat bot has been logged in, **When** the admin calls the start API, **Then** the bot begins its long-polling loop and is ready to receive messages.
2. **Given** a WeChat bot is running, **When** the admin calls the stop API, **Then** the bot gracefully stops its polling loop and is marked as "stopped".
3. **Given** multiple WeChat bots are configured, **When** the admin queries the status API, **Then** the system returns the status of each bot (logged_in, running, stopped, expired) along with the associated WeChat user information.
4. **Given** a WeChat bot is stopped, **When** the admin starts it again, **Then** the bot resumes from the last known polling cursor (get_updates_buf) without missing messages.

---

### User Story 4 - Automatic Failure Recovery (Priority: P2)

As the system, when the WeChat connection encounters transient errors (network timeouts, API errors), the bot should automatically retry with increasing backoff intervals, and when a session expires, it should pause and retry later — all without manual intervention.

**Why this priority**: Robustness is critical for a long-running messaging channel. Personal WeChat sessions can be fragile; without automatic recovery, the admin would need to constantly babysit the bot. Important for operational viability but lower than core functionality.

**Independent Test**: Can be tested by simulating network failures and verifying the bot retries with backoff, and by simulating session expiry (errcode=-14) and verifying the bot pauses for 1 hour then retries.

**Acceptance Scenarios**:

1. **Given** a long-polling request fails due to a network timeout, **When** the failure is transient, **Then** the bot retries immediately on the first failure, and applies exponential backoff on consecutive failures.
2. **Given** 3 consecutive polling failures occur, **When** the backoff reaches its maximum, **Then** the bot waits up to 30 seconds before the next retry attempt.
3. **Given** the API returns a session expiry error (errcode=-14), **When** the bot detects this condition, **Then** it pauses the polling loop for 1 hour, then attempts to resume with the existing credentials.
4. **Given** the bot was polling and the service restarts, **When** the bot starts up again, **Then** it resumes polling from the persisted get_updates_buf cursor, ensuring no message gap.

---

### User Story 5 - Multiple Simultaneous Accounts (Priority: P3)

As an admin, I can configure and run multiple personal WeChat bot accounts simultaneously, each serving different AI agents or user groups.

**Why this priority**: Multi-account support expands the feature's utility but is not essential for initial viability. A single account is sufficient to prove the channel works. This is an enhancement for scale.

**Independent Test**: Can be tested by logging in two separate WeChat accounts, sending messages to each, and verifying they are independently routed and do not interfere with each other.

**Acceptance Scenarios**:

1. **Given** two WeChat accounts are logged in, **When** a user messages the first account, **Then** only the first account's agent processes and replies; the second account is unaffected.
2. **Given** multiple accounts are running, **When** one account's session expires, **Then** only that account enters recovery mode; the others continue operating normally.
3. **Given** multiple accounts are configured, **When** the admin queries the status API, **Then** each account is listed separately with its individual state and user information.

---

### User Story 6 - Typing Indicator (Priority: P3)

As a WeChat user, when I send a message and the AI agent is generating a response, I see a "typing..." indicator in my WeChat chat, providing feedback that a reply is being prepared.

**Why this priority**: Typing indicators improve user experience but are not functionally required. Messages work fine without them. This is a polish feature that leverages the iLinkAI typing API.

**Independent Test**: Can be tested by sending a message and verifying that the typing status is shown in the WeChat client before the reply arrives, and that it is cancelled after the reply is sent.

**Acceptance Scenarios**:

1. **Given** a message is received from a user, **When** the bot begins processing the reply, **Then** a typing indicator is sent to the user's WeChat before the reply content.
2. **Given** a typing indicator has been sent, **When** the reply is fully generated and sent, **Then** the typing indicator is cancelled.

---

### Edge Cases

- What happens when a QR code is scanned by an account that is already logged in as a bot elsewhere? → The system should handle the response gracefully and report the conflict to the admin.
- What happens when the iLinkAI service is completely unreachable (DNS failure, service down)? → The bot should enter a long backoff cycle and surface the error in its status.
- What happens when a user sends an extremely long text message (>10,000 characters)? → The system should accept and forward it without truncation up to the platform's message limit, and reject gracefully beyond it.
- What happens when the get_updates_buf persistence is corrupted or lost? → The bot should start with an empty cursor and accept that some historical messages may be missed.
- What happens when the context_token cache is evicted for a user? → The bot should handle the missing token gracefully — if no context_token is available, it should still attempt to send the reply (potentially without conversation context linkage).
- What happens when the admin triggers QR login for an account that already has an active session? → The system should warn the admin and either invalidate the old session or reject the new login attempt.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support QR code generation for personal WeChat account login, returning a QR code image URL and a tracking identifier.
- **FR-002**: System MUST support long-polling the QR code status (wait/scaned/confirmed/expired) until the login completes or times out.
- **FR-003**: System MUST auto-refresh expired QR codes up to 3 times before requiring manual re-trigger by the admin.
- **FR-004**: System MUST persist the login session credentials (bot_token, ilink_bot_id) so that the bot can resume after service restarts without re-login.
- **FR-005**: System MUST receive inbound messages via HTTP long-polling (35-second server-side timeout) from the iLinkAI protocol endpoint.
- **FR-006**: System MUST send outbound text replies to WeChat users via the iLinkAI outbound message endpoint, including the required context_token.
- **FR-007**: System MUST handle non-text message types (image, voice, file, video) gracefully by returning a localized placeholder message without crashing.
- **FR-008**: System MUST persist the get_updates_buf opaque cursor between polls and across service restarts for message continuity.
- **FR-009**: System MUST maintain an in-memory cache mapping (accountId, userId) → context_token for reply routing.
- **FR-010**: System MUST support starting, stopping, and querying the status of individual WeChat bot instances via admin API endpoints.
- **FR-011**: System MUST support running multiple WeChat bot accounts simultaneously, with independent lifecycle and message routing.
- **FR-012**: System MUST implement automatic retry with exponential backoff (up to 30 seconds after 3 consecutive failures) for transient polling errors.
- **FR-013**: System MUST detect session expiry (errcode=-14) and pause the polling loop for 1 hour before retrying.
- **FR-014**: System MUST send typing indicators (typing start/cancel) to the user's WeChat when processing replies.
- **FR-015**: System MUST authenticate all requests to the iLinkAI API using the Bearer token and AuthorizationType: ilink_bot_token header scheme.
- **FR-016**: System MUST include the required X-WECHAT-UIN header (random base64 value) in all API requests.
- **FR-017**: System MUST only process private (direct) messages; group chat messages, if received, MUST be silently ignored.
- **FR-018**: System MUST register itself into the existing as-dispatch platform lifecycle without affecting other channel integrations (WeCom, Telegram, Discord, Slack, Lark, QQ).
- **FR-019**: System MUST expose admin API endpoints for triggering QR code login and monitoring login progress.

### Key Entities

- **WeixinAccount**: Represents a personal WeChat account bound as a bot. Key attributes: account identifier, bot_token, ilink_bot_id, ilink_user_id, login status (logged_in / expired / pending), get_updates_buf cursor, last active timestamp.
- **WeixinMessage**: An inbound or outbound message. Key attributes: message items (typed list of content elements), context_token (conversation linkage), message_type (user or bot), message_state (new / generating / finish), sender identifier, timestamp.
- **WeixinSession**: The runtime state of a running WeChat bot instance. Key attributes: associated account, polling loop state (running / stopped / paused), consecutive failure count, backoff state, context_token cache.
- **QRLoginAttempt**: Tracks a QR code login flow. Key attributes: qrcode identifier, qrcode image URL, status (wait / scaned / confirmed / expired), refresh count, creation timestamp, resulting credentials (on success).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An admin can complete the QR code login flow (from triggering to confirmed) within 2 minutes under normal conditions.
- **SC-002**: A WeChat user receives a text reply to their message within the expected AI agent response time plus no more than 5 seconds of channel overhead.
- **SC-003**: The bot can sustain continuous operation for at least 24 hours without manual intervention under stable network conditions.
- **SC-004**: The system recovers from transient network errors automatically within 60 seconds (3 retries with backoff).
- **SC-005**: The system detects and handles session expiry within one polling cycle, pausing and resuming without admin action.
- **SC-006**: Multiple WeChat accounts (at least 3) can operate simultaneously without cross-account message leakage or interference.
- **SC-007**: Non-text messages (image, voice, file, video) are handled gracefully — the user receives a friendly placeholder and the bot does not error.
- **SC-008**: The existing channel integrations (WeCom, Telegram, Discord, Slack, Lark, QQ) continue to function without any degradation after the WeChat channel is added.
- **SC-009**: Message continuity is maintained across service restarts — no messages are lost when the service recovers with a persisted polling cursor.

## Assumptions

- The iLinkAI protocol at https://ilinkai.weixin.qq.com is stable and available for production use.
- Personal WeChat accounts used for bot login are not subject to unexpected bans or restrictions by Tencent beyond normal session expiry.
- The admin has access to a physical device or WeChat client capable of scanning QR codes during the login flow.
- The as-dispatch platform's existing ChannelAdapter interface is sufficient to model the WeChat channel without breaking changes to the interface contract.
- Long-polling with a 35-second server-side timeout is sufficient for near-real-time message delivery (messages arrive within one polling cycle).
- A single as-dispatch instance can handle the polling load for up to 10 simultaneous WeChat accounts without performance concerns.

## Non-Goals (Explicitly Out of Scope for MVP)

- **Group chat support**: Only private (direct) messages are supported. Group message handling is deferred to a future phase.
- **Media message processing**: Images, voice, video, and file messages are acknowledged with a placeholder but not processed, forwarded, or stored.
- **CDN encryption/decryption**: Media content encryption is not addressed in this phase.
- **Markdown rendering**: Outbound messages are plain text only; rich formatting is not supported.
- **Web-based QR display**: The QR code is exposed via API; building a web UI to display it is outside the scope of this spec.
