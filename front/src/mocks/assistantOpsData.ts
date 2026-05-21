import type {
  AssistantMemoryEvalReport,
  AssistantMemorySearchItem,
  AssistantPatchMetadata,
  AssistantPerfRecord,
  AssistantProposal,
} from "../services/types";

export const MOCK_ASSISTANT_PROPOSAL_IDS = {
  syncMemoryIndex: "pr_sync_memory_index",
  applyUpgradeGuard: "pr_apply_upgrade_guard",
} as const;

export const MOCK_ASSISTANT_PROPOSAL_TITLES = {
  syncMemoryIndex: "补 memory index 审计",
  applyUpgradeGuard: "apply 前强校验 approved",
} as const;

export type MockAssistantOpsState = {
  proposals: AssistantProposal[];
  proposalDiffs: Record<string, string>;
  proposalPatchDiffs: Record<string, string>;
  proposalPatchMetadata: Record<string, AssistantPatchMetadata>;
  memories: AssistantMemorySearchItem[];
  evalReports: AssistantMemoryEvalReport[];
  perfRecords: AssistantPerfRecord[];
};

export function createMockAssistantOpsState(botAlias: string): MockAssistantOpsState {
  const applyUpgradeGuardDiff = [
    "diff --git a/bot/assistant_upgrade.py b/bot/assistant_upgrade.py",
    "@@ -10,3 +10,7 @@",
    " def apply_upgrade(...):",
    "-    return run_patch()",
    "+    assert proposal.status == 'approved'",
    "+    return run_patch()",
    "+",
    "+def dry_run_upgrade(...):",
    "+    return check_patch()",
    "",
    "diff --git a/tests/test_assistant_upgrade.py b/tests/test_assistant_upgrade.py",
    "@@ -1,2 +1,6 @@",
    "+def test_apply_requires_approved():",
    "+    assert True",
    "",
  ].join("\n");
  const syncMemoryIndexDiff = [
    "diff --git a/bot/assistant_memory_recall.py b/bot/assistant_memory_recall.py",
    "@@ -20,3 +20,8 @@",
    " def recall_assistant_memories(...):",
    "+    emit_audit('memory_recall')",
    "+    return []",
    "",
    "diff --git a/bot/assistant_memory_store.py b/bot/assistant_memory_store.py",
    "@@ -40,2 +40,5 @@",
    "+def record_recall_trace(...):",
    "+    return None",
    "",
  ].join("\n");
  return {
    proposals: [
      {
        id: MOCK_ASSISTANT_PROPOSAL_IDS.syncMemoryIndex,
        kind: "code",
        title: MOCK_ASSISTANT_PROPOSAL_TITLES.syncMemoryIndex,
        body: "- 为 recall 路径补独立 audit\n- 保留现有行为",
        status: "proposed",
        createdAt: "2026-04-28T08:30:00+08:00",
      },
      {
        id: MOCK_ASSISTANT_PROPOSAL_IDS.applyUpgradeGuard,
        kind: "rule",
        title: MOCK_ASSISTANT_PROPOSAL_TITLES.applyUpgradeGuard,
        body: "- apply 前要求 proposal=approved\n- 失败写 last-error audit",
        status: "approved",
        createdAt: "2026-04-28T09:00:00+08:00",
        reviewedBy: "127.0.0.1",
        reviewedAt: "2026-04-28T09:10:00+08:00",
      },
    ],
    proposalDiffs: {
      [MOCK_ASSISTANT_PROPOSAL_IDS.applyUpgradeGuard]: applyUpgradeGuardDiff,
      [MOCK_ASSISTANT_PROPOSAL_IDS.syncMemoryIndex]: syncMemoryIndexDiff,
    },
    proposalPatchDiffs: {
      [MOCK_ASSISTANT_PROPOSAL_IDS.applyUpgradeGuard]: applyUpgradeGuardDiff,
    },
    proposalPatchMetadata: {
      [MOCK_ASSISTANT_PROPOSAL_IDS.applyUpgradeGuard]: {
        id: MOCK_ASSISTANT_PROPOSAL_IDS.applyUpgradeGuard,
        proposalId: MOCK_ASSISTANT_PROPOSAL_IDS.applyUpgradeGuard,
        state: "approved",
        targetAlias: "main",
        targetWorkingDir: "C:\\workspace\\main",
        targetRepoRoot: "C:\\workspace\\main",
        baseCommit: "a1b2c3d4",
        worktreePath: "C:\\workspace\\.assistant\\upgrades\\worktrees\\pr_apply_upgrade_guard",
        patchPath: "upgrades/approved/pr_apply_upgrade_guard.patch",
        generatedAt: "2026-04-28T09:05:00+08:00",
        generatedBy: "127.0.0.1",
        approvedBy: "127.0.0.1",
        approvedAt: "2026-04-28T09:10:00+08:00",
        generator: {
          cliType: "codex",
          cliPath: "codex",
          status: "succeeded",
          elapsedSeconds: 8,
        },
        dryRun: {
          ok: false,
          checkedAt: "",
          stdout: "",
          stderr: "",
          patchPath: "upgrades/approved/pr_apply_upgrade_guard.patch",
          repoRoot: "C:\\workspace\\main",
        },
        sensitiveHits: [],
        changedFiles: [
          "bot/assistant_upgrade.py",
          "tests/test_assistant_upgrade.py",
        ],
        additions: 6,
        deletions: 1,
      },
    },
    memories: [
      {
        id: "mem_pref_cn_short",
        kind: "semantic",
        scope: "user",
        title: "回复偏好",
        summary: "默认简短中文",
        body: "- 默认简短中文\n- 少解释",
        score: 0.96,
        sourceType: "chat",
        sourceRef: "capture_1",
        updatedAt: "2026-04-28T08:00:00+08:00",
      },
      {
        id: "mem_incident_cron",
        kind: "episodic",
        scope: "project",
        title: "cron 根因",
        summary: "pending_run_id 残留",
        body: "- pending_run_id 残留\n- 重启丢队列",
        score: 0.82,
        sourceType: "dream",
        sourceRef: "dream_1",
        updatedAt: "2026-04-28T07:40:00+08:00",
      },
      {
        id: "mem_playbook_release",
        kind: "procedural",
        scope: "global",
        title: "发版惯例",
        summary: "先 dry-run 再 apply",
        body: "- 先 dry-run\n- 冲突先停\n- 审计必留",
        score: 0.74,
        sourceType: "manual",
        sourceRef: "kb_release",
        updatedAt: "2026-04-27T09:30:00+08:00",
        invalidatedAt: "2026-04-27T10:00:00+08:00",
      },
    ],
    evalReports: [
      {
        reportPath: ".assistant/evals/memory/20260428T020000Z.json",
        createdAt: "2026-04-28T10:00:00+08:00",
        metrics: {
          hitAt5: 1,
          staleRecallRate: 0,
        },
        rows: [
          {
            query: "默认简短中文",
            promptBlock: "<ASSISTANT_MEMORY_RECALL>\n1. [semantic/user] 回复偏好: 默认简短中文\n</ASSISTANT_MEMORY_RECALL>",
            hit: true,
            stale: false,
            auditPath: ".assistant/audit/memory/20260428T020000Z-1001.json",
          },
        ],
      },
    ],
    perfRecords: [
      {
        runId: "run_perf_1",
        createdAt: "2026-04-28T10:10:00+08:00",
        botAlias,
        source: "web",
        taskMode: "standard",
        interactive: true,
        userId: 1001,
        status: "completed",
        stageDurations: {
          syncMs: 18,
          indexMs: 11,
          recallMs: 24,
          cliMs: 1320,
          dbMs: 17,
          traceMs: 42,
          pluginMs: 0,
        },
        elapsedMs: 1445,
        promptChars: 1280,
        outputChars: 640,
        traceCount: 7,
        toolCallCount: 2,
        processCount: 3,
      },
      {
        runId: "run_perf_2",
        createdAt: "2026-04-28T10:16:00+08:00",
        botAlias,
        source: "cron",
        taskMode: "dream",
        interactive: false,
        userId: 1001,
        status: "failed",
        stageDurations: {
          syncMs: 24,
          indexMs: 18,
          recallMs: 31,
          cliMs: 2480,
          dbMs: 20,
          traceMs: 16,
          pluginMs: 0,
        },
        elapsedMs: 2688,
        promptChars: 860,
        outputChars: 0,
        traceCount: 5,
        toolCallCount: 1,
        processCount: 2,
        error: "CLI timeout",
      },
      {
        runId: "run_perf_3",
        createdAt: "2026-04-28T10:20:00+08:00",
        botAlias,
        source: "web",
        taskMode: "standard",
        interactive: true,
        userId: 1002,
        status: "failed",
        stageDurations: {
          syncMs: 12,
          indexMs: 15,
          recallMs: 28,
          cliMs: 980,
          dbMs: 12,
          traceMs: 120,
          pluginMs: 85,
        },
        elapsedMs: 1320,
        promptChars: 1140,
        outputChars: 120,
        traceCount: 8,
        toolCallCount: 4,
        processCount: 3,
        error: "plugin render failed",
      },
    ],
  };
}
