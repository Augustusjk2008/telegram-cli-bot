import type { AgentSummary } from "../../services/types";

const DEFAULT_CLUSTER = {
  allowCluster: true,
  allowWrite: false,
  sessionPolicy: "persistent" as const,
  timeoutSeconds: 600,
};

type AgentOverrides = Partial<AgentSummary>;

function createAgent(base: AgentSummary, overrides: AgentOverrides = {}): AgentSummary {
  return {
    ...base,
    ...overrides,
    cluster: {
      ...(base.cluster || DEFAULT_CLUSTER),
      ...(overrides.cluster || {}),
    },
  };
}

export function createMainAgent(overrides: AgentOverrides = {}): AgentSummary {
  return createAgent({
    id: "main",
    name: "主 agent",
    systemPrompt: "",
    enabled: true,
    isMain: true,
    cluster: { ...DEFAULT_CLUSTER },
  }, overrides);
}

export function createReviewerAgent(overrides: AgentOverrides = {}): AgentSummary {
  return createAgent({
    id: "reviewer",
    name: "代码审查",
    systemPrompt: "负责审查代码。",
    enabled: true,
    isMain: false,
    cluster: { ...DEFAULT_CLUSTER, sessionPolicy: "ephemeral" },
  }, overrides);
}

export function createTesterAgent(overrides: AgentOverrides = {}): AgentSummary {
  return createAgent({
    id: "tester",
    name: "测试专家",
    systemPrompt: "负责执行测试。",
    enabled: true,
    isMain: false,
    cluster: { ...DEFAULT_CLUSTER, sessionPolicy: "ephemeral" },
  }, overrides);
}
