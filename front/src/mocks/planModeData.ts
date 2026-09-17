export const MOCK_PLAN_PATH = "docs/plan/2026-05-21-1010-plan.md";

export function buildMockPlanExecutionMessage(planPath = MOCK_PLAN_PATH): string {
  return [
    `Please execute the plan. Plan file: ${planPath}`,
    "",
    "Requirements:",
    "- Read the plan and relevant code first",
    "- Implement according to the plan",
    "- Do not return to this application's Plan Mode or use Claude Code's built-in Plan Mode",
    "- Run the necessary validation when finished",
  ].join("\n");
}
