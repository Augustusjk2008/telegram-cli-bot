function normalizeDebugPath(value: string) {
  return String(value || "").replace(/\\/g, "/").replace(/\/+/g, "/").replace(/\/$/, "");
}

export function toWorkspaceRelativeSourcePath(sourcePath: string, workspaceRoot: string) {
  const source = normalizeDebugPath(sourcePath);
  const root = normalizeDebugPath(workspaceRoot);
  if (!source || !root) {
    return source;
  }

  const sourceKey = source.toLowerCase();
  const rootKey = root.toLowerCase();
  if (sourceKey === rootKey) {
    return "";
  }
  if (!sourceKey.startsWith(`${rootKey}/`)) {
    return source;
  }
  return source.slice(root.length + 1);
}
