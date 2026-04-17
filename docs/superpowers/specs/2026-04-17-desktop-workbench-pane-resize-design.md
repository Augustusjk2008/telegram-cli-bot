# Desktop Workbench Pane Resize Design

Date: 2026-04-17
Status: Draft approved in conversation, written for review

## Summary

The existing desktop workbench delivers the correct four-pane structure, but it still behaves like a fixed dashboard rather than an editor-grade workspace. The panes use rounded card chrome and fixed grid tracks, which makes the desktop layout feel less like VSCode and prevents users from allocating space based on the task at hand.

This design refines the desktop workbench only. It removes rounded outer pane chrome for the main desktop panes and adds VSCode-style splitter resizing for the left sidebar, right chat sidebar, and the editor-terminal horizontal split. The mobile shell and pane order remain unchanged.

## Goals

- Make the main desktop panes visually square instead of rounded.
- Allow desktop users to drag splitters to resize:
  - left file pane width
  - right chat pane width
  - editor pane height
- Persist resized layout values across reloads.
- Preserve the existing collapse and expand behavior for all four panes.
- Keep the change isolated to desktop mode.

## Non-Goals

- No freeform docking or pane reordering.
- No mobile layout changes.
- No new layout dependency or splitter library.
- No redesign of pane internals such as editor tabs, chat messages, or terminal content.

## User Experience

### Visual Treatment

The four main desktop panes should feel like workbench panels rather than floating cards.

- Remove rounded outer corners from desktop pane chrome.
- Keep borders and header separation so pane boundaries remain clear.
- Use dedicated splitter bars between panes instead of making the pane border itself draggable.
- Splitters should show resize cursors and a clearer hover or active highlight.

### Resizing Behavior

Desktop users can resize the workbench with direct manipulation.

- Drag the divider between the file pane and center pane to resize the left sidebar width.
- Drag the divider between the center pane and chat pane to resize the right sidebar width.
- Drag the divider between the editor and terminal panes to resize the editor height.
- The center pane always consumes the remaining space after side widths are applied.
- The terminal height is derived from the remaining center column height after the editor height is applied.

### Collapse Behavior

Collapse state remains higher priority than custom sizes.

- A collapsed left or right pane still uses the existing narrow collapsed track.
- A collapsed editor or terminal pane still uses the existing compact row behavior.
- Re-expanding a pane restores the last user-selected size rather than resetting to defaults.

## Layout State Model

The current desktop workbench stores only collapse state. This change extends the state model to include persisted pane dimensions.

Recommended shape:

- `filesCollapsed`
- `editorCollapsed`
- `terminalCollapsed`
- `chatCollapsed`
- `filesWidthPx`
- `chatWidthPx`
- `editorHeightPx`

Default values should stay close to the current layout so the first render does not jump unexpectedly.

Recommended defaults:

- `filesWidthPx = 320`
- `chatWidthPx = 384`
- `editorHeightPx = 420`

The state continues to live in the desktop workbench state layer and persists through local storage.

### Component Boundaries

The change should stay concentrated in the workbench shell.

- `DesktopWorkbench` remains responsible for composing the overall three-column and two-row grid.
- `PaneChrome` remains responsible for pane framing and collapse actions, but its outer chrome should become square for desktop panes.
- A small dedicated splitter component or hook may be introduced so pointer logic does not bloat `DesktopWorkbench`.

Recommended additions:

- `usePaneLayout` for clamping, persistence helpers, and drag state
  or
- `PaneResizer` for DOM event wiring and separator rendering

Either is acceptable as long as the ownership remains clear and the workbench root does not turn into one large event handler file.

## Interaction Model

### Input Handling

Use native pointer events instead of a dependency.

Expected flow:

1. `pointerdown` on a splitter records the active axis and starting pointer position.
2. `pointermove` computes the proposed next size.
3. The proposed size is clamped against pane minimums and container constraints.
4. `pointerup` or `pointercancel` finalizes the drag and clears active drag state.

The implementation should also clean up listeners correctly if the component unmounts mid-drag.

### Minimum Size Constraints

The resize logic must protect usability.

Recommended minimums:

- file pane width: `220px`
- chat pane width: `260px`
- editor pane height: `220px`
- terminal pane height: `160px`
- center main pane width reserve: at least `480px`

The exact center reserve may be implemented indirectly by clamping the left and right sidebars against container width.

### Cursor and Feedback

The splitter affordance should be explicit.

- Vertical splitters use `col-resize`.
- Horizontal splitters use `row-resize`.
- Hover state should raise contrast.
- Active drag state should keep the splitter highlighted until release.

## Persistence

The current `web-workbench-pane-state` storage entry should be expanded rather than replaced with a second key. That keeps desktop layout preferences in one place.

Storage rules:

- Invalid or missing persisted numbers fall back to defaults.
- Collapse flags continue to merge against defaults.
- Persist after state changes, including drag completion and collapse toggles.

## Error Handling

The feature is UI-local and should fail soft.

- If local storage cannot be read or written, use in-memory defaults and keep the workbench usable.
- If a persisted value is outside the valid range for the current viewport, clamp it at render time.
- Dragging must never produce negative track sizes, overlapping panes, or a center area with no usable space.

## Testing Strategy

This change should follow TDD and extend the current desktop workbench coverage.

### Unit and Component Tests

Add tests for:

- reading default layout sizes when storage is empty
- restoring persisted layout sizes when storage is valid
- clamping invalid persisted values back into range
- keeping last resized values when panes are collapsed and re-expanded
- rendering square pane chrome for desktop pane containers

### Drag Interaction Tests

Add tests that simulate splitter drag behavior and verify:

- left pane width changes after dragging the left splitter
- right pane width changes after dragging the right splitter
- editor height changes after dragging the horizontal splitter
- layout state is written back to local storage

The tests can assert state-derived DOM styles or serialized storage values. The goal is to verify behavior rather than implementation details.

### Regression Tests

Keep the existing coverage that confirms:

- all four desktop panes render
- collapse state still works
- mobile mode remains unaffected

Run the existing frontend test suite after implementation. A production build should also be run if the tests pass cleanly.

## Implementation Order

1. Extend workbench state types and storage parsing for pane dimensions.
2. Add failing tests for default sizes, persistence, and drag updates.
3. Introduce splitter rendering and pointer-driven resize behavior in the desktop workbench.
4. Remove rounded outer chrome from desktop pane containers.
5. Verify collapse and re-expand behavior with persisted custom sizes.
6. Run frontend tests and build verification.

## Trade-Offs

### Why Native Pointer Handling

The workbench already has a stable and specific layout structure. Native pointer handling is sufficient for three splitters and avoids the cost and abstraction overhead of a pane library.

### Why Persist Sizes in Existing Workbench State

Collapse and size preferences belong to the same user mental model: desktop layout. Storing them together reduces state fragmentation and keeps restoration logic simple.

### Why Keep Pane Order Fixed

The request is for VSCode-like resizing, not a full docking system. Fixed pane order keeps the implementation bounded while delivering the requested workflow improvement.
