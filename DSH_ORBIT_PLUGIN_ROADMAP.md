# DSH Orbit Workspace Plugin Roadmap

Status: proposed

Target: the latest DeepSeek Harness Desktop release on Windows, with the official `dsh` command enabled.

This document describes a new DeepSeek Harness plugin inspired by Orbit Safe Claw. It keeps the useful visual language and DeepSeek stream semantics from Orbit, while using DeepSeek Harness as the runtime for projects, sessions, providers, credentials, and model execution.

The plugin deliberately does not carry Orbit's multi-agent cluster, Telegram gateway, account database, or multi-account Web model. It is a single-user project and session console with authenticated remote access.

## Decisions captured

- Use the latest DSH release during development. Do not hard-pin one DSH version. Record the tested `dsh --version` in build and bug reports, and use capability detection where an API may vary.
- Start with a native DSH page and a DSH sidebar entry. Keep the first streaming prototype inside DSH so it can reuse Workspace and Session services.
- Enforce project-only remote access in the production path. If the native DSH page cannot provide that boundary, add a loopback sidecar and place Cloudflared in front of the sidecar.
- Treat registered DSH Workspaces as projects. Do not accept arbitrary filesystem paths in the first release.
- Support chat, session status, stop, retry, and project switching first. Defer Files, Git, Terminal, Debug, and plugin previews.
- Use one active Session at a time in the first milestone. Add multiple project/session tabs after the lifecycle and reconnect paths are stable.
- Use Cloudflare Quick Tunnel for local development and a named tunnel or tunnel token for real deployments.
- Keep provider configuration in DSH Settings → Models. The plugin reads the active provider and model metadata; it does not create a second provider registry or store a second copy of the API key.
- Store one generated or user-supplied remote access credential through DSH's credential service. Use an HttpOnly cookie after login; never put the token in a URL or browser local storage.

## Reference material

- DSH plugin authoring: [Your first plugin](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/develop/basic/index.md).
- DSH Workspace and Session client surface: [ui-workspace](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-workspace/README.md).
- DSH provider configuration: [Model providers](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/providers.md).
- DSH Host/Client Remote assembly: [api-remotes](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/api/remotes/README.md).
- Cloudflared Host/Client example: [dsh-cftunnel](https://github.com/weicy98/dsh-cftunnel).
- Orbit DeepSeek parser: [`bot/cli.py`](bot/cli.py), beginning at `DeepSeekJsonStreamParser`.
- Orbit tunnel lifecycle reference: [`bot/web/tunnel_service.py`](bot/web/tunnel_service.py), beginning at `TunnelService`.
- Orbit chat visual references: [`front/src/screens/ChatScreen.tsx`](front/src/screens/ChatScreen.tsx), [`front/src/components/ChatMarkdownMessage.tsx`](front/src/components/ChatMarkdownMessage.tsx), and [`front/src/components/ChatComposer.tsx`](front/src/components/ChatComposer.tsx).

## Goals and non-goals

### Goals

- Show several registered DSH Workspaces in a compact project picker.
- Open or create a Session inside the selected Workspace.
- Display incremental assistant text, thinking, tool activity, final output, usage, and errors.
- Send prompts, stop turns, retry failed turns, and reconnect after the browser or tunnel reconnects.
- Provide a responsive Orbit-inspired page for desktop and mobile browsers.
- Expose only selected projects through the production remote gateway.
- Start, stop, inspect, and recover a Cloudflared process.
- Keep provider credentials inside DSH's credential system.

### Non-goals for the first release

- Multi-agent orchestration or team configuration.
- Telegram integration.
- Multiple accounts, invitations, roles, or per-user permissions.
- A replacement for DSH's Files, Git, Terminal, or Debug surfaces.
- Arbitrary directory browsing.
- A second model provider catalog.
- Full visual parity with every Orbit screen.

## Architecture

The initial package should contain a Host half, a browser Client half, and shared contracts:

```text
DSH Host
  ├─ Workspace / Session adapter
  ├─ project selection persistence
  ├─ remote token credential
  ├─ optional project-only sidecar
  └─ Cloudflared lifecycle

DSH Web Client
  ├─ sidebar entry
  ├─ project picker
  ├─ Session timeline
  ├─ composer and turn controls
  └─ tunnel / connection status

Shared
  ├─ project and Session types
  ├─ normalized stream events
  ├─ error codes
  └─ feature/capability detection
```

The native page should use DSH's Workspace and Session APIs directly. If those APIs cannot provide a reliable live stream or cannot restrict the remote surface to selected projects, the Host starts a loopback sidecar:

```text
Cloudflared
    ↓
127.0.0.1:orbit-dsh-proxy
    ↓
project/session allowlist
    ↓
DSH Host services
```

The sidecar must never proxy the whole DSH administration surface when project-only access is enabled.

## Package layout

Use a standalone package so DSH can install it as a normal bundle:

```text
dsh-orbit-workspace/
├─ package.json
├─ pnpm-lock.yaml
├─ cordis.patch.yml
├─ locale/
│  ├─ en.json
│  └─ zh.json
├─ src/
│  ├─ host/
│  │  ├─ index.ts
│  │  ├─ workspace-adapter.ts
│  │  ├─ session-adapter.ts
│  │  ├─ project-store.ts
│  │  ├─ remote-gateway.ts
│  │  ├─ auth-store.ts
│  │  └─ tunnel-manager.ts
│  ├─ client/
│  │  ├─ index.tsx
│  │  ├─ OrbitWorkspacePage.tsx
│  │  ├─ ProjectPicker.tsx
│  │  ├─ SessionHeader.tsx
│  │  ├─ ChatTimeline.tsx
│  │  ├─ ChatComposer.tsx
│  │  ├─ StreamStatus.tsx
│  │  └─ styles/
│  └─ shared/
│     ├─ project-types.ts
│     ├─ stream-events.ts
│     ├─ errors.ts
│     └─ capabilities.ts
└─ test/
   ├─ host/
   ├─ client/
   └─ fixtures/
```

The bundle manifest should declare the Host entry, browser entry, `dsh.bundle.patch`, locale resources, and the DSH services required by each half. Keep the package compatible with the latest DSH dependency range rather than a single exact release.

## Core contracts

### Project and Session model

Use durable DSH identities:

```ts
type Project = {
  id: string;
  title: string;
  directory: string;
  sessionIds: string[];
};

type ProjectSession = {
  id: string;
  projectId: string;
  title: string;
  status: "idle" | "running" | "waiting" | "completed" | "error";
  updatedAt: string;
};
```

Persist selected Workspace IDs and the last active Session per Workspace. Directory paths are display data and validation context, never the primary identity.

### Normalized stream events

```ts
type StreamEvent =
  | { type: "session"; sessionId: string }
  | { type: "text"; text: string }
  | { type: "thinking"; text: string }
  | { type: "status"; phase: string; data?: unknown }
  | { type: "tool_call"; callId?: string; data: unknown }
  | { type: "tool_result"; callId?: string; data: unknown }
  | { type: "usage"; turn: number; step: number; usage: Record<string, number> }
  | { type: "final"; text: string; truncated?: boolean }
  | { type: "error"; message: string };
```

If native DSH services expose structured events, adapt them directly. If the Host launches headless `dsh`, port Orbit's parser behavior into TypeScript. Preserve these invariants:

- bounded text and raw-output retention;
- a single stable Session ID per process;
- `final` replaces the visible answer body;
- `turn_end` must carry a valid terminal reason;
- events after `final` fail the turn;
- incomplete usage remains partial and never becomes a complete estimate;
- failures keep the body received so far and complete the turn exactly once.

### Host RPC and sidecar API

Start with a small internal API:

```text
projects.list
projects.select
sessions.list
sessions.open
sessions.create
sessions.send
sessions.stop
sessions.retry
remote.status
remote.login
remote.logout
tunnel.status
tunnel.start
tunnel.stop
```

If a sidecar is needed, expose only the corresponding HTTP/WebSocket endpoints:

```text
GET  /api/projects
GET  /api/projects/:id/sessions
POST /api/projects/:id/sessions
POST /api/sessions/:id/messages
POST /api/sessions/:id/stop
GET  /api/sessions/:id/stream
GET  /api/remote/status
POST /api/remote/login
POST /api/remote/logout
```

Unknown paths must be rejected. Every project and Session request must be checked against the selected-project allowlist.

### Settings and credentials

Use DSH settings for non-secret values:

```text
selectedWorkspaceIds
activeWorkspaceId
activeSessionByWorkspace
tunnelMode
tunnelHostname
proxyPort
```

Use DSH credentials for:

```text
ORBIT_DSH_REMOTE_TOKEN
```

Provider keys remain under DSH's Models configuration. The plugin receives provider/model metadata only and never returns the full API key to the browser, logs, or stream history.

## Implementation phases

### Phase 0 — Windows baseline and architecture spike

Estimated effort: 2–3 days.

Tasks:

1. Install the latest DSH Desktop on Windows.
2. Enable the `dsh` command from Desktop's **Manage dsh Command** menu.
3. Record `dsh --version`, Node version, Windows version, and profile path in the development notes.
4. Create a clean Web profile for plugin testing.
5. Confirm the current DSH release exposes the Workspace list, Session open/create, prompt submission, stop, and live update surfaces needed by the plugin.
6. Verify whether a browser Client plugin can receive the required live events through the public Remote surface.
7. Decide whether the native page can enforce project-only remote access. If it cannot, enable the sidecar design.

Exit criteria:

- a minimal bundle loads and unloads;
- one registered Workspace can be listed;
- one Session can be opened;
- one prompt can be submitted;
- the team has a recorded decision on native page versus sidecar.

### Phase 1 — Bundle skeleton and navigation

Estimated effort: 2–4 days.

Tasks:

- create `package.json`, `cordis.patch.yml`, Host entry, Client entry, and locales;
- register one sidebar action and one page route;
- add a loading, error, empty, and disconnected state;
- add capability detection for Workspace, Session, Remote, credential, and settings services;
- add clean disposal for every Host process, timer, listener, and Client registration.

Exit criteria:

- `dsh plugin --profile web add file:.` installs the bundle;
- the plugin can be enabled and disabled without restarting DSH;
- missing optional services produce a clear in-page diagnostic;
- no API key or token appears in diagnostics.

### Phase 2 — Workspace and Session adapter

Estimated effort: 4–6 days.

Tasks:

- list registered Workspaces;
- select several projects;
- display Session summaries grouped by project;
- open an existing Session;
- create a new Session in the selected Workspace;
- send a prompt;
- stop a running turn;
- restore the selected project and Session after browser reload;
- handle deleted, archived, or unavailable Workspaces.

Exit criteria:

- project selection survives a reload;
- Session navigation never crosses project boundaries;
- a missing Workspace removes itself from the selected set;
- stop and navigation cannot leave the UI permanently busy.

### Phase 3 — Stream adapter and history reconciliation

Estimated effort: 4–7 days.

Tasks:

- implement the normalized `StreamEvent` contract;
- adapt native DSH events or port the Orbit JSONL parser;
- reconcile incremental text with final text;
- pair tool calls and tool results by `callId`;
- preserve thinking and status events separately from answer text;
- handle reconnect, replay, duplicate events, and sequence gaps;
- retain partial output on error or cancellation;
- expose model, provider, usage, and context information where DSH provides it.

Exit criteria:

- a long response streams without duplicated text;
- reconnecting the browser does not restart the Session turn;
- final output replaces the preview exactly once;
- malformed or incomplete streams end in a visible error state;
- usage is marked partial when required fields are missing.

### Phase 4 — Orbit-inspired interface

Estimated effort: 1–2 weeks.

Tasks:

- extract Orbit-like color, spacing, radius, border, typography, and status tokens;
- use DSH primitives for buttons, menus, focus rings, tooltips, and overlays;
- implement the project picker;
- implement the Session header and status indicators;
- implement Markdown message rendering;
- implement thinking/tool trace disclosure;
- implement the composer, stop, retry, and reconnect controls;
- implement narrow-screen layout and touch-safe hit targets;
- support DSH light/dark theme changes.

Exit criteria:

- desktop and mobile layouts remain usable without horizontal scrolling;
- the page follows DSH theme changes;
- a streaming turn remains readable while tool details expand;
- keyboard focus and Escape behavior work for all overlays.

### Phase 5 — Single-user authentication and project-only gateway

Estimated effort: 4–7 days.

Tasks:

- generate or accept a remote access token;
- save it through DSH credentials;
- add login, logout, rotation, and status endpoints;
- issue an HttpOnly, Secure, SameSite cookie after login;
- implement constant-time token comparison;
- add failed-login throttling;
- add Origin and CSRF checks;
- bind the gateway to loopback only;
- enforce the selected Workspace allowlist on every request;
- redact authorization headers and credentials from logs.

Exit criteria:

- a valid token opens the project page;
- an invalid token never reaches DSH Session operations;
- rotating the token invalidates existing remote sessions;
- a browser cannot access an unselected Workspace by changing an ID in the URL;
- credentials never appear in browser payloads, logs, or history.

### Phase 6 — Cloudflared lifecycle

Estimated effort: 3–6 days.

Tasks:

- implement Quick Tunnel start and stop;
- parse the public URL from Cloudflared output;
- check local readiness before launch;
- verify the public endpoint after URL acquisition;
- report starting, connected, verifying, running, stopped, and error states;
- terminate the complete process tree on stop or plugin unload;
- detect stale processes after DSH restart;
- add a verified Cloudflared download path for Windows;
- store the executable outside the plugin source directory;
- verify downloaded binaries by SHA-256;
- add named tunnel/token mode after Quick Tunnel works.

Exit criteria:

- the public URL reaches the authenticated page;
- WebSocket or SSE streaming works through the tunnel;
- stopping the tunnel closes active remote streams;
- DSH restart does not leave an orphaned Cloudflared process;
- a failed download or checksum produces a recoverable error.

### Phase 7 — Multi-project persistence and recovery

Estimated effort: 3–6 days.

Tasks:

- persist selected Workspace IDs;
- persist last active Session per Workspace;
- support project reorder and removal;
- add a project-level connection status;
- recover after DSH restarts;
- clear stale Session references;
- keep one active Session for the first release;
- add multiple Session tabs only after recovery tests pass.

Exit criteria:

- reopening the page restores the selected projects;
- DSH restart does not corrupt the selection state;
- a missing Session is reported and removed cleanly;
- project switching never sends a prompt to the previous project.

### Phase 8 — Provider integration

Estimated effort: 2–3 days.

Tasks:

- read the active provider and model metadata from DSH;
- display the provider and model in the Session header;
- display reasoning level when available;
- surface provider errors without exposing credentials;
- document OpenAI Chat Completions, OpenAI Responses, Anthropic Messages, and Gemini base-URL rules;
- test custom provider model discovery;
- test manual model entry when discovery fails;
- verify provider switching does not bind the UI to the previous Session incorrectly.

The plugin should not duplicate DSH's provider form in this phase. DSH's Models page remains the source of truth for the base URL, protocol, model catalog, and API key.

### Phase 9 — Verification and release

Estimated effort: 1–2 weeks.

Host tests:

- Workspace and Session allowlists;
- token comparison, rotation, logout, and throttling;
- stream parsing and event reconciliation;
- duplicate and out-of-order events;
- Cloudflared process cleanup;
- URL extraction and public health checks;
- checksum failure and download interruption;
- secret redaction.

Client tests:

- project switching;
- Session switching;
- streaming text merge;
- final-answer replacement;
- thinking and tool trace disclosure;
- stop, retry, and reconnect;
- mobile layout;
- theme changes;
- keyboard and touch interactions.

Manual integration matrix:

- latest DSH Desktop on Windows 11;
- clean DSH Web profile;
- plugin install, enable, disable, update, and uninstall;
- DSH restart during an active turn;
- browser reload during streaming;
- Quick Tunnel and named tunnel;
- WebSocket/SSE through Cloudflared;
- invalid provider URL;
- failed model discovery;
- manual model ID;
- remote token rotation;
- deleted or archived Workspace.

Release checks:

```powershell
npm run build
npm test
npm pack --dry-run
dsh --version
dsh plugin --profile web add file:.
```

Do not hard-pin the DSH version. Instead, record the tested version in release notes, run a latest-version smoke test, and fail early with a capability diagnostic when a required DSH service is unavailable.

## Risk register

| Risk | Effect | Mitigation |
| --- | --- | --- |
| DSH API changes | Plugin fails to load or loses live updates | Capability detection, latest-version smoke test, small adapter layer |
| Custom Host events are not forwarded | Native page cannot receive live project updates | Use typed DSH Session APIs or switch the live path to the sidecar |
| Native page exposes too much DSH | Project-only access is not enforceable | Put Cloudflared in front of the project-only sidecar |
| Quick Tunnel instability | Remote URL changes or becomes unavailable | Use Quick Tunnel for development and named tunnels for deployment |
| Orbit frontend coupling | Large bundle and fragile imports | Extract tokens and a small set of components; use DSH primitives |
| Provider protocol mismatch | Requests reach the wrong endpoint | Make protocol and base URL explicit; test the resulting request path |
| Orphaned Cloudflared process | Tunnel survives plugin shutdown | Own the process handle, terminate the process tree, and probe stale PIDs |
| Secret leakage | Remote token or provider key exposed | DSH credential service, HttpOnly cookie, redacted logs, no URL tokens |
| Concurrent project confusion | Prompt reaches the wrong Session | Bind every request to Workspace ID and Session ID and test rapid switching |

## MVP acceptance checklist

- [ ] Latest DSH Desktop on Windows installs and enables the plugin.
- [ ] The plugin adds a DSH sidebar entry and page.
- [ ] Several registered Workspaces can be selected.
- [ ] A Session can be opened or created in the selected Workspace.
- [ ] Prompts stream incrementally.
- [ ] Thinking, tool calls, tool results, final output, and errors remain distinct.
- [ ] Stop, retry, reload, and reconnect work.
- [ ] The UI works on desktop and narrow mobile widths.
- [ ] Provider and model metadata appear without exposing keys.
- [ ] Quick Tunnel reaches the authenticated page.
- [ ] The production gateway exposes only selected projects.
- [ ] Remote token login, logout, and rotation work.
- [ ] Cloudflared exits when the plugin stops.
- [ ] DSH restart does not leave an orphaned process.
- [ ] Clean-profile installation and uninstall succeed.
- [ ] The tested DSH version and known compatibility limits are recorded.

## Expected schedule

The native-page MVP should take approximately four to six weeks for one experienced TypeScript/React developer. The project-only sidecar, hardened Cloudflared lifecycle, reconnect behavior, and release matrix bring the expected production effort to roughly six to ten weeks. Files, Git, Terminal, Debug, and full Orbit workbench parity should be treated as later milestones and can add one to three months.

