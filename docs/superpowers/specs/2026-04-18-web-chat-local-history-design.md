# Web Chat Local History Design

Date: 2026-04-18
Status: Draft approved in conversation, written for review

## Summary

The current Web chat history is reconstructed from Codex / Claude native session storage plus a thin layer of app-owned runtime overlay. That direction is no longer sufficient. It creates three persistent failure modes:

- `compact` can change the native transcript shape and make previously displayed content drift or disappear
- refresh can show a different result from the live streaming state because history and running preview come from different sources
- the same active turn can appear twice because the frontend merges `history` and `runningReply` separately

This design replaces that model with a project-local SQLite chat store that becomes the only source of truth for Web chat history. Native CLI session ids remain in the system, but only as a sidecar for `codex` / `claude` resume behavior. Native transcript files are removed from the `/history` read path.

For `assistant` bots, the design keeps the current injected prompt behavior but stores only the user-visible surface in chat history. Host-managed prompt content stays out of the visible conversation and is tracked only through metadata such as prompt hash and assistant home path.

The chosen migration strategy is intentionally hard-cut:

- do not import old native history
- do not continue old native sessions
- start fresh from the first release that enables the new store

## Goals

- Make project-local persistent storage the only truth source for Web chat history.
- Eliminate history dependence on native transcript parsing for normal UI reads.
- Ensure the same active assistant turn is shown consistently during:
  - live SSE streaming
  - refresh
  - restart recovery
- Remove history duplication caused by separate `history` and `runningReply` merge paths.
- Preserve `codex` / `claude` native session ids only for CLI resume, not for UI reconstruction.
- Keep `assistant` bot prompt injection out of visible chat history while preserving enough metadata for debugging and boundary checks.
- Treat working-directory changes as a hard chat-session boundary.
- Require explicit user confirmation before changing working directory when a session exists.
- Reject working-directory changes while a task is still running.

## Non-Goals

- No migration of old Codex / Claude transcript files into the new local store.
- No attempt to make native transcript parsing perfectly reflect every `compact` variant.
- No support for preserving chat continuity across working-directory changes.
- No user-facing conversation archive or multi-session browser in this phase.
- No Telegram-side redesign. This design is for the current Web runtime.
- No storage of full injected prompt bodies for `assistant` bot history.

## User Decisions Captured In This Design

- The new source of truth should be project-local persistent storage.
- `assistant` bot injected prompt text must not be stored in visible chat history.
- On workdir switch, existing session history should be discarded after explicit confirmation.
- If workdir switch is requested while a task is still running, the change should be blocked rather than implicitly killing the task.
- Old native history should not be migrated.
- The rollout should begin as a fresh history epoch instead of trying to stitch old and new storage models together.

## Current Problems

### Native Transcript Is An Unstable UI Dependency

The current history read path rebuilds chat turns from native transcript files through:

- [native_history_locator.py](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/native_history_locator.py)
- [native_history_adapter.py](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/native_history_adapter.py)
- [native_history_builder.py](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/native_history_builder.py)

That path assumes the transcript remains suitable for replay as a user-facing history source. This breaks down when:

- `compact` rewrites the native turn surface
- native files omit early in-flight state
- provider-specific event layouts change
- one real turn is split across multiple transcript fragments

This is acceptable for debugging. It is not stable enough to be the primary UI history source.

### Live State And Restored State Use Different Models

The backend currently exposes a runtime preview snapshot through `running_reply` while `/history` is rebuilt separately. The frontend then merges those two models in:

- [ChatScreen.tsx](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/ChatScreen.tsx#L82)
- [ChatScreen.tsx](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/ChatScreen.tsx#L111)

That makes duplicate or conflicting rendering structurally likely rather than accidental.

### Current Persistence Only Stores Thin Overlay, Not Durable History

The current app-owned persistence explicitly stopped storing full chat history and now keeps only thin chat recovery fields in:

- [session_store.py](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/session_store.py#L127)
- [session_store.py](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/session_store.py#L145)

This means the system has no durable local truth source to fall back to when native transcript replay becomes incomplete or different from what the user already saw.

### Assistant Prompt Injection Must Stay Out Of Visible History

`assistant` bots prepend host-managed prompt material that depends on the current project and assistant home. That content is necessary for execution, but it is not user-authored chat history and should not appear as if the user typed it.

The current architecture strips some visible reread notices, but it still reasons about history through native prompt surfaces. That is too close to leaking internal host-managed content into the displayed conversation.

## Options Considered

### Option A: Keep Native Transcript As The Main History Source

This keeps the current direction and continues to improve the parser and overlay merge logic.

Pros:

- least invasive to current code structure
- retains existing native-history investment

Cons:

- does not remove the root dependency on provider-specific transcript behavior
- `compact` remains a permanent correctness risk
- refresh and streaming still need dual-path reconciliation
- `assistant` prompt-surface handling remains fragile

Conclusion:

- rejected

### Option B: Project-Local JSON / JSONL History Files

This makes the app own history directly, but stores it as files instead of a database.

Pros:

- easy to inspect manually
- simpler than a database for very small histories

Cons:

- awkward for high-frequency streaming updates
- poor crash recovery semantics
- expensive whole-file rewrites or complex append/compaction logic
- migration and schema evolution are harder than they first appear

Conclusion:

- rejected

### Option C: Project-Local SQLite History Store With Native Session Sidecar

This gives the Web app a durable local history database and limits native session data to CLI resume behavior only.

Pros:

- one truth source for history during streaming, refresh, and restart
- resilient against native transcript `compact` behavior
- precise turn lifecycle and trace event ownership
- clean separation between visible history and assistant prompt metadata
- suitable for incremental writes and crash recovery

Cons:

- broad backend and frontend refactor
- one-time migration cutoff is intentionally breaking for existing sessions

Conclusion:

- chosen

## Chosen Design

### Storage Ownership Model

The new ownership split is:

- `local SQLite store`: authoritative source for Web chat history, turn state, trace events, and recoverable in-flight messages
- `native session id`: sidecar state for `codex` / `claude` resume behavior only
- `native transcript files`: debug and validation inputs only, not part of normal `/history` rendering

This means the Web UI no longer needs to ask, "What does the native transcript currently look like?" The UI only asks, "What does the local chat store say the current conversation contains?"

### Conversation Boundary Model

The conversation identity is scoped by:

- `bot_id`
- `user_id`
- `working_dir`
- `session_epoch`

`session_epoch` increments whenever the system intentionally starts a fresh chat context, such as:

- reset session
- confirmed working-directory change
- first-run migration into the new storage model

Only one active conversation exists for a given `(bot_id, user_id)` at a time.

### Turn Lifecycle Model

Each user request creates a stable local `turn_id` before the CLI process starts.

That turn owns:

- one user message row
- one assistant message row
- zero or more trace events
- turn lifecycle state
- native sidecar metadata for that turn

The assistant message row is updated in place through the lifecycle:

- `streaming`
- `completed`
- `cancelled`
- `failed`

The same assistant row is what the user sees:

- during SSE streaming
- after refresh
- after restart recovery

This removes the current need for a separate "live preview bubble" model.

### Assistant Bot Visibility Rules

For `assistant` bot turns, the local chat store records only the user-visible conversation surface:

- user text as entered by the user
- assistant visible output
- visible tool / trace events

It does not store:

- full injected prompt body
- full host-managed prompt file text
- hidden prompt sections added before CLI execution

Instead, the turn and conversation metadata record:

- `managed_prompt_hash`
- `assistant_home`
- `working_dir`
- `prompt_surface_version`

That preserves debugging and boundary checks without polluting history or leaking internal prompt material into visible chat.

## Data Model

### Store Location

The local database file lives inside the active project root:

- `<repo_root>/.tcb/state/chat.sqlite`

This path is host-managed application state and must be ignored by git.

This design intentionally does not place the Web chat database under `.assistant`, because `.assistant` belongs to assistant runtime state rather than general Web chat state.

### Tables

The store uses four core tables.

#### `conversations`

One active conversation per `(bot_id, user_id)`.

Required fields:

- `id`
- `bot_id`
- `bot_alias`
- `user_id`
- `bot_mode`
- `cli_type`
- `working_dir`
- `session_epoch`
- `status`
- `native_provider`
- `native_session_id`
- `assistant_home`
- `managed_prompt_hash`
- `prompt_surface_version`
- `created_at`
- `updated_at`

#### `turns`

One row per user request / assistant response pair.

Required fields:

- `id`
- `conversation_id`
- `seq`
- `user_message_id`
- `assistant_message_id`
- `assistant_state`
- `completion_state`
- `native_provider`
- `native_session_id`
- `managed_prompt_hash`
- `started_at`
- `updated_at`
- `completed_at`
- `error_code`
- `error_message`

#### `messages`

Visible chat rows.

Required fields:

- `id`
- `conversation_id`
- `turn_id`
- `role`
- `content`
- `content_format`
- `state`
- `created_at`
- `updated_at`

Rules:

- `role` is one of `user`, `assistant`, `system`
- assistant streaming updates mutate the same row instead of creating a second row
- the displayed history list is generated from this table, not from native transcript replay

#### `trace_events`

Structured per-turn process details.

Required fields:

- `id`
- `turn_id`
- `ordinal`
- `kind`
- `raw_type`
- `title`
- `tool_name`
- `call_id`
- `summary`
- `payload_json`
- `created_at`

Rules:

- append-only within a turn
- ordering is defined by `ordinal`
- provider-native fields must be preserved enough to support future debugging and trace rendering

### Session Snapshot Compatibility

The existing `.session_store.json` should stop owning chat-history truth.

Short-term compatibility is acceptable for fields such as:

- `browse_dir`
- lightweight session metadata needed outside chat history

But the following fields must no longer be authoritative once local chat storage is enabled:

- `web_turn_overlays`
- `running_user_text`
- `running_preview_text`
- `running_started_at`
- `running_updated_at`
- previous persisted native session ids

The new store becomes authoritative for those concerns.

## Backend Design

### New Core Boundary

Introduce a dedicated local history service with three clear responsibilities:

- store and load active conversations and turns
- write streaming updates incrementally
- expose history and trace queries in Web-ready shape

Recommended boundary names:

- `ChatStore`: low-level SQLite access and transactions
- `ChatHistoryService`: conversation and turn lifecycle operations
- `NativeSessionBridge`: native session id read/write for CLI resume only

The existing native-history modules remain available only for explicit debugging utilities or future repair tooling. They are removed from the main `/history` path.

### History Read Path

`GET /history` and `GET /history/{message_id}/trace` read only from the local chat store.

They do not:

- locate native transcript files
- parse transcript JSONL
- merge transcript turns with app overlay

This change is the center of the redesign.

### Stream Write Path

Before starting a CLI subprocess, the backend creates:

- active conversation if missing
- next `turn`
- user `message`
- empty assistant `message` in `streaming` state

As SSE events arrive:

- text deltas update the same assistant message row
- preview/status text updates the same assistant message row if it is newer than accumulated delta text
- trace events append `trace_events`
- state timestamps update the current turn

At completion:

- the same assistant message row is finalized
- the turn state becomes `completed`, `cancelled`, or `failed`
- native session sidecar is updated if resume should continue

### Crash Recovery

Because streaming writes occur incrementally to SQLite, restart recovery becomes a database concern rather than a transcript replay concern.

On process restart:

- if a turn is still marked `streaming`, it is shown as the latest assistant message
- the backend may optionally normalize stale `streaming` turns to `cancelled` or `failed_recovered` during startup or first read if no process is actually alive

The exact normalization label may vary, but the key requirement is that the user sees the same message row rather than a separate synthetic recovery bubble.

### Native Session Handling

Native session ids still matter for CLI resume behavior, but they are no longer allowed to drive chat history rendering.

Rules:

- current native session id is attached to the active conversation and updated after each completed turn as needed
- reset session clears native session ids
- confirmed workdir change clears native session ids
- first-run migration into the new store clears any previously persisted native session ids so that local history and hidden CLI context cannot drift apart

This last rule is mandatory. Since old native history is not being migrated, hidden continuation into an old native session would create invisible context carryover and break user expectations.

## Frontend Design

### Single Rendering Model

The chat screen must stop constructing history from:

- persisted history
- separate `runningReply`
- synthetic restored reply bubbles

Instead, the screen always renders the message list returned by `/history`, including the currently streaming assistant row if one exists.

### Overview Usage

`getBotOverview()` can continue exposing `is_processing` for top-bar status and button enablement.

It may also continue exposing `running_reply` temporarily for backward compatibility with older screens, but the main chat message list must not merge it into the rendered conversation once the new store is active.

### Trace Rendering

Trace rendering behavior remains the same at the UX level:

- assistant summary first
- trace panel collapsed by default
- tool calls and results available on demand

The difference is that trace data now comes directly from `trace_events` rather than lazy native transcript reconstruction.

## Assistant Bot Design

### Prompt Metadata

For assistant turns, store:

- `assistant_home`
- `managed_prompt_hash`
- `prompt_surface_version`

Do not store:

- generated managed prompt file body
- injected prompt preamble
- hidden reread scaffold as if it were user text

### Prompt Drift Handling

If managed prompt material changes between turns, the system may record a visible system notice or assistant-readable surface note, but it must not rewrite historical user messages or inject hidden prompt text into history.

The conversation metadata is sufficient to explain why a later assistant turn used a different prompt surface.

### Workdir Coupling

For assistant bots, `working_dir` is part of the conversation identity rather than a casual setting. A workdir change is therefore equivalent to discarding the current assistant context and starting a new conversation epoch.

## Reset And Workdir Change Rules

### Reset Session

Reset performs a hard local reset of the active conversation context.

Required effects:

- delete local conversation rows for the active `(bot_id, user_id)` conversation
- clear native session ids
- clear in-memory streaming state
- start the next message on a fresh conversation epoch

### Workdir Change While Idle

If the user requests a workdir change and the current session has any active conversation state, the backend must require explicit confirmation before proceeding.

The frontend confirmation copy should clearly state that changing the working directory will discard the current conversation.

Recommended backend pattern:

- first request without confirmation flag
- backend returns `409 workdir_change_requires_reset`
- payload includes enough summary fields for the UI to explain the consequence
- frontend shows confirmation dialog
- confirmed retry sends an explicit force/reset flag

### Workdir Change While Processing

If a task is still running, workdir change is rejected.

This is a hard rule, not a best effort.

The system must not:

- implicitly kill the task
- switch directory and hope the stream settles
- create a mixed state where assistant prompt context and workdir diverge

The user must terminate the task first, then retry the workdir change.

## Migration Strategy

### Cutover Behavior

The selected migration is a fresh start, not a replay migration.

On first activation of the new local history store:

- create the SQLite database and schema
- clear persisted chat overlay fields from old session snapshots
- clear persisted native session ids from old session snapshots
- begin with no imported history rows

This guarantees that:

- visible Web history starts fresh
- hidden native CLI context also starts fresh
- the user does not unknowingly continue inside an invisible old conversation

### Legacy Module Status

The following native-history modules remain temporarily in the repository:

- [native_history_locator.py](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/native_history_locator.py)
- [native_history_adapter.py](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/native_history_adapter.py)
- [native_history_builder.py](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/web/native_history_builder.py)

But after cutover they are no longer part of the primary chat read path. They become debug-only or cleanup candidates.

## Error Handling

### Store Write Failure

If the local history store cannot write a turn update, the request should fail fast rather than allow the UI to continue on an unpersisted history branch.

The system should prefer:

- one visible failed turn
- one explicit error message

over:

- continuing to stream content that will disappear on refresh

### Native Resume Failure

If a native session id becomes invalid, the system may clear the native sidecar and continue future turns with a fresh native session.

This must not rewrite or delete local history rows that have already been shown to the user.

### Stale Streaming Turn

If the app restarts and finds a turn stuck in `streaming` with no live process behind it, the turn should be normalized on read or startup into a non-streaming terminal state without creating a second synthetic assistant message.

## Testing

### Backend Tests

Add or update tests to verify:

- `/history` reads only from local store once the feature is enabled
- SSE `delta`, `status`, `trace`, and `done` all update the same assistant message row
- refresh during an active turn shows the same assistant row instead of a duplicate preview row
- restart recovery preserves unfinished assistant output from the local store
- first-run migration clears old native session ids and overlay fields
- assistant bot history stores user-visible text only and keeps injected prompt material out of visible rows
- workdir change while idle returns a confirmation-required error when conversation state exists
- confirmed workdir change clears local conversation rows and native session ids
- workdir change while processing is rejected

### Frontend Tests

Add or update tests to verify:

- chat screen does not merge `runningReply` into history when local-store mode is active
- streaming assistant output remains one message before and after refresh
- finalization updates the existing assistant message instead of replacing it with a second message
- workdir change confirmation dialog appears when session state exists
- workdir change is blocked while processing

## Acceptance Criteria

- The Web chat list is identical before and after refresh for the same active turn.
- `compact` inside native transcript files no longer affects normal Web history rendering.
- A live assistant reply is represented by one stable local assistant message row, not a native-history row plus a synthetic preview row.
- `assistant` bot history contains only user-visible surface content.
- Switching working directory requires explicit confirmation if the session has history and is rejected if a task is running.
- After rollout, both visible history and hidden CLI context start fresh rather than silently continuing from pre-cutover native sessions.
