# DSH Orbit Workspace Phase 0/1 Baseline

Last updated: 2026-11-13 20:24 +08:00

## Environment

- Windows 11 x64, build 26300.
- DSH Desktop is installed at `D:\Programs\dsh` and reports `0.2.1-rc.3` through its bundled command.
- The current PATH command is `C:\Users\JiangKai\.dsh\bin\dsh.cmd`, backed by npm `@deepseek-ai/dsh@0.2.0-rc.2`.
- The official DSH release page currently lists `v0.2.2-rc.2` as the latest release. The release API exposes no Windows installer asset, so the Desktop upgrade remains an in-app updater task.
- Node is `v22.17.0`, npm is `10.9.2`, pnpm is `11.9.0`, Python is `3.13.5`, and Git is `2.41.0.windows.3`.
- The user DSH home is `C:\Users\JiangKai\.dsh`.
- Cloudflared is not installed on PATH. It is a later Phase 6 prerequisite.

## Completed checks

- The shipped Web profile was initialized at `C:\Users\JiangKai\.dsh\profiles\web`.
- The clean Web profile composes Session, Workspace, Workspace Controller, Session Controller, API Remotes, Web Server, Client Workspace, Client Conversation, and Client Session entries.
- A separate `orbit-phase0-web2` profile was created from the Web template for bundle testing.
- The Phase 1 `dsh-orbit-workspace` bundle now includes Host and Client entries, localized metadata, a sidebar panel, a global main panel, capability diagnostics, connection states, and effect-owned cleanup.
- The Phase 1 bundle was installed into `orbit-phase0-web2` with `dsh plugin`; the profile dependency resolves to version `0.1.0-phase1`.
- `node --check dsh-orbit-workspace/index.js` and `node --check dsh-orbit-workspace/client.js` passed.
- The Host lifecycle smoke check passed.
- `dsh --profile orbit-phase0-web2 --dump-config` passed and contains the `dsh-orbit-workspace` entry.
- `dsh --profile orbit-phase0-web2 --help` passed.

## Phase 1 shell result

The bundle registers `orbit-workspace` through `sidebar.panellist` and the keyed `main` slot. Its page renders localized loading, error, disconnected, ready, and empty states, plus metadata-only capability diagnostics for Workspace, Session, Remote, credentials, and settings services. Client subscriptions refresh on connection reset and dispose with the bundle.

## Runtime capability result

The installed Web composition exposes the required Workspace, Session, and Remote building blocks. The current environment still lacks a completed live UI check for Workspace listing, Session open/create, prompt submission, stop, and incremental updates. The public Remote event path and project-only boundary also remain unverified.

The Phase 0 architecture decision is provisional: continue with a native DSH page first, then switch the live path to a loopback project-only sidecar if the Remote surface cannot enforce the selected Workspace allowlist.

## Known diagnostic

`dsh --profile web --dump-config-schema` exits with four existing `unrecognized Loader tree carrier` errors for the shipped `preset-standard`, `preset-ptc`, `preset-minimal`, and `preset-cordis` entries. The same errors reproduce in the clean Web profile and are independent of `dsh-orbit-workspace`.

## Remaining Phase 0 gates

1. Update or confirm the latest DSH Desktop release through its in-app updater.
2. Register the Desktop-managed `dsh` command so the tested command and Desktop runtime are aligned.
3. Use the DSH Web UI to verify one registered Workspace, one Session, one prompt, stop, and live updates.
4. Verify the browser Client receives the required live events through the Remote surface.
5. Finalize the native-page versus sidecar decision after the live allowlist check.
