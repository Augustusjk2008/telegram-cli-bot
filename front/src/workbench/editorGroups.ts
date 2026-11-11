import type { EditorGroup, EditorGroupsState } from "./workbenchTypes";

export function normalizeEditorGroups(raw: unknown, paths: string[], activePath = ""): EditorGroupsState {
  const candidate = raw && typeof raw === "object" ? raw as Partial<EditorGroupsState> : {};
  const available = new Set(paths);
  function group(value: EditorGroup | undefined): EditorGroup {
    const entries = Array.isArray(value?.paths)
      ? [...new Set(value.paths.filter((path) => available.has(path)))]
      : [];
    return { paths: entries, activePath: entries.includes(value?.activePath || "") ? value!.activePath : entries[0] || "" };
  }
  const left = group(candidate.left);
  const right = group(candidate.right);
  const assigned = new Set([...left.paths, ...right.paths]);
  left.paths.push(...paths.filter((path) => !assigned.has(path)));
  if (!left.activePath) left.activePath = left.paths.includes(activePath) ? activePath : left.paths[0] || "";
  return {
    left,
    right,
    activeGroupId: candidate.activeGroupId === "right" && right.paths.length > 0 ? "right" : "left",
    splitRatio: typeof candidate.splitRatio === "number" && Number.isFinite(candidate.splitRatio)
      ? Math.min(0.8, Math.max(0.2, candidate.splitRatio))
      : 0.5,
  };
}
