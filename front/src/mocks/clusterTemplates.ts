import type { ClusterConfigBundle, ClusterTemplateSummary } from "../services/types";

export const MOCK_CLUSTER_TEMPLATES: ClusterConfigBundle[] = [
  {
    id: "full_test",
    name: "全量测试集群",
    description: "并行运行测试、失败归因和回归复核。",
    cluster: {
      enabled: true,
      writePolicy: "main_only",
      conflictPolicy: "snapshot_diff",
      maxParallelAgents: 3,
      defaultTimeoutSeconds: 900,
      modelTiers: { low: "", medium: "", high: "" },
      reasoningEfforts: { low: "", medium: "", high: "" },
    },
    agents: [
      {
        id: "tester",
        name: "测试专家",
        systemPrompt: "Run test commands to completion and record failing tests, error stack traces, and reproduction steps. Report only facts; do not modify code.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
      {
        id: "failure-analyst",
        name: "失败分析",
        systemPrompt: "Analyze the root causes of test failures, distinguishing product defects, outdated tests, and environment issues. Report causes, evidence, and recommended actions.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
      {
        id: "regression-reviewer",
        name: "回归复核",
        systemPrompt: "Verify that fixes address the original issue, and check related regression risks and the necessary test scope. Treat the workspace as read-only.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
    ],
  },
  {
    id: "code_review",
    name: "代码审查集群",
    description: "并行做代码审查、安全审查和测试规划。",
    cluster: {
      enabled: true,
      writePolicy: "main_only",
      conflictPolicy: "snapshot_diff",
      maxParallelAgents: 3,
      defaultTimeoutSeconds: 900,
      modelTiers: { low: "", medium: "", high: "" },
      reasoningEfforts: { low: "", medium: "", high: "" },
    },
    agents: [
      {
        id: "reviewer",
        name: "代码审查",
        systemPrompt: "Review code correctness, boundary conditions, maintainability, and regression risks. Report findings by severity.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
      {
        id: "security-reviewer",
        name: "安全审查",
        systemPrompt: "Check permissions, input validation, path handling, command execution, and risks to sensitive information. Report only verifiable issues.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
      {
        id: "test-planner",
        name: "测试规划",
        systemPrompt: "Identify tests that need to be added or adjusted, specifying test files, test case names, and validation commands.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
    ],
  },
  {
    id: "feature_dev",
    name: "功能开发集群",
    description: "实现、测试和审查并行协作。",
    cluster: {
      enabled: true,
      writePolicy: "main_only",
      conflictPolicy: "snapshot_diff",
      maxParallelAgents: 3,
      defaultTimeoutSeconds: 1200,
      modelTiers: { low: "", medium: "", high: "" },
      reasoningEfforts: { low: "", medium: "", high: "" },
    },
    agents: [
      {
        id: "implementer",
        name: "实现专家",
        systemPrompt: "Implement features within an explicitly defined set of files. State the write scope before editing, then list changed files and validation results.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: true, sessionPolicy: "fork", timeoutSeconds: 1200 },
      },
      {
        id: "tester",
        name: "测试专家",
        systemPrompt: "Run relevant tests, recommend additional tests, and identify causes of failures. Do not modify code by default.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
      {
        id: "reviewer",
        name: "代码审查",
        systemPrompt: "Review the implementation, focusing on behavior regressions, interface consistency, and missing validation.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
    ],
  },
  {
    id: "test_expert",
    name: "测试专家开发集群",
    description: "开发、测试和审查三角色协作，适合围绕测试问题快速修复和回归验证。",
    cluster: {
      enabled: true,
      writePolicy: "main_only",
      conflictPolicy: "snapshot_diff",
      maxParallelAgents: 3,
      defaultTimeoutSeconds: 1200,
      modelTiers: { low: "", medium: "", high: "" },
      reasoningEfforts: { low: "", medium: "", high: "" },
    },
    agents: [
      {
        id: "implementer",
        name: "实现专家",
        systemPrompt: "Modify code within an explicitly defined scope. First state the plan and files to write, then list changed files and validation results.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: true, sessionPolicy: "fork", timeoutSeconds: 1200 },
      },
      {
        id: "tester",
        name: "测试专家",
        systemPrompt: "Run relevant tests and record commands, results, failing tests, and reproduction steps. Do not modify code by default.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
      {
        id: "reviewer",
        name: "代码审查",
        systemPrompt: "Review changes for correctness, regression risks, and missing validation. Report issues ordered by severity and recommended tests.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
    ],
  },
  {
    id: "research_plan",
    name: "调研规划集群",
    description: "资料整理、架构分析和风险评估。",
    cluster: {
      enabled: true,
      writePolicy: "main_only",
      conflictPolicy: "warn_only",
      maxParallelAgents: 3,
      defaultTimeoutSeconds: 900,
      modelTiers: { low: "", medium: "", high: "" },
      reasoningEfforts: { low: "", medium: "", high: "" },
    },
    agents: [
      {
        id: "researcher",
        name: "资料整理",
        systemPrompt: "Collect relevant project files, interfaces, and existing constraints. Report a list of facts and their source locations.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
      {
        id: "architect",
        name: "架构分析",
        systemPrompt: "Break down the proposed design's boundaries, data flows, and module responsibilities. Identify alternatives and tradeoffs.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
      {
        id: "risk-reviewer",
        name: "风险评估",
        systemPrompt: "Identify and prioritize implementation, testing, migration, and operations risks.",
        enabled: true,
        cluster: { allowCluster: true, allowWrite: false, sessionPolicy: "ephemeral", timeoutSeconds: 900 },
      },
    ],
  },
];

export function listMockClusterTemplateSummaries(): ClusterTemplateSummary[] {
  return MOCK_CLUSTER_TEMPLATES.map((item) => ({
    id: item.id,
    name: item.name,
    description: item.description,
    agentCount: item.agents.length,
    writeAgentCount: item.agents.filter((agent) => agent.cluster.allowWrite).length,
    maxParallelAgents: item.cluster.maxParallelAgents,
  }));
}

export function findMockClusterTemplate(templateId: string): ClusterConfigBundle | undefined {
  const found = MOCK_CLUSTER_TEMPLATES.find((item) => item.id === templateId);
  return found ? structuredClone(found) : undefined;
}
