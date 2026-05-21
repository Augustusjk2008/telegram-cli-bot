import type { ChatMessage, ConversationSummary, PlanExecuteResult } from "../services/types";

export const MOCK_PLAN_PATH = "docs/plan/2026-05-21-1010-plan.md";
export const MOCK_PLAN_MARKDOWN = "# 方案\n- 改 A";

export function wrapPlanDraft(content = MOCK_PLAN_MARKDOWN): string {
  return `<PLAN_DRAFT>\n${content.trim()}\n</PLAN_DRAFT>`;
}

export function buildMockPlanExecutionMessage(planPath = MOCK_PLAN_PATH): string {
  return [
    `请按方案执行。方案文件：${planPath}`,
    "",
    "要求：",
    "- 先阅读方案和相关代码",
    "- 按方案实施",
    "- 不要回到 Plan Mode",
    "- 完成后运行必要验证",
  ].join("\n");
}

type MockPlanExecuteOverrides = Partial<Omit<PlanExecuteResult, "conversation">>;

export function createMockPlanExecuteResult(
  conversation: ConversationSummary,
  overrides: MockPlanExecuteOverrides = {},
): PlanExecuteResult {
  const planPath = overrides.planPath || MOCK_PLAN_PATH;
  return {
    planPath,
    conversation,
    messages: overrides.messages || [],
    executionMessage: overrides.executionMessage || buildMockPlanExecutionMessage(planPath),
  };
}
