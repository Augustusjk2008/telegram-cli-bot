# Desktop Workbench Design

Date: 2026-04-17
Status: Draft approved in conversation, written for review

## Summary

The current web frontend is optimized around a mobile-first single-tab shell. That shell works for phones, but it blocks the desktop workflow the product is already close to supporting. Desktop users want to see file navigation, file editing, terminal output, and AI chat at the same time in an IDE-like workspace.

This design adds a desktop workbench without rewriting the frontend from scratch. The implementation will preserve the current mobile shell, introduce a desktop shell, and progressively extract pane-level components from existing screen-level components. The first desktop version will use a fixed four-pane layout with collapsible regions, a three-state layout mode switch, and multi-tab file editing without split editors.

## Goals

- Keep the current mobile experience available and stable.
- Add a desktop workbench that resembles an IDE workflow.
- Show four functional areas at once on desktop:
  - left file tree
  - center top editor
  - center bottom terminal
  - right AI chat
- Support collapsing all four areas.
- Support layout mode selection with `auto`, `mobile`, and `desktop`.
- Support multiple open editor tabs on desktop, with one active tab at a time.
- Reuse existing business logic where practical instead of building a second frontend.

## Non-Goals

- No draggable or freely dockable panes in the first version.
- No split editor view in the first version.
- No persistence of open editor tabs across reloads in the first version.
- No full redesign of the current visual language.
- No backend API redesign unless existing APIs are insufficient for the pane split.

## User Experience

### Mobile Mode

Mobile mode keeps the existing single-page tab workflow. Bottom navigation remains the primary navigation pattern. File preview and file editing continue to behave in a mobile-first way.

### Desktop Mode

Desktop mode renders one workbench instead of one active tab page.

- Left pane: file tree and file actions.
- Center top pane: editor with multiple file tabs.
- Center bottom pane: terminal.
- Right pane: AI chat.

All four panes are collapsible.

- Left pane collapses toward the left edge.
- Right pane collapses toward the right edge.
- Center top and center bottom collapse vertically.

The first version uses a fixed arrangement rather than user-driven drag resizing. This keeps state complexity low while still delivering the core desktop workflow.

### Layout Mode Switch

The frontend exposes a three-state layout mode switch:

- `auto`
- `mobile`
- `desktop`

Recommended default behavior:

- Persist the selected mode in local storage.
- In `auto`, switch to desktop workbench at viewport widths `>= 1280px`.
- In `auto`, widths below that threshold stay in mobile mode.
- `mobile` forces the existing mobile shell even on desktop browsers.
- `desktop` forces the desktop workbench even when the browser would otherwise stay in mobile mode.

This provides the same practical benefit users get from browser-level "desktop site" toggles, but with application-owned behavior instead of browser heuristics.

## Architecture

### Top-Level Shell

The current `App` component decides between one active screen at a time. That is the main structural blocker for desktop. The desktop design should replace that single-screen outlet with a shell split:

- `MobileShell`
- `DesktopWorkbench`

`App` remains the root coordinator and is responsible for:

- authentication gate
- current bot selection
- theme and user preference bootstrapping
- layout mode state
- effective layout mode resolution

### Desktop Workbench

`DesktopWorkbench` becomes the desktop shell and owns:

- fixed pane layout
- pane collapse state
- top-level desktop toolbar and controls
- shared workbench state for files and editor tabs

### Pane-Level Components

The desktop shell should not embed the existing screen components as-is for the long term. Instead it should extract pane-level components that can be embedded cleanly.

Recommended pane split:

- `WorkbenchHeader`
- `FileTreePane`
- `EditorPane`
- `TerminalPane`
- `ChatPane`

The current screens can still be used as implementation references or intermediate wrappers during migration, but the target design is pane-first rather than screen-first.

## Component Boundaries

### App

Responsibilities:

- determine `viewMode`
- determine `effectiveLayoutMode`
- keep current bot selection
- route to `MobileShell` or `DesktopWorkbench`

### MobileShell

Responsibilities:

- preserve current bottom-nav tab workflow
- continue to mount one active functional area at a time

### DesktopWorkbench

Responsibilities:

- render fixed four-pane layout
- manage pane collapse behavior
- manage shared editor tab state
- coordinate file tree to editor interactions

### FileTreePane

Responsibilities:

- file list and directory navigation
- file actions such as create, rename, delete, download
- opening files into editor tabs

It should no longer own the canonical editor state in desktop mode.

### EditorPane

Responsibilities:

- tab strip
- active editor content
- save and close actions
- dirty tab indicators
- conflict and save errors

### TerminalPane

Responsibilities:

- embed the existing terminal session experience
- keep terminal-specific state local
- provide reconnect or rebuild actions

### ChatPane

Responsibilities:

- embed the existing AI chat experience
- preserve chat draft and conversation state while other panes change

## State Model

The design uses two layers of state.

### Workbench-Level Shared State

This state affects multiple panes and should be owned by `App` or `DesktopWorkbench`.

- `viewMode: auto | mobile | desktop`
- `effectiveLayoutMode`
- `currentBot`
- pane collapse state for all four panes
- editor tab list
- active editor tab id
- current file tree working directory
- desktop preference values that should persist

Recommended persisted preferences for first version:

- `viewMode`
- pane collapse state

### Pane-Local State

This state should remain local to each pane where possible.

- loading/error states for file tree actions
- chat composer draft and streaming details
- terminal connection/follow state
- transient editor save status text

### Editor Tab Model

Desktop editing requires promoting the current single-file editor state into a tab model. Each open tab should include enough state to avoid rereading files on every interaction.

Minimum tab shape:

- `path`
- `content`
- `savedContent`
- `dirty`
- `lastModifiedNs`
- `loading`
- `saving`
- optional error/status metadata

If a file is already open, selecting it from the tree should activate the existing tab rather than open a duplicate.

## Data Flow

### Layout Mode Resolution

1. Read persisted `viewMode`.
2. Measure viewport width.
3. Resolve `effectiveLayoutMode`.
4. Render either `MobileShell` or `DesktopWorkbench`.

### File Opening on Desktop

Desktop file selection should behave like an IDE, not like a preview-first mobile viewer.

1. User clicks a file in `FileTreePane`.
2. If a tab for that file already exists, activate it.
3. Otherwise load full content and create a new editor tab.
4. Make the new tab active.

Desktop mode should not use preview as the primary file-open flow.

### File Saving

Saving keeps the current optimistic shape and conflict guard.

1. Save active tab content with `lastModifiedNs`.
2. On success, update the tab's saved snapshot and timestamp.
3. Refresh any file metadata that the tree depends on.
4. Do not disturb chat or terminal state.

### Rename and Delete Coordination

- Rename updates open tab paths and labels if the file is open.
- Delete closes any matching open tabs and shows a clear message.

### Bot Switching

Bot switching should be isolated by bot context.

- File tree, editor tabs, chat, and terminal all switch together by bot.
- State from one bot must not leak into another bot.

For the first version, unsaved editor tabs for the current bot are not preserved when confirming a bot switch.

## Error Handling

Errors should appear in the pane that owns the failing action.

### File Tree Errors

Show in left pane:

- listing failure
- directory change failure
- file action failures such as rename, delete, create

### Editor Errors

Show in center editor pane:

- file read failure
- save failure
- conflict detected via `lastModifiedNs`

The first version must not auto-overwrite on conflict.

### Chat Errors

Show in right pane without clearing existing messages or the current draft.

### Terminal Errors

Show in bottom pane with clear recovery actions such as reconnect or rebuild.

### Unsaved Changes Protection

- Closing a dirty tab requires confirmation.
- Switching bots with dirty tabs requires one consolidated confirmation before leaving the current bot.

### Collapsed Pane Behavior

Collapsing a pane should not destroy the pane's state. Re-expanding it should restore the current UI state, including error messages where still relevant.

## Testing Strategy

### Unit and Component Tests

Add tests for:

- layout mode resolution in `auto`, `mobile`, and `desktop`
- pane collapse toggles for all four panes
- desktop workbench rendering only in desktop mode
- editor tab open, activate, close, and dirty confirmation behavior
- bot switch confirmation when unsaved tabs exist

### Integration Tests

Add integration coverage for:

- opening files from tree into editor tabs
- renaming and deleting files with open tabs
- keeping chat and terminal mounted while file actions occur
- preserving pane state when collapsed and expanded

### Mobile Regression Coverage

Existing mobile shell tests should remain in place to ensure:

- current tabbed layout still works
- no desktop-only workbench leaks into mobile mode
- file preview flow still works in mobile mode

### Layout Verification

Add browser-level checks for desktop layout at large widths and existing mobile layout checks at phone widths.

## Migration Plan

Recommended implementation order:

1. Introduce layout mode state and shell split.
2. Add `DesktopWorkbench` with fixed pane containers wired to workbench layout state.
3. Extract file tree and editor state from `FilesScreen`.
4. Add editor tabs and desktop file-open flow.
5. Embed terminal pane.
6. Embed chat pane.
7. Add pane collapse controls and persistence.
8. Add bot-switch dirty-state guard.
9. Expand tests for desktop workbench and mobile regressions.

This order reduces risk by moving one vertical slice at a time while preserving the current mobile experience.

## Trade-Offs

### Why Not Full Rewrite

A rewrite would increase delivery time and create immediate divergence between mobile and desktop implementations. The current code already contains usable business logic and screen-level behavior that can be extracted incrementally.

### Why Not CSS-Only Responsiveness

The current limitation is not just styling. The single-screen `currentTab` shell and screen-local editor state are structural constraints. Pure CSS would produce a fragile layout without fixing the ownership model behind multi-pane desktop behavior.

### Why Fixed Layout First

A fixed desktop workbench delivers the primary workflow quickly while avoiding the state and interaction complexity of draggable docking and split editors. It leaves room for a later iteration if the product proves that advanced docking behavior is worth the added cost.

## Open Questions Resolved In This Design

- Desktop first version uses a fixed workspace, not draggable docking.
- All four panes are collapsible.
- Collapse direction is horizontal for left/right panes and vertical for center top/bottom panes.
- Layout mode uses `auto | mobile | desktop`.
- Desktop editor supports multiple tabs but not split view.
- Desktop file click opens editor tabs directly rather than using preview as the primary flow.
