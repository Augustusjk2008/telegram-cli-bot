# Desktop Workbench IDE Refresh Design

Date: 2026-04-17
Status: Draft approved in conversation, written for review

## Summary

The current desktop workbench has the correct functional slices, but it still reads like a dashboard made of embedded pages. The panes are visually separate cards, the file area behaves like a generic file browser, and the embedded chat and terminal still carry page-level chrome that breaks the IDE illusion.

This design upgrades the desktop workbench into a VSCode-style shell without replacing the existing four-pane layout or rewriting the underlying business logic. The desktop view keeps the current left file area, center editor plus terminal stack, and right AI chat area, but reframes all of them inside a tighter IDE shell with a title bar, activity rail, explorer, editor stack, docked terminal, AI sidecar, and bottom status bar.

The change is deliberately desktop-only. Mobile screens, backend APIs, and the existing pane resize and collapse model remain in place.

## Goals

- Make the desktop experience feel like an IDE rather than a dashboard.
- Keep the current four-pane desktop structure:
  - left file area
  - center editor
  - bottom terminal
  - right AI chat
- Use a VSCode-like deep dark visual system for desktop workbench mode.
- Add stronger desktop shell structure:
  - title bar
  - activity rail
  - explorer
  - editor stack
  - terminal dock
  - AI sidecar
  - status bar
- Increase information density and reduce card-like spacing.
- Preserve current pane resize, collapse, and persisted layout behavior.
- Reuse existing embedded chat and terminal logic instead of reimplementing them.

## Non-Goals

- No mobile redesign.
- No freeform docking or pane reordering.
- No split editors.
- No backend API changes.
- No rewrite of chat or terminal business logic.
- No attempt to make the whole application adopt the new IDE theme outside the desktop workbench.

## User Decisions Captured In This Design

- Desktop workbench should move toward a VSCode-like visual language.
- The desktop shell should keep the current four-pane structure rather than collapsing terminal and chat into one shared panel.
- The work should cover the whole desktop workbench, not just the file area.

## User Experience

### Overall Desktop Shell

Desktop mode should look like one continuous workbench rather than four adjacent cards.

The new vertical rhythm is:

- top title bar
- main workbench body
- bottom status bar

The main horizontal rhythm is:

- activity rail plus explorer on the left
- editor stack and terminal dock in the center
- AI sidecar on the right

Existing resize handles and collapse behavior remain available, but the visual treatment changes to IDE-style separators and panels.

### Title Bar

The current desktop header is too close to a normal page toolbar. It should become a title bar with tighter height and clearer desktop ownership.

Recommended content:

- left: current bot alias, workspace name, compact connection or mode hint
- center: desktop or mobile mode switch, visually de-emphasized
- right: workbench-level actions such as bot switching and view controls

This bar should visually anchor the desktop shell and avoid large rounded controls.

### Left Side: Activity Rail And Explorer

The current left pane is a file card. The new left side should feel like IDE navigation.

Recommended structure:

- narrow activity rail on the far left
- explorer content area on the right

Initial activity rail entries:

- explorer
- git
- AI

The first iteration does not need full content switching for all entries. The rail can initially serve as desktop shell structure and future extension surface while the explorer stays active by default.

Explorer behavior:

- compact `EXPLORER` section label
- current workspace name near the top
- small action icons for create file, create folder, go home, refresh if needed
- flatter file tree rows with lower height and clearer active state
- opened file markers and dirty file indicators
- row actions shown as hover affordances rather than always-visible button clusters

Collapsed-left behavior:

- preserve the activity rail
- hide explorer content
- keep the current collapsed sizing model

That makes the collapsed state still look intentional, not like a broken sidebar.

### Center: Editor Stack

The center area should become the main canvas.

Recommended structure:

- thin editor tab strip
- breadcrumb or context bar below tabs
- editor surface filling the remaining height

Editor tab behavior:

- show basename in the tab label, not the full path
- keep full path available in tooltip or context bar
- replace `*` dirty markers with a dot-based or equivalent IDE-style indicator
- use a flat active tab treatment instead of pill buttons
- keep tab close behavior and dirty-close confirmation

Context bar behavior:

- show current relative path
- show file type or language hint
- keep save action available but visually secondary to keyboard save

Editor surface behavior:

- remove oversized rounded card treatment
- make the code area feel attached to the workbench
- keep current CodeMirror integration and keyboard save behavior

Empty editor state should also be neutral and workbench-like, not a centered marketing-style empty card.

### Bottom: Terminal Dock

The terminal is currently embedded successfully but still reads like a full page in a pane. In desktop mode it should become a docked panel.

Recommended treatment:

- slimmer panel header
- compact connection state and working directory
- keep reconnect or close actions
- reduce page-level padding
- let the terminal canvas dominate the panel body

The bottom terminal remains independently collapsible and vertically resizable.

### Right Side: AI Sidecar

The right chat pane should feel like an IDE assistant panel rather than a transplanted chat page.

Recommended treatment:

- compact side panel header with current bot and running state
- tighter message density
- reduced mobile-chat visual cues
- embedded composer anchored to the bottom of the sidecar
- trace, preview, and running state integrated into the panel language instead of large page blocks where possible

The underlying `ChatScreen` behavior can remain mostly intact, but its `embedded` rendering path should adopt the new workbench chrome and spacing rules.

### Bottom Status Bar

The current desktop shell lacks a closing boundary. Add a status bar across the bottom of the workbench.

Recommended content:

- current working directory or shortened path
- active file dirty or saved state
- terminal connection state
- chat running or idle state
- current layout mode hint

The status bar should be informational, always visible, and low height.

## Visual System

### Desktop-Only IDE Token Scope

Do not globally replace the existing application themes. Instead, scope a desktop-only IDE token layer to the workbench root.

Recommended approach:

- keep existing global tokens and theme selection machinery
- add a workbench-specific token scope at the desktop workbench root
- override only the desktop workbench internals with IDE-oriented values

Recommended token categories:

- workbench background
- panel background
- elevated panel background
- activity rail background
- title bar background
- status bar background
- separator and border contrast
- tab inactive and active states
- hover and selection states
- terminal dock background
- editor canvas background

This lets the desktop workbench stay VSCode-like even if the rest of the application still supports broader themes.

### Shape And Density

The main desktop shell should move away from large radii and card spacing.

Rules:

- square or near-square outer pane corners
- tighter headers
- smaller button radii
- flatter tabs
- thinner separators
- reduced internal padding in embedded desktop panes

The result should feel dense and tool-like, not decorative.

## Architecture

### DesktopWorkbench

`DesktopWorkbench` remains the desktop shell coordinator and should gain ownership of the new shell layers:

- title bar
- main three-column workbench
- bottom status bar
- workbench token scope

The existing resize and collapse state model remains the canonical layout state. This design changes the shell structure and pane chrome, not the persisted pane state semantics.

### PaneChrome

`PaneChrome` should become a shared IDE panel wrapper rather than a card wrapper.

Responsibilities:

- panel header
- collapse and expand affordance
- shared panel border and background language
- compact embedded header sizing

It should not force all panes into the same heavy page-style chrome.

### FileTreePane And FileList

`FileTreePane` owns the explorer header and explorer-level actions.

`FileList` should move toward a tree-row presentation:

- lower-height rows
- clearer active and opened states
- less emphasis on timestamp and size
- action affordances that do not dominate every row

The file browser data flow remains the same.

### EditorPane And FileEditorSurface

`EditorPane` should take responsibility for:

- IDE tab strip
- current-file context bar
- active tab state presentation

`FileEditorSurface` remains responsible for the actual editing surface and save logic, but should render without large card framing when used in desktop workbench mode.

### TerminalPane

`TerminalPane` continues to wrap the existing terminal screen, but desktop embedded mode should render with dock-panel chrome rather than full-page styling.

### ChatPane

`ChatPane` continues to wrap the existing chat screen, but embedded mode should render as an assistant sidecar with tighter density and more neutral tool-panel styling.

## Interaction Rules

### State Signifiers

The workbench should consistently distinguish:

- active file
- opened file
- dirty file
- running assistant
- connected terminal
- collapsed panel

Use restrained markers:

- subtle highlight or border for active rows and active tabs
- dirty dot for unsaved files or tabs
- compact status pill or icon for running states

Avoid large warning blocks unless the condition is truly exceptional.

### Hover, Focus, And Active States

All desktop workbench controls should follow the same interaction language:

- hover raises contrast slightly
- active press darkens or compresses slightly
- keyboard focus uses one consistent outline treatment
- splitter hit targets stay generous even if the visual separators remain thin

### Errors, Loading, And Empty States

Pane-local states should remain pane-local, but their presentation should match the IDE shell.

Examples:

- empty explorer: compact centered panel message
- no file open: quiet empty editor canvas
- terminal loading: inline dock status
- chat running: compact sidecar state indicator
- file or save errors: pane-level status rows instead of oversized page blocks where practical

## Data Flow And Behavioral Boundaries

The behavioral boundaries stay intentionally narrow.

- File opening still routes through the existing desktop tab model.
- File rename and delete still synchronize with open tabs.
- Terminal session behavior stays local to the terminal pane.
- Chat conversation state stays local to the chat pane.
- Bot switching still swaps the whole workbench context and preserves the current dirty-tab confirmation flow.

This is a shell refactor, not a cross-pane state redesign.

## Testing Strategy

### Component And Interaction Tests

Update desktop workbench coverage to assert:

- title bar, activity rail, workbench body, and status bar render in desktop mode
- all four main panes still exist
- left collapse preserves the activity rail while hiding explorer content
- pane collapse and persisted sizing still work
- file clicks still open editor tabs
- rename and delete still synchronize with editor tabs

### Embedded Pane Regression Tests

Add or update focused tests for embedded desktop rendering:

- chat embedded mode uses compact desktop shell structure
- terminal embedded mode keeps connection actions and dock layout
- editor empty state and active-tab state render correctly in IDE mode

These tests should target structure and behavior, not fragile pixel styling.

### Existing Regression Coverage

Keep current coverage for:

- mobile shell behavior
- desktop pane resizing
- desktop file tab behavior
- chat and terminal core functionality

The new shell must not break the existing desktop persistence and resize tests.

## Implementation Order

1. Add desktop workbench shell structure for title bar, activity rail, and status bar.
2. Refactor `PaneChrome` into flatter IDE-style panel chrome.
3. Convert the left pane into activity rail plus explorer layout.
4. Rework editor tabs and context bar to IDE-style structure.
5. Adjust `FileEditorSurface` to remove card-like desktop framing.
6. Tidy terminal embedded mode into dock-panel styling.
7. Tidy chat embedded mode into sidecar styling.
8. Update desktop tests and rerun frontend verification.

## Trade-Offs

### Why Keep The Existing Four-Pane Layout

The user explicitly wants the broader desktop workbench improved, but not replaced with a different docking model. Keeping the current four-pane arrangement delivers the IDE feel while preserving the existing state and resize logic.

### Why Use A Desktop-Scoped Theme Layer

The rest of the application still serves mobile and non-workbench screens. A workbench-scoped IDE token layer avoids destabilizing those screens while giving desktop the stronger visual identity the user asked for.

### Why Reuse Embedded Chat And Terminal Logic

The current embedded chat and terminal flows already work. Replacing their business logic would increase risk without helping the main goal, which is to make the desktop workbench feel like a coherent IDE.
