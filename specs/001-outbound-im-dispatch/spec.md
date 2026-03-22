# Feature Specification: Outbound IM Dispatch

**Feature Branch**: `feat/outbound-im-dispatch`  
**Created**: 2026-03-22  
**Status**: Draft  
**Input**: User description: "Enable AgentStudio to proactively dispatch messages to IM channels and route user replies back into the original Agent conversation"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Web-to-IM Message Forwarding (Priority: P1)

A user is chatting with an Agent on the AgentStudio Web UI. The Agent produces a response that the user wants to share with colleagues in a WeChat Work group. The user clicks a "Forward to WeChat Work" button on the AI-generated message bubble. The message is sent to the designated WeChat Work group with a unique routing identifier `[#short_id project_name]` embedded in the message header. The user sees a confirmation that the message was dispatched.

**Why this priority**: This is the foundational capability that enables all other scenarios. Without the ability to dispatch a message from the web UI to an IM channel with proper routing context, no downstream reply-routing can occur. It delivers immediate value by bridging the gap between the web-based Agent workspace and the team's IM channel.

**Independent Test**: Can be fully tested by sending a message from AgentStudio Web UI to a WeChat Work group and verifying the message arrives with the correct routing header. Delivers value even without reply routing — users can already share Agent output with their team.

**Acceptance Scenarios**:

1. **Given** a user is viewing an AI-generated message in AgentStudio Web UI, **When** the user clicks "Forward to WeChat Work" on the message, **Then** the message is sent to the configured WeChat Work group with the routing header `[#<short_id> <project_name>]` prepended to the content
2. **Given** a message is successfully dispatched, **When** the dispatch completes, **Then** the user sees a success indicator on the message bubble in the Web UI
3. **Given** a message dispatch fails (e.g., bot key invalid, network error), **When** the dispatch encounters an error, **Then** the user sees an error notification explaining the failure and the message bubble returns to its original state
4. **Given** a message has already been forwarded, **When** the user views the message bubble, **Then** the UI indicates that this message was previously dispatched (preventing duplicate sends or informing the user)

---

### User Story 2 - IM Reply Routing Back to Agent Conversation (Priority: P1)

After an AI message has been forwarded to WeChat Work (via Story 1 or Story 3), a user quotes/replies to that message in the WeChat Work group. The reply content is automatically routed back to the original Agent conversation in AgentStudio as a new user message. The Agent then continues processing the conversation with the reply, creating a seamless cross-platform dialogue.

**Why this priority**: Reply routing is co-equal with outbound dispatch — together they form the complete bidirectional loop. Without reply routing, the outbound dispatch is a one-way broadcast with no way to close the feedback loop. This is what transforms the feature from "message forwarding" into "cross-platform conversation continuity."

**Independent Test**: Can be tested by sending a message to WeChat Work (via the dispatch mechanism), then replying to that message in WeChat Work. Verify that the reply appears in the original AgentStudio conversation and triggers the Agent to respond.

**Acceptance Scenarios**:

1. **Given** a message with routing header `[#abc123 MyProject]` exists in a WeChat Work group, **When** a user quotes that message and types a reply, **Then** the reply text (excluding the quoted portion) is injected into the AgentStudio conversation identified by the stored session context
2. **Given** a reply is injected into the AgentStudio conversation, **When** the Agent receives the injected message, **Then** the Agent processes it as a normal user message and generates a response
3. **Given** the routing identifier in a quoted message cannot be found in the outbound context store (e.g., expired or invalid), **When** the system receives the reply, **Then** the system falls back to the existing HITL-MCP routing behavior without error
4. **Given** the original AgentStudio session has been closed or is no longer active, **When** a reply arrives for that session, **Then** the system handles the situation gracefully (e.g., logs a warning, notifies the user that the session is unavailable)

---

### User Story 3 - Scheduled Task IM Notification with Reply Support (Priority: P2)

A scheduled task or hook in AgentStudio produces an AI response (e.g., a daily report, a monitoring alert, a periodic summary). The orchestration layer determines that this response should be proactively sent to the user's IM channel. The message is dispatched to WeChat Work using the same mechanism as web-to-IM forwarding — same routing header, same dispatch service. When the user replies to the notification in WeChat Work, the reply flows back into the original Agent conversation as a user message.

**Why this priority**: Builds on the dispatch and reply-routing foundation from P1 stories. Scheduled/hook-based dispatch adds automation value but depends entirely on the core dispatch and routing mechanisms already being functional. It extends the feature from user-initiated forwarding to system-initiated proactive messaging.

**Independent Test**: Can be tested by configuring a scheduled task or hook that triggers an IM dispatch, verifying the message arrives in WeChat Work with proper routing headers, then replying and verifying the reply appears in the originating Agent conversation.

**Acceptance Scenarios**:

1. **Given** a scheduled task or hook produces an AI response flagged for IM dispatch, **When** the orchestration layer processes the response, **Then** the response is sent to the configured WeChat Work channel using the same dispatch mechanism as web-to-IM forwarding
2. **Given** a scheduled notification has been sent to WeChat Work, **When** a user replies to the notification, **Then** the reply is routed back to the originating Agent conversation, and the Agent processes it as a user message
3. **Given** a scheduled task targets a user who has no configured IM channel or bot, **When** the dispatch is attempted, **Then** the system logs the failure and does not block the scheduled task from completing

---

### Edge Cases

- What happens when the same message is forwarded multiple times by the same user or different users? Each forward generates a new unique `short_id` and outbound context — replies are routed to the conversation from which the most recent forward was triggered.
- What happens when a user replies to a very old forwarded message whose outbound context has expired? The system falls back to existing routing behavior (HITL-MCP) and does not inject the reply into a stale session.
- What happens when the quoted text in the WeChat Work reply is truncated or malformed, and the routing header cannot be parsed? The system treats the message as a normal inbound message and routes it through the existing callback flow (no injection, no error to the user).
- How does the system handle concurrent replies to the same forwarded message from multiple users? Each reply is independently injected into the original session as separate user messages. The Agent processes them sequentially.
- What happens if the AgentStudio backend is temporarily unavailable when a reply needs to be injected? The system retries injection with a reasonable backoff or logs the failure for manual recovery.
- What happens if the WeChat Work bot webhook returns an error during dispatch? The error is surfaced to the caller (Web UI shows error, scheduled task logs failure) and no outbound context is persisted for the failed message.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow users to forward any AI-generated message from the AgentStudio Web UI to a configured WeChat Work group with a single user action (button click)
- **FR-002**: System MUST embed a unique routing identifier in the format `[#<short_id> <project_name>]` at the beginning of every outbound IM message
- **FR-003**: System MUST persist the mapping between each outbound `short_id` and the originating conversation context (`session_id`, `agent_id`, `bot_key`, `chat_id`) for the purpose of reply routing
- **FR-004**: System MUST parse quoted text in inbound WeChat Work callback messages to extract the `[#<short_id>]` routing identifier
- **FR-005**: When a valid `short_id` is found in an inbound reply, the system MUST inject the reply text into the corresponding AgentStudio conversation as a new user message
- **FR-006**: System MUST automatically expire outbound message contexts after a reasonable retention period (default: 7 days) to prevent unbounded storage growth
- **FR-007**: System MUST support the same dispatch mechanism for both user-initiated forwarding (Web UI) and system-initiated forwarding (scheduled tasks / hooks)
- **FR-008**: System MUST provide visual feedback in the Web UI when a message has been forwarded (success state, error state, already-forwarded state)
- **FR-009**: When a `short_id` cannot be matched (expired, invalid, or unparseable), the system MUST fall back to existing message routing behavior without generating user-facing errors
- **FR-010**: System MUST NOT modify or interfere with the existing HITL-MCP message flow — outbound IM dispatch operates as an independent, additive capability

### Key Entities

- **OutboundMessageContext**: Represents the relationship between a dispatched IM message and its originating Agent conversation. Key attributes: unique short identifier, originating session, originating agent, target bot configuration, target chat/group, original message content (or summary), creation timestamp, expiration timestamp, dispatch status
- **DispatchRequest**: Represents a request to send a message to an IM channel. Key attributes: message content, target channel configuration, originating session reference, dispatch trigger type (user-initiated vs. system-initiated)
- **InboundReply**: Represents a reply received from an IM channel that has been matched to an outbound context. Key attributes: reply text, matched short identifier, source user identity, timestamp, injection status

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can forward an AI message from AgentStudio Web UI to WeChat Work in under 3 seconds (from button click to delivery confirmation)
- **SC-002**: 95% of IM replies to forwarded messages are correctly matched and injected into the originating Agent conversation within 5 seconds of receipt
- **SC-003**: The Agent successfully continues the conversation after receiving an injected IM reply in 100% of cases where the session is still active
- **SC-004**: Scheduled task notifications are dispatched to IM within 10 seconds of the task producing output
- **SC-005**: Zero disruption to existing HITL-MCP message flows — all existing inbound/outbound message routing continues to function identically after this feature is deployed
- **SC-006**: Outbound message contexts are automatically cleaned up after expiration, maintaining storage usage within predictable bounds (no manual intervention required)
- **SC-007**: Users receive clear, actionable feedback in the Web UI for both successful dispatches and failures — no silent failures

## Assumptions

- WeChat Work group bot webhook API does NOT return a `msgid` for sent messages; therefore all reply matching is application-level, based on parsing the routing header from quoted text in callbacks
- The existing `POST /api/agui/sessions/:sessionId/inject` endpoint in AgentStudio is available and functioning for injecting user messages into active sessions
- Each AgentStudio project has a pre-configured WeChat Work bot key and chat ID for outbound messaging (configuration management is outside the scope of this feature)
- The WeChat Work callback mechanism delivers quoted text content reliably when a user replies to a message in a group
- Default outbound context expiration of 7 days is sufficient for most use cases; this can be adjusted via configuration without code changes

## Out of Scope

- QQ Bot proactive messaging (API disabled since April 2025)
- WeChat personal account proactive messaging (requires `context_token`)
- Modifications to HITL-MCP behavior
- Real-time streaming of IM messages to the Web UI
- Multi-platform IM support beyond WeChat Work (future extensibility is assumed via existing `ChannelAdapter` pattern, but only WeChat Work is implemented in this iteration)
- Bot key and chat ID configuration management (assumed to be pre-configured)
