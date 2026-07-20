---
name: orbit-maintenance
description: Use when changing Orbit Safe Claw native agent, Pi, cluster, session/history flow, LiteLLM Transfer gateway, plugin runtime or manifests, installation, updater, release packaging, or their focused tests.
---

# Orbit Maintenance

Load only the reference for the subsystem being changed. Do not read every reference by default.

## Route by subsystem

- Native agent, Pi RPC/runtime/session, AG-UI, cluster, context usage, workspace history: read [references/native-agent.md](references/native-agent.md).
- LiteLLM routes, gateway runtime, compact conversion, endpoint modes: read [references/transfer-gateway.md](references/transfer-gateway.md).
- Plugin manifests, registry, runtime, view sessions, Vivado waveform: read [references/plugin-system.md](references/plugin-system.md).
- Install/start scripts, runtime paths, updater, release packaging: read [references/release-runtime.md](references/release-runtime.md).

If a change crosses subsystems, read only the references for the affected boundaries.

## Workflow

1. Identify the affected runtime contract and its consumers.
2. Read the routed reference completely, then inspect the named source and current tests.
3. Preserve existing routes, event shapes, persistence, permissions and user-visible behavior unless the task explicitly changes them.
4. Add or update focused regression coverage for behavior changes.
5. Run the reference-specific checks plus the smallest relevant broader gate.
6. Report changed files, verification evidence and any unverified boundary.
