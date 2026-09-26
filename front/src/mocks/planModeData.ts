export const MOCK_PLAN_PATH = "docs/plan/2026-05-21-1010-plan.md";

export function buildMockPlanExecutionMessage(planPath = MOCK_PLAN_PATH): string {
  return [
    `Please execute the plan. Plan file: ${planPath}`,
    "",
    "The saved plan is the task for this conversation. Read it, applicable repository instructions, and relevant code before editing. Use the plan's goal and scope, but check its assumptions against the current workspace and adapt stale implementation details as needed.",
    "",
    "Carry out the change end to end. Do not stop after restating the plan, return to this application's Plan Mode, or use a CLI's built-in Plan Mode. Run focused validation, then report the changes, the checks performed, and any remaining blocker. If a required decision cannot be made from the plan and workspace, ask a focused question.",
  ].join("\n");
}
