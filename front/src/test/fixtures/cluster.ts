import type {
  BotClusterConfig,
  BotOverview,
  ClusterAgentTask,
  ClusterBundleDiff,
  ClusterBundlePreviewResult,
  ClusterConfigBundle,
  ClusterConfigBundleAgent,
  ClusterStatus,
  ClusterTaskMessage,
  ClusterTaskStatus,
} from "../../services/types";
import { createMainAgent, createTesterAgent } from "./agents";

const DEFAULT_MODEL_TIERS = { low: "", medium: "", high: "" };

export function createClusterConfig(overrides: Partial<BotClusterConfig> = {}): BotClusterConfig {
  const base: BotClusterConfig = {
    enabled: true,
    writePolicy: "main_only",
    conflictPolicy: "snapshot_diff",
    maxParallelAgents: 2,
    defaultTimeoutSeconds: 120,
    modelTiers: { ...DEFAULT_MODEL_TIERS },
  };
  return {
    ...base,
    ...overrides,
    modelTiers: {
      ...base.modelTiers,
      ...(overrides.modelTiers || {}),
    },
  };
}

export function createClusterBundleAgent(
  overrides: Partial<ClusterConfigBundleAgent> = {},
): ClusterConfigBundleAgent {
  const base: ClusterConfigBundleAgent = {
    id: "tester",
    name: "测试专家",
    systemPrompt: "负责执行测试。",
    enabled: true,
    cluster: {
      allowCluster: true,
      allowWrite: false,
      sessionPolicy: "ephemeral",
      timeoutSeconds: 900,
    },
  };
  return {
    ...base,
    ...overrides,
    cluster: {
      ...base.cluster,
      ...(overrides.cluster || {}),
    },
  };
}

export function createClusterTemplateBundle(
  overrides: Partial<ClusterConfigBundle> = {},
): ClusterConfigBundle {
  const base: ClusterConfigBundle = {
    id: "full_test",
    name: "全量测试集群",
    description: "跑测试",
    cluster: createClusterConfig({ maxParallelAgents: 3, defaultTimeoutSeconds: 900 }),
    agents: [createClusterBundleAgent()],
  };
  return {
    ...base,
    ...overrides,
    cluster: createClusterConfig(overrides.cluster || base.cluster),
    agents: overrides.agents
      ? overrides.agents.map((agent) => createClusterBundleAgent(agent))
      : base.agents.map((agent) => createClusterBundleAgent(agent)),
  };
}

export function createClusterBundleDiff(
  bundle: ClusterConfigBundle,
  overrides: Partial<ClusterBundleDiff> = {},
): ClusterBundleDiff {
  const base: ClusterBundleDiff = {
    deleteAgents: [],
    createAgents: bundle.agents.map((agent) => agent.id),
    updateAgents: [],
    clusterChanges: {},
    overwritesAgents: bundle.agents.length > 0,
  };
  return {
    ...base,
    ...overrides,
  };
}

export function createClusterBundlePreview(
  bundle = createClusterTemplateBundle(),
  overrides: Partial<ClusterBundlePreviewResult> = {},
): ClusterBundlePreviewResult {
  return {
    bundle,
    diff: overrides.diff || createClusterBundleDiff(bundle),
  };
}

export function createClusterOverview(overrides: Partial<BotOverview> = {}): BotOverview {
  const base: BotOverview = {
    alias: "main",
    cliType: "codex",
    status: "running",
    workingDir: "C:\\workspace",
    isProcessing: false,
    cluster: createClusterConfig(),
    agents: [createMainAgent()],
  };
  return {
    ...base,
    ...overrides,
    cluster: createClusterConfig(overrides.cluster || base.cluster || {}),
    agents: overrides.agents || base.agents,
  };
}

export function createClusterStatus(overrides: Partial<ClusterStatus> = {}): ClusterStatus {
  const base: ClusterStatus = {
    enabled: true,
    modelTiers: { ...DEFAULT_MODEL_TIERS },
    mcp: {
      serverName: "tcb-cluster",
      activeCliType: "codex",
      runtime: { state: "runtime_ready", message: "运行态可用" },
      codex: { state: "installed", message: "已安装" },
      claude: { state: "not_checked", message: "未使用" },
      kimi: { state: "not_checked", message: "未使用" },
    },
    agents: [{
      id: "tester",
      name: "测试专家",
      enabled: true,
      allowCluster: true,
      allowWrite: false,
      sessionPolicy: "ephemeral",
      timeoutSeconds: 600,
    }],
  };
  return {
    ...base,
    ...overrides,
    modelTiers: {
      ...base.modelTiers,
      ...(overrides.modelTiers || {}),
    },
    mcp: {
      ...base.mcp,
      ...(overrides.mcp || {}),
      runtime: overrides.mcp?.runtime
        ? { ...base.mcp.runtime, ...overrides.mcp.runtime }
        : base.mcp.runtime,
      codex: { ...base.mcp.codex, ...(overrides.mcp?.codex || {}) },
      claude: { ...base.mcp.claude, ...(overrides.mcp?.claude || {}) },
      kimi: { ...base.mcp.kimi, ...(overrides.mcp?.kimi || {}) },
    },
    agents: overrides.agents || base.agents,
  };
}

export function createClusterTaskMessage(
  overrides: Partial<ClusterTaskMessage> = {},
): ClusterTaskMessage {
  return {
    sequence: 1,
    taskId: "clt_1",
    agentId: "tester",
    kind: "progress",
    content: "开始",
    createdAt: "2026-05-06T10:00:01+08:00",
    ...overrides,
  };
}

export function createClusterTask(
  overrides: Partial<ClusterAgentTask> = {},
): ClusterAgentTask {
  return {
    taskId: "clt_1",
    agentId: "tester",
    message: "跑测试",
    status: "completed",
    modelTier: "low",
    timeoutSeconds: 900,
    deadlineExceeded: false,
    allowWrite: false,
    createdAt: "2026-05-06T10:00:00+08:00",
    startedAt: "2026-05-06T10:00:01+08:00",
    completedAt: "2026-05-06T10:00:02+08:00",
    messageCount: 2,
    latestMessageSequence: 2,
    messages: [
      createClusterTaskMessage(),
      createClusterTaskMessage({
        sequence: 2,
        kind: "final",
        content: "完成",
        createdAt: "2026-05-06T10:00:02+08:00",
      }),
    ],
    output: "ok",
    error: "",
    ...overrides,
  };
}

export function createClusterTaskStatus(
  overrides: Partial<ClusterTaskStatus> = {},
): ClusterTaskStatus {
  const tasks = overrides.tasks || [createClusterTask()];
  const queuedCount = tasks.filter((item) => item.status === "queued").length;
  const runningCount = tasks.filter((item) => item.status === "running").length;
  const completedCount = tasks.filter((item) => item.status === "completed").length;
  const failedCount = tasks.filter((item) => item.status === "failed").length;
  return {
    tasks,
    queuedCount,
    runningCount,
    completedCount,
    failedCount,
    pendingCount: queuedCount + runningCount,
    ...overrides,
  };
}

export const DEFAULT_CLUSTER_PANEL_JSON = createClusterTemplateBundle({
  id: "custom",
  name: "自定义",
  description: "测试",
  cluster: createClusterConfig({ maxParallelAgents: 1, defaultTimeoutSeconds: 600 }),
  agents: [
    createClusterBundleAgent({
      id: "tester",
      name: "测试",
      systemPrompt: "跑测试",
      cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 600 },
    }),
  ],
});
