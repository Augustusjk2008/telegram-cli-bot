---
name: orbit-maintenance
description: Use when changing Orbit Safe Claw CLI or native-agent execution, cluster, session/history flow, remote workspace/terminal/Git bridge, plugin runtime or manifests, installation, updater, release packaging, or their focused tests.
---

# Orbit Maintenance

Load only the reference for the subsystem being changed. Do not read every reference by default.

## Route by subsystem

- Codex exec/app-server, Claude, Antigravity, native Pi RPC/runtime/session, AG-UI, shared cluster contracts, context usage and workspace history: read [references/native-agent.md](references/native-agent.md).
- DeepSeek Harness CLI configuration, headless JSON, MCP patch injection, session/history and support boundaries: read [references/deepseek-harness.md](references/deepseek-harness.md); read the native-agent reference when changing shared cluster behavior.
- Remote workspace, SSH transport, remote MCP/Pi extension, remote Git and terminal isolation: read [references/remote-workspace.md](references/remote-workspace.md).
- Plugin manifests, registry, runtime, Host API, runtime installers, view sessions, artifacts/audit and bundled plugins: read [references/plugin-system.md](references/plugin-system.md).
- Install/start scripts, runtime paths, updater, release packaging: read [references/release-runtime.md](references/release-runtime.md).

If a change crosses subsystems, read only the references for the affected boundaries.

## Workflow

1. Identify the affected runtime contract and its consumers.
2. Read the routed reference completely, then inspect the named source and current tests. Resolve outdated documentation against current source, pinned dependencies and tests; update the affected guidance in place.
3. Preserve existing routes, event shapes, persistence, permissions and user-visible behavior unless the task explicitly changes them.
4. Add or update tests only for stable contracts, important boundaries, high-risk behavior or real bug regressions. Documentation and mechanical changes do not need new tests.
5. Run the smallest checks relevant to the change. For documentation, verify commands, links and implementation claims; expand testing when behavior changes or unresolved concerns require it.
6. Report changed files, verification evidence and any unverified boundary.
