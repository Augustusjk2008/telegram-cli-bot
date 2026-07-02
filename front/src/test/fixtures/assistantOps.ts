import { MOCK_ASSISTANT_PROPOSAL_IDS, MOCK_ASSISTANT_PROPOSAL_TITLES } from "../../mocks/assistantOpsData";
import { MockWebBotClient } from "../../services/mockWebBotClient";
import type {
  AssistantAdminAuditItem,
  AssistantPatchMetadata,
  AssistantProposal,
  CreateBotInput,
} from "../../services/types";

const DEFAULT_ASSISTANT_BOT: CreateBotInput = {
  alias: "assistant1",
  botMode: "assistant",
  cliType: "codex",
  cliPath: "codex",
  workingDir: "C:\\workspace\\assistant1",
};

export const assistantProposalIds = MOCK_ASSISTANT_PROPOSAL_IDS;
export const assistantProposalTitles = MOCK_ASSISTANT_PROPOSAL_TITLES;

export async function buildAssistantClient(overrides: Partial<CreateBotInput> = {}) {
  const client = new MockWebBotClient();
  await client.addBot({
    ...DEFAULT_ASSISTANT_BOT,
    ...overrides,
  });
  return client;
}

export function createAssistantProposal(overrides: Partial<AssistantProposal> = {}): AssistantProposal {
  return {
    id: assistantProposalIds.syncMemoryIndex,
    kind: "code",
    title: assistantProposalTitles.syncMemoryIndex,
    body: "- 生成 patch",
    status: "proposed",
    createdAt: "2026-04-28T08:30:00+08:00",
    ...overrides,
  };
}

export function createAssistantPatchMetadata(
  overrides: Partial<AssistantPatchMetadata> = {},
): AssistantPatchMetadata {
  const base: AssistantPatchMetadata = {
    id: assistantProposalIds.syncMemoryIndex,
    proposalId: assistantProposalIds.syncMemoryIndex,
    state: "pending",
    targetAlias: "main",
    targetWorkingDir: "C:\\workspace\\main",
    targetRepoRoot: "C:\\workspace\\main",
    baseCommit: "a1b2c3d4",
    worktreePath: "C:\\workspace\\.assistant\\upgrades\\worktrees\\pr_sync_memory_index",
    patchPath: "upgrades/pending/pr_sync_memory_index.patch",
    generatedAt: "2026-04-28T09:00:00+08:00",
    generatedBy: "1001",
    generator: {
      cliType: "codex",
      cliPath: "codex",
      status: "succeeded",
      elapsedSeconds: 3,
    },
    dryRun: {
      ok: false,
      checkedAt: "",
      stdout: "",
      stderr: "",
      patchPath: "",
      repoRoot: "",
    },
    sensitiveHits: [],
    changedFiles: ["bot/assistant_memory_recall.py"],
    additions: 1,
    deletions: 0,
  };
  return {
    ...base,
    ...overrides,
    generator: {
      ...base.generator,
      ...(overrides.generator || {}),
    },
    dryRun: {
      ...base.dryRun,
      ...(overrides.dryRun || {}),
    },
    sensitiveHits: overrides.sensitiveHits || base.sensitiveHits,
    changedFiles: overrides.changedFiles || base.changedFiles,
  };
}

export function createAssistantAuditItem(
  overrides: Partial<AssistantAdminAuditItem> = {},
): AssistantAdminAuditItem {
  return {
    id: "audit_1",
    createdAt: "2026-04-28T10:00:00+08:00",
    accountId: "member_1",
    userId: 1001,
    username: "alice",
    method: "POST",
    path: "/api/admin/bots/assistant1/assistant/proposals/pr_sync_memory_index/patch",
    action: "assistant.proposal.patch.generate",
    target: {
      botAlias: "assistant1",
      resource: "proposal",
      resourceId: assistantProposalIds.syncMemoryIndex,
    },
    requestSummary: {
      proposalId: assistantProposalIds.syncMemoryIndex,
      targetAlias: "main",
    },
    statusCode: 200,
    ok: true,
    elapsedMs: 12,
    ...overrides,
  };
}
