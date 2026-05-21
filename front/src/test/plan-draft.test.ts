import { expect, test } from "vitest";
import { extractPlanDraft, stripPlanDraftTags } from "../utils/planDraft";

test("extractPlanDraft returns the first complete plan draft", () => {
  expect(extractPlanDraft("分析\n<PLAN_DRAFT>\n# 方案\n- A\n</PLAN_DRAFT>")).toBe("# 方案\n- A");
});

test("extractPlanDraft ignores incomplete draft", () => {
  expect(extractPlanDraft("<PLAN_DRAFT>\n# 方案")).toBe("");
});

test("stripPlanDraftTags removes the wrapper", () => {
  expect(stripPlanDraftTags("前文\n<PLAN_DRAFT>\n# 方案\n</PLAN_DRAFT>\n后文")).toBe("# 方案");
});
