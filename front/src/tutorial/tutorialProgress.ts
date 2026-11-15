export const TUTORIAL_STATE_STORAGE_KEY = "web-tutorial-state";

export type TutorialProgress = {
  v: 1;
  /** True once the prompt has been opened in this browser; clears the logo hint. */
  seen: boolean;
  chapterId: string;
  stepIndex: number;
  completed: string[];
};

const EMPTY_PROGRESS: TutorialProgress = { v: 1, seen: false, chapterId: "", stepIndex: 0, completed: [] };

export function readTutorialProgress(): TutorialProgress {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(TUTORIAL_STATE_STORAGE_KEY) || "null");
    if (!parsed || typeof parsed !== "object" || (parsed as { v?: unknown }).v !== 1) {
      return { ...EMPTY_PROGRESS };
    }
    const raw = parsed as Record<string, unknown>;
    const stepIndex = Number(raw.stepIndex);
    return {
      v: 1,
      seen: raw.seen === true,
      chapterId: typeof raw.chapterId === "string" ? raw.chapterId : "",
      stepIndex: Number.isInteger(stepIndex) && stepIndex > 0 ? stepIndex : 0,
      completed: Array.isArray(raw.completed)
        ? [...new Set(raw.completed.filter((item): item is string => typeof item === "string"))]
        : [],
    };
  } catch {
    return { ...EMPTY_PROGRESS };
  }
}

/** Merges a patch into the stored state and returns the result; storage failures keep the in-memory value. */
export function updateTutorialProgress(patch: Partial<Omit<TutorialProgress, "v">>): TutorialProgress {
  const next: TutorialProgress = { ...readTutorialProgress(), ...patch, v: 1 };
  try {
    localStorage.setItem(TUTORIAL_STATE_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Ignore storage failures.
  }
  return next;
}
