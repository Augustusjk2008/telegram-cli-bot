const PLAN_DRAFT_OPEN = "<PLAN_DRAFT>";
const PLAN_DRAFT_CLOSE = "</PLAN_DRAFT>";

export function extractPlanDraft(text: string): string {
  const value = String(text || "");
  const start = value.indexOf(PLAN_DRAFT_OPEN);
  if (start < 0) {
    return "";
  }
  const contentStart = start + PLAN_DRAFT_OPEN.length;
  const end = value.indexOf(PLAN_DRAFT_CLOSE, contentStart);
  if (end < 0) {
    return "";
  }
  return value.slice(contentStart, end).trim();
}

export function stripPlanDraftTags(text: string): string {
  return extractPlanDraft(text) || String(text || "");
}
