export const MOCK_PLAN_PATH = "docs/plan/2026-05-21-1010-plan.md";

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
