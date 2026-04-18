# Desktop Workbench Shell Refactor Design

Date: 2026-04-18
Status: Draft approved in conversation, written for review

## Summary

The current desktop workbench has the correct high-level panes, but several details still behave like embedded pages rather than one coherent IDE shell:

- the left activity rail contains buttons that do not do anything
- the four desktop regions are visually separated from their actual content modules by extra panel chrome
- the file area is still a flat directory list instead of a tree
- page height is influenced by the tallest pane rather than being bounded by the viewport
- the bottom status bar adds noise without solving a real workflow problem

This design refactors the desktop shell into a denser, more VSCode-like workbench while preserving the existing three-column plus center-stack structure:

- left sidebar work area
- center editor above terminal
- right AI chat

The redesign is desktop-only. Mobile mode is out of scope.

## Goals

- Remove non-functional desktop shell controls.
- Make the desktop workbench read as one continuous tool surface instead of embedded page cards.
- Replace the current flat file list with a compact tree browser.
- Keep browser viewport height as the only outer height driver and move overflow to internal pane scroll areas.
- Remove the desktop bottom status bar entirely.
- Keep the existing center editor, bottom terminal, and right chat responsibilities intact.
- Preserve current bot and theme systems.

## Non-Goals

- No mobile layout redesign.
- No freeform pane docking or pane reordering.
- No rewrite of editor, terminal, chat, Git, or settings business logic.
- No attempt to make the left sidebar mirror the right AI chat pane.
- No full repository preloading for the file tree.

## User Decisions Captured In This Design

- The left activity rail should stay, but it must switch real content.
- The left activity rail should expose `文件`, `Git`, and `设置`.
- The left sidebar should not contain an assistant pane.
- Only the editor should keep a top bar because its tab strip is part of the editor itself.
- Other desktop panes should not keep generic outer headers.
- File tree directory click should expand or collapse only and must not change the bot working directory.
- Actual working-directory changes should stay separate from ordinary file browsing.
- The desktop bottom status bar should be removed completely.

## Current Problems

### 1. Left rail is partly decorative

[`front/src/workbench/WorkbenchActivityRail.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/WorkbenchActivityRail.tsx)

The current rail renders `explorer`, `git`, and `assistant`, but only the explorer collapse button has behavior. The other buttons look actionable while doing nothing.

### 2. Pane chrome duplicates the real pane boundary

[`front/src/workbench/PaneChrome.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/PaneChrome.tsx)

The workbench currently wraps multiple panes in a generic shell that adds a separate header, border, and collapse button layer. That makes the visible region and the actual content module feel detached.

### 3. File browsing is still current-directory list navigation

[`front/src/workbench/FileTreePane.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/FileTreePane.tsx)

[`front/src/workbench/useFileBrowser.ts`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/useFileBrowser.ts)

The current file pane is not a tree. It renders one directory listing at a time and changes browsing location by calling `changeDirectory()`.

That conflicts with the requested desktop behavior:

- show a tree like VS Code
- expand directories without changing working directory
- keep terminal and chat context stable unless the user explicitly changes it

### 4. Desktop height ownership is too loose

[`front/src/workbench/DesktopWorkbench.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/DesktopWorkbench.tsx)

The root uses `100dvh`, but internal pane ownership is still uneven because content modules carry page-like layout and scrolling assumptions. The redesign needs explicit internal scroll containers per pane so the outer shell stays locked to the viewport.

### 5. Bottom status bar is unnecessary chrome

[`front/src/workbench/WorkbenchStatusBar.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/WorkbenchStatusBar.tsx)

The current status bar adds another structural layer but does not carry enough value for this workflow. The user explicitly asked for full removal.

## Options Considered

### Option A: Full desktop shell refactor plus path-based directory listing support

- Keep the current desktop layout shape.
- Remove generic pane chrome.
- Make the left rail switch between file tree, Git, and settings.
- Add path-based directory listing support so tree expansion does not change working directory.

Pros:

- Matches the requested UX cleanly.
- Keeps working-directory semantics correct.
- Produces a real tree instead of a visual imitation.

Cons:

- Requires both frontend and backend work.

### Option B: Frontend-only tree using temporary directory changes

- Keep existing file APIs.
- Expand a directory by temporarily changing browse directory and restoring it.

Pros:

- Smaller backend diff.

Cons:

- Pollutes browsing state.
- Risks breaking terminal or chat assumptions.
- Produces race conditions and fragile tree behavior.

### Option C: Visual fake tree over current directory listing

- Change layout and styling only.
- Keep listing one directory at a time.

Pros:

- Lowest implementation cost.

Cons:

- Does not satisfy the requested interaction model.
- Still not a real tree.

## Chosen Approach

Use Option A.

The requested desktop behavior requires a real distinction between:

- browsing arbitrary directories in the tree
- the active file tree expansion state
- the bot's actual working directory

Without path-based listing support, the tree would either be fake or would mutate session state in surprising ways.

## Design

### 1. Desktop Shell Layout

The desktop shell keeps the current macro layout:

- top title bar
- main workbench body
- no bottom status bar

The main workbench body keeps the current functional regions:

- left sidebar
- center editor plus terminal stack
- right AI chat

`DesktopWorkbench` remains the shell coordinator, but it should stop treating each pane as an embedded page card.

Required layout rules:

- desktop root stays locked to `100dvh`
- body row uses `minmax(0, 1fr)`
- every pane wrapper uses `min-h-0 min-w-0 overflow-hidden`
- scrolling happens inside pane content, not on the outer desktop shell

This makes the browser window the only height owner.

### 2. Title Bar

[`front/src/workbench/WorkbenchHeader.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/WorkbenchHeader.tsx)

The existing title bar stays. It already owns:

- current bot switcher entry point
- workspace label
- desktop/mobile/auto view toggle

This design does not add new title-bar responsibilities.

### 3. Left Sidebar Model

The left side becomes a real two-part sidebar:

- activity rail
- active sidebar content

Activity rail entries become:

- `文件`
- `Git`
- `设置`

The rail keeps the existing explorer collapse/expand control at the top, but the other buttons now switch the active sidebar page.

When the left sidebar is collapsed:

- the activity rail remains visible
- the content area disappears
- the selected sidebar page is preserved in state

When expanded:

- the selected sidebar page is rendered next to the rail

The right chat pane remains separate and unchanged in responsibility.

### 4. Pane Chrome Rules

`PaneChrome` should be removed from the desktop workbench path.

Pane boundary policy:

- editor pane boundary is defined by the editor module itself
- terminal pane boundary is defined by the embedded terminal root itself
- chat pane boundary is defined by the embedded chat root itself
- left sidebar boundary is defined by the active sidebar content container

Header policy:

- editor keeps its tab strip and editor-local metadata row
- terminal does not get a generic outer header
- chat does not get a generic outer header
- Git and settings in the left sidebar do not keep standalone full-page headers when embedded

This removes the "container around a container" look.

### 5. Center Editor And Terminal

[`front/src/workbench/EditorPane.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/EditorPane.tsx)

[`front/src/workbench/TerminalPane.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/TerminalPane.tsx)

Center region behavior remains:

- editor on top
- terminal below
- vertical resize handle between them

Editor rules:

- keep tab strip
- keep active file info and save affordance
- keep internal scrolling only
- treat the tab strip as part of editor content, not outer chrome

Terminal rules:

- render directly into the pane body
- keep embedded terminal behavior
- rely on terminal internal layout and scrolling

The editor and terminal stay resizable through the existing separator model.

### 6. Right Chat Pane

[`front/src/workbench/ChatPane.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/workbench/ChatPane.tsx)

The right pane remains the dedicated AI chat area.

Rules:

- no duplicate assistant page in the left sidebar
- no generic outer header in desktop mode
- embedded chat root fills the pane
- message list and composer handle their own internal scrolling and anchoring

### 7. File Tree Behavior

The file pane changes from current-directory navigation to a real tree.

#### Tree interactions

- file click opens the file in the center editor
- directory click expands or collapses only
- directory click must not change actual working directory
- node density should be reduced to a smaller font and tighter row height, closer to VS Code
- file actions stay available, but should move into tree-row affordances rather than card-style buttons

#### Working directory semantics

The tree must distinguish between:

- expanded directories in the tree
- the current browse root shown in the tree
- the bot's actual working directory

The current working directory should be visibly marked in the tree.

If the user wants to make another directory the real working directory, that action must stay explicit. To preserve the existing workdir boundary from the earlier file-browser/workdir separation design, the tree should not silently call workdir update APIs on row click.

Recommended behavior:

- a directory row offers a secondary action such as `在设置中设为工作目录`
- that action switches the left sidebar to `设置`
- the settings panel receives the selected path as a prefilled target for confirmation and save

This preserves the "browsing is not workdir mutation" rule while keeping the workflow fast.

#### Tree loading model

The tree should be lazy-loaded.

Initial load:

- render the workspace root node
- load only the root's immediate children

Expand directory:

- request that directory's children if not already loaded
- cache loaded children in tree state
- preserve expansion state until pane unmount or bot change

Do not recursively preload the whole repository.

### 8. Git And Settings Embedding

[`front/src/screens/GitScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/GitScreen.tsx)

[`front/src/screens/SettingsScreen.tsx`](/C:/Users/JiangKai/telegram_cli_bridge/refactoring/front/src/screens/SettingsScreen.tsx)

The left sidebar should embed Git and settings as narrow-pane variants rather than full-page screens.

Git embedded mode:

- remove the standalone page header
- keep repository summary, action buttons, changed file sections, and diff area
- adapt spacing for a narrow sidebar width
- keep its own internal scrolling

Settings embedded mode:

- remove the standalone page header
- keep settings sections and form logic
- support receiving an optional prefilled workdir target from the file tree flow
- keep its own internal scrolling

This can be achieved either by:

- adding an `embedded` rendering mode to each screen
- or extracting their content body into reusable embedded components

The key requirement is not the exact extraction method, but the removal of standalone-page chrome when rendered inside the workbench.

### 9. Desktop State Model

The desktop persisted state should be simplified.

Keep:

- left sidebar collapsed state
- active left sidebar page
- left sidebar width
- chat width
- editor height

Discard as active desktop concepts:

- editor collapsed
- terminal collapsed
- chat collapsed

Those fields may still exist in old local storage payloads, but the new desktop workbench should ignore them during read and only write the new reduced state shape going forward.

This aligns persisted state with the new interaction model.

## Backend/API Design

The file tree requires path-based directory listing that does not mutate session working state.

### Existing constraint

Current file browsing is centered on the current browse directory. The tree needs to inspect arbitrary paths without changing:

- real working directory
- current browse directory
- active CLI session assumptions

### Proposed API change

Extend the existing file listing API so it can optionally list a target path without changing session state.

Recommended shape:

- existing directory listing route keeps current behavior when no target path is provided
- when `path` is provided, the backend returns entries for that path only
- the request does not update `working_dir`
- the request does not update `browse_dir`

The returned payload can keep the current `DirectoryListing` structure:

- `workingDir`
- `entries`
- `isVirtualRoot`

For path-based tree requests, `workingDir` should represent the path that was listed.

This is intentionally smaller than introducing a separate tree-specific API surface.

## Frontend Architecture

### DesktopWorkbench

`DesktopWorkbench` should own:

- layout measurements
- resize state
- active left sidebar page
- sidebar collapsed state
- composition of left, center, and right regions

It should no longer own generic pane headers.

### WorkbenchActivityRail

`WorkbenchActivityRail` should change from passive icon list to active navigation control.

New responsibilities:

- render `文件`, `Git`, `设置`
- show selected page
- trigger sidebar page switch
- keep top collapse/expand button

### File Tree State

The current `useFileBrowser()` hook is centered on one active directory listing. That is not sufficient for a lazy tree.

Refactor direction:

- either replace it with a tree-oriented hook
- or split it into:
  - path listing support
  - tree expansion/cache state
  - file mutation actions

Regardless of implementation shape, the tree state must support:

- root path
- expanded directory set
- loaded children by directory path
- loading state per directory
- error state per directory
- current working directory marker

### Embedded Git And Settings

Embedded rendering should be explicit rather than inferred from container size.

Recommended pattern:

- add `embedded` props to Git and settings content paths
- suppress page headers in embedded mode
- keep existing business actions intact

## Data Flow

### File tree expansion

1. Desktop workbench loads current bot context.
2. File tree requests the workspace root listing.
3. User clicks a directory row.
4. The row toggles expansion.
5. If children are not cached yet, frontend requests listing for that directory path.
6. Backend returns entries for that path without mutating session state.
7. Tree updates only that node branch.

### Open file

1. User clicks a file row in the tree.
2. Tree emits the file path.
3. Editor tab state opens or activates the file.
4. Center editor becomes the active reading/editing surface.

### Set working directory from tree

1. User triggers `在设置中设为工作目录` on a directory row.
2. Left sidebar switches to `设置`.
3. Settings receives the selected path as prefilled target.
4. User confirms save through existing workdir update flow.
5. On success, workbench refreshes the working-directory marker and any dependent panels.

## Error Handling

### File tree

- If a directory child load fails, show the error inline on that node or branch.
- Do not clear the entire tree for one node failure.
- Keep already loaded branches intact.

### Git and settings

- Left sidebar content failures stay local to the selected sidebar page.
- Git failure must not block editor, terminal, or chat.
- Settings failure must not block editor, terminal, or chat.

### Layout

- If old local storage contains unsupported desktop pane fields, ignore them and fall back to new defaults where needed.
- Resize clamping remains in place so invalid stored sizes cannot break the shell.

## Testing

### Backend

Add coverage for path-based directory listing:

- listing current directory without `path` keeps current behavior
- listing arbitrary `path` returns that path's entries
- path-based listing does not modify real working directory
- path-based listing does not modify browse directory

### Frontend unit and integration

Add or update coverage for:

- activity rail switches between `文件`, `Git`, and `设置`
- left collapse keeps the rail visible and preserves the selected sidebar page
- desktop status bar no longer renders
- terminal and chat render without generic outer pane headers
- editor keeps its own tab/header behavior
- file tree expands and collapses directories without calling workdir mutation
- file click still opens editor tabs
- tree can route a directory into settings as a pending workdir target
- old desktop storage payloads do not break the new shell

### Browser-level layout checks

Keep or extend Playwright checks to verify:

- desktop root fits the viewport
- all four desktop regions remain visible
- overflowing file tree content scrolls internally instead of growing the full page
- embedded Git and settings remain usable in the left sidebar width

## Risks And Mitigations

### Risk 1: Tree browsing accidentally reintroduces workdir mutation

Mitigation:

- keep path-based listing read-only
- make workdir changes explicit through settings flow

### Risk 2: Reusing full-page Git and settings layouts inside the sidebar causes cramped UI

Mitigation:

- give both screens explicit embedded mode
- remove standalone headers and oversized spacing in embedded mode

### Risk 3: Old pane state logic leaks into the new shell

Mitigation:

- narrow the persisted state shape
- add compatibility reads and focused tests for stale local storage data

### Risk 4: Large repositories make the tree feel slow

Mitigation:

- load root only at startup
- lazy-load each directory on first expansion
- cache loaded branches during the session

## Implementation Notes For The Next Plan

The implementation plan should be split into at least these tracks:

1. backend path-based listing support and tests
2. desktop shell state and layout refactor
3. left activity rail and embedded Git/settings
4. file tree state, rendering, and interactions
5. desktop regression and layout verification
