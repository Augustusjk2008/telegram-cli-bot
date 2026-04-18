# System Functions Workdir Scripts Design

Date: 2026-04-18
Status: Draft approved in conversation, written for review

## Summary

The current Web "system script" feature is still wired like a global admin preset list. It only exposes a hardcoded allowlist, it ignores the active bot's working directory, and its wording still describes the feature as scripts instead of a broader system-function entry.

This design changes the feature into a per-bot "system functions" capability. Every bot gets the same entry point in the chat actions UI. The backend discovers runnable files from the current bot's `<working_dir>/scripts` directory, filters them by runtime platform, and resolves execution from that directory only. The UI wording changes from `系统脚本` to `系统功能` across desktop and mobile chat views.

The design keeps the basic user flow intact: open the list, choose one item, run it, and stream or display the result. The main change is where the items come from and how they are scoped.

## Goals

- Rename the Web action from `系统脚本` to `系统功能`.
- Show the entry for all bots, not only the main bot.
- Discover available items from the active bot's `working_dir/scripts`.
- Remove the hardcoded script allowlist.
- Filter supported files by runtime platform:
  - Windows: `.ps1`, `.bat`
  - Linux: `.sh`, `.py`
- Resolve and execute only files inside the active bot's `working_dir/scripts`.
- Keep the existing Web interaction model:
  - list items
  - run selected item
  - stream or show output

## Non-Goals

- No recursive scan of nested script folders.
- No change to Telegram command naming such as `/system`.
- No attempt to turn arbitrary files outside `scripts` into runnable actions.
- No new script metadata format beyond the existing comment-based title and description extraction.
- No change to mobile or desktop layout structure beyond the wording and bot visibility of the entry.

## User Decisions Captured In This Design

- The user-facing label should become `系统功能`.
- The change should apply to both mobile and desktop Web views.
- The backend should stop using a whitelist.
- The scan root should be the active bot's `working_dir/scripts`.
- The entry should appear for all bots.
- Supported extensions are:
  - Windows: `.ps1`, `.bat`
  - Linux: `.sh`, `.py`

## Current Problems

### Global Instead Of Per-Bot

The current implementation exposes scripts from a repository-level `scripts` directory through global admin endpoints. That breaks the user's expectation that each bot should work relative to its own working directory.

### Hardcoded Filtering

The current implementation has an exposed-name allowlist. That prevents newly added scripts from appearing even when they exist in the expected directory.

### Weak Identity

The current `script_name` is based on the file stem. That creates a collision risk when two files share the same basename with different extensions.

### Misleading Wording

The current Web wording says `系统脚本`, while the requested feature is closer to a general system-function panel that happens to be backed by local scripts.

## Chosen Design

### Scope Model

System functions become bot-scoped. The active bot alias determines which working directory is used for discovery and execution.

The scan root is:

- `<bot working_dir>/scripts`

The feature only reads direct child files of that directory. It does not recurse into subfolders.

### Supported Files

Platform filtering is explicit and narrow.

- On Windows, include only `.ps1` and `.bat`
- On Linux, include only `.sh` and `.py`

Files with any other extension are ignored even if they exist in the directory.

### Stable Item Identity

`script_name` becomes the exact filename including extension, for example:

- `network_traffic.ps1`
- `build_frontend.sh`

This avoids basename collisions and lets the backend resolve the requested target without ambiguity.

`display_name` and `description` continue to be derived from leading script comments using the existing extraction rules.

### Safety Rules

Execution remains constrained to the active bot's `working_dir/scripts`.

The backend must:

- resolve the bot working directory from the current alias
- resolve the `scripts` directory from that working directory
- match the requested `script_name` against discovered direct children only
- reject missing files
- reject unsupported extensions
- reject anything that resolves outside the `scripts` directory

This keeps the feature intentionally narrow and prevents the Web API from becoming a generic arbitrary-file runner.

## API Design

### Endpoint Scope

The capability should move from global admin endpoints to bot-scoped endpoints so the alias participates in discovery and execution.

Recommended routes:

- `GET /api/bots/{alias}/scripts`
- `POST /api/bots/{alias}/scripts/run`
- `POST /api/bots/{alias}/scripts/run/stream`

Keeping `scripts` in the internal route name minimizes churn in the client and payload shape while still changing the user-facing wording to `系统功能`.

### Response Shape

List response keeps the existing shape:

```json
{
  "items": [
    {
      "script_name": "network_traffic.ps1",
      "display_name": "网络流量",
      "description": "查看当前网络连接与流量",
      "path": "C:\\workspace\\demo\\scripts\\network_traffic.ps1"
    }
  ]
}
```

Run responses also keep the existing structure, except `script_name` now includes the extension.

## Backend Design

### Script Discovery

`bot/platform/scripts.py` should stop relying on a repository-global `SCRIPTS_DIR` and a hardcoded allowlist.

Instead, it should expose helpers that accept the target scripts directory or working directory as input. The discovery path should be built from the active bot configuration at request time.

Recommended helper boundaries:

- function to compute supported extensions for the current runtime platform
- function to derive `<working_dir>/scripts`
- function to list direct child script files from that directory
- function to resolve one requested filename safely from that directory
- existing execution and stream helpers can stay path-based

### Web API Layer

`bot/web/api_service.py` should change the system-function helpers to accept:

- manager
- alias
- user id where needed for session lookup or auth continuity

The Web API layer should use the current bot alias to fetch the relevant bot session or profile, then derive the effective working directory for script discovery.

### Execution Rules

Execution behavior remains platform-aware:

- `.ps1` through PowerShell
- `.bat` through shell execution on Windows
- `.sh` through `bash`
- `.py` through `python`

Existing timeout handling, output decoding, and streaming behavior should remain unchanged.

## Frontend Design

### Wording

Change all Web labels on this feature from `系统脚本` to `系统功能`.

That includes:

- action button text
- sheet or dialog title
- helper copy
- loading error copy
- execution result prefix where it currently says `脚本：...`

The user flow stays the same; only the language and scope change.

### Bot Visibility

The `系统功能` action should be available for all bots. The current `main`-only gating should be removed.

### Client Calls

The Web client should become alias-aware for this feature. The frontend service methods should pass the active bot alias when listing or running system functions.

The current method names may stay stable for low-risk implementation, but they must call the new bot-scoped endpoints.

## Testing

### Backend Tests

Add or update tests to verify:

- scripts are discovered from the active bot's `working_dir/scripts`
- Windows includes `.ps1` and `.bat` only
- Linux includes `.sh` and `.py` only
- unsupported files are ignored
- the old allowlist no longer controls visibility
- execution fails for missing filenames
- execution cannot escape the `scripts` directory

### Frontend Tests

Add or update tests to verify:

- the action text is `系统功能`
- non-main bots also show the action
- the sheet or dialog title uses `系统功能`
- compact title rendering still avoids verbose metadata noise
- client requests now include the current bot alias

### Compatibility Notes

The old tests asserting that only `codex_switch_source` is exposed should be rewritten to match dynamic per-directory discovery.

## Risks And Mitigations

### Risk: Ambiguous Working Directory Source

If discovery uses the wrong directory source, the feature may show functions for the wrong bot.

Mitigation:

- derive the path from the active bot alias at request time
- cover this with bot-scoped API tests

### Risk: Filename Collisions

Stem-only identity can resolve the wrong file.

Mitigation:

- use full filename including extension as `script_name`

### Risk: Overly Broad Execution

Removing the allowlist could accidentally widen execution too far.

Mitigation:

- keep extension filtering narrow
- keep discovery non-recursive
- keep resolution confined to direct children of `working_dir/scripts`

## Rollout

This change is safe to ship as one implementation unit because it is limited to:

- script discovery helpers
- bot-scoped Web endpoints
- frontend wording and client wiring
- tests

No data migration is required.
