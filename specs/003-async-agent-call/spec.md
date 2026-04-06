# Feature Specification: Async Agent Call via JSON-RPC Message Stream

**Feature Branch**: `003-async-agent-call`  
**Created**: 2026-03-26  
**Status**: Draft  
**Input**: User description: "Async JSON-RPC Message Stream for WeChat Work Bot Agent Calls"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Instant Message Acknowledgment (Priority: P1)

A WeChat Work user sends a message to a bot powered by an AgentStudio agent. The bot acknowledges receipt within seconds, even though the actual AI processing may take several minutes. The user sees a "正在处理中..." (processing) indicator immediately, so they know their message was received and is being worked on.

**Why this priority**: This is the foundational requirement. Without quick acknowledgment, WeChat Work may retry delivery or users get no feedback at all. Solving this eliminates the root cause of current 504 timeout errors.

**Independent Test**: Can be tested by sending a message to a bot and verifying a "processing" acknowledgment arrives within 3 seconds, without needing the agent to complete its work.

**Acceptance Scenarios**:

1. **Given** a WeChat Work bot is configured and a user sends a message, **When** the message arrives at as-dispatch, **Then** as-dispatch responds to WeChat Work's callback within 3 seconds with a confirmation acknowledgment.
2. **Given** a user sends a message requiring complex agent processing, **When** the agent task is submitted asynchronously, **Then** the user receives a "processing" status reply in WeChat Work within 5 seconds of sending.
3. **Given** as-dispatch receives a WeChat Work message, **When** the underlying agent service is temporarily unavailable, **Then** the user receives a friendly error notification rather than a silent timeout.

---

### User Story 2 - Agent Response Delivered to User (Priority: P1)

After an agent completes processing (whether in 30 seconds or 25 minutes), the final response is automatically sent back to the WeChat Work conversation. The user does not need to poll or refresh — the result appears in their chat window when ready.

**Why this priority**: Equal priority with P1 acknowledgment — the system is only useful if the final answer reaches the user. Both halves of the async loop must work.

**Independent Test**: Can be tested by verifying that after an agent task completes (even a simulated one), the result text is posted back to the correct WeChat Work conversation.

**Acceptance Scenarios**:

1. **Given** an agent has finished processing a user's task, **When** the result is ready, **Then** the complete response is delivered to the originating WeChat Work conversation automatically.
2. **Given** an agent streams partial responses during processing, **When** each chunk is received, **Then** the final composed response is delivered once streaming is complete (or intermediate updates are shown, if configured).
3. **Given** an agent task takes longer than 30 minutes, **When** the timeout is reached, **Then** the user receives a clear timeout notification rather than silence.
4. **Given** a long-running task completes successfully, **When** the response is being delivered back to WeChat Work, **Then** responses exceeding WeChat's message length limits are split into multiple messages automatically.

---

### User Story 3 - Task Lifecycle Visibility (Priority: P2)

Bot administrators and operators can see the current status of in-flight agent tasks — which tasks are pending, processing, or completed — through a management interface. This enables debugging, monitoring, and detecting stalled tasks.

**Why this priority**: Operational visibility prevents silent failures from going unnoticed for extended periods. Important for reliability but not required for end-user functionality.

**Independent Test**: Can be tested by submitting a long-running task and verifying its status transitions (submitted → processing → completed) are observable through the management view.

**Acceptance Scenarios**:

1. **Given** a task has been submitted to an agent, **When** an operator queries task status, **Then** the current state (pending / in-progress / completed / failed / timed-out) is returned.
2. **Given** multiple concurrent bot conversations are active, **When** an operator views the task list, **Then** each task shows its originating conversation, submission time, and current status.
3. **Given** a task has failed or timed out, **When** an operator reviews the task, **Then** the failure reason is available for debugging.

---

### User Story 4 - Backward Compatible Short-Task Handling (Priority: P3)

For bots configured with short timeout expectations (tasks expected to complete in under 30 seconds), the system continues to behave synchronously — no "processing" message is sent, and the response appears directly as a reply. This ensures no disruption to bots that were working fine before.

**Why this priority**: Preserves existing behavior for simple use cases and allows gradual migration to async pattern.

**Independent Test**: Can be tested by configuring a bot with a "sync mode" flag and verifying that quick agent responses are delivered without an intermediate "processing" acknowledgment.

**Acceptance Scenarios**:

1. **Given** a bot is configured in synchronous mode, **When** an agent completes in under 30 seconds, **Then** the response is sent directly without an intermediate "processing" notification.
2. **Given** a bot is configured in synchronous mode, **When** the agent exceeds the synchronous timeout, **Then** the system automatically falls back to async mode and sends a "processing" notification.

---

### Edge Cases

- What happens when WeChat Work's delivery endpoint is temporarily unreachable when the agent result is ready?
- How does the system handle an agent task that never completes and never times out (runaway task)?
- What happens when a user sends multiple messages in quick succession while the first task is still processing? **[DECIDED: Reject-with-notification strategy]** — If a task from the same conversation is already PENDING or PROCESSING, the second message is rejected (not queued). The user receives a friendly notification such as "正在处理您的上一条消息，请稍后再试" (Your previous message is being processed, please try again later). This prevents unbounded task queue growth and simplifies the state machine. Future iterations may add optional queuing mode per bot config.
- How are responses handled when the WeChat Work conversation context has expired (e.g., the group chat was dissolved)?
- What happens if as-dispatch restarts while tasks are in-flight?
- How does the system handle agents that return empty or malformed responses?
- What if the agent result is too large for WeChat Work's message limits (after splitting attempts)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST acknowledge every incoming WeChat Work message to the WeChat platform within 3 seconds of receipt, regardless of how long agent processing takes.
- **FR-002**: System MUST submit agent tasks asynchronously, receiving a task identifier back without waiting for task completion.
- **FR-003**: System MUST notify the originating WeChat Work conversation when an agent task completes, using the task identifier to correlate results back to the correct conversation.
- **FR-004**: System MUST support receiving streaming agent responses incrementally and deliver the final composed result to WeChat Work upon stream completion.
- **FR-005**: System MUST enforce a maximum task duration (default: 30 minutes), after which the task is considered timed-out and a timeout notification is sent to the user.
- **FR-006**: System MUST persist task state (conversation context, task identifier, submission time, status) so that in-flight tasks survive as-dispatch service restarts.
- **FR-007**: System MUST support both tunnel-proxied agent calls and direct agent calls, with async behavior applied consistently to both.
- **FR-008**: System MUST send an intermediate "processing" status message to the WeChat Work user when async task submission succeeds, to confirm the request was received.
- **FR-009**: System MUST automatically split agent responses that exceed WeChat Work's per-message character limit into multiple sequential messages.
- **FR-010**: System MUST implement retry logic for delivering results back to WeChat Work when the initial delivery attempt fails (transient network errors).
- **FR-011**: System MUST provide backward compatibility: bots configured for synchronous operation should continue to work without modification, with automatic async fallback if the synchronous timeout is exceeded.
- **FR-012**: System MUST expose task status information (pending / in-progress / completed / failed / timed-out) queryable by conversation or task identifier.
- **FR-013**: System MUST handle the case where a user sends multiple messages before the first task completes, queueing or handling concurrent tasks per conversation.

### Key Entities *(include if feature involves data)*

- **AsyncTask**: Represents one submitted agent job; attributes include task identifier, originating conversation context (WeChat group/user ID), submission timestamp, current status, agent target URL, raw user message, and result payload when complete.
- **ConversationContext**: Captures the WeChat Work conversation details needed to reply — includes bot token, chat ID, user ID, and any reply-chain metadata required to post a message back.
- **BotConfiguration**: The per-bot settings record (already exists) extended with: async mode flag, processing acknowledgment message template, synchronous timeout threshold, and maximum task duration.
- **StreamBuffer**: Transient accumulator for incremental streaming agent output, associated with a task, cleared once the final response is delivered.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: WeChat Work callback acknowledgments are delivered within 3 seconds for 99% of incoming messages, eliminating 504 Gateway Timeout errors from WeChat's perspective.
- **SC-002**: Agent tasks running up to 30 minutes complete successfully and deliver results to users, with zero silent failures (all failures result in an explicit user notification).
- **SC-003**: Users receive a "processing" confirmation within 5 seconds of sending a message to any async-enabled bot.
- **SC-004**: The system correctly delivers agent responses to 99.5% of completed tasks under normal network conditions, with a configurable number of retry attempts for transient failures (default: 3, minimum: 1).
- **SC-005**: as-dispatch service restarts result in zero lost in-flight task results — tasks that completed during the restart window are delivered upon service recovery.
- **SC-006**: Existing bots that were working in synchronous mode continue to function correctly without any configuration changes, with no regression in response behavior for tasks completing under 30 seconds.
- **SC-007**: Operators can determine the status of any in-flight or recently completed task within 10 seconds of querying the system.

## Assumptions

- WeChat Work's callback URL receives an HTTP 200 acknowledgment quickly; the actual reply to the user is sent as a separate outbound API call (not in the HTTP response body).
- The A2A protocol already supports asynchronous task submission with a task identifier return value; this feature uses that existing mechanism.
- Agent streaming output is compatible with Server-Sent Events (SSE) or an equivalent incremental delivery mechanism already supported by AgentStudio.
- The "processing" acknowledgment message text is configurable per bot (with a sensible default like "正在为您处理，请稍候...").
- WeChat Work's per-message length limit applies and is known; the system uses this limit for splitting logic.
- Task state persistence uses the same database infrastructure already in place for as-dispatch (no new database technology required).
