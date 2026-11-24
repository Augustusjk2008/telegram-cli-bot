function absolutePath(path: string, windows: boolean) {
  let anchor = "/";
  if (windows) {
    const volume = /^(?:\/?([a-z]:)\/|\/\/([^/?\.][^/]*)\/([^/]+)(?:\/|$))/i.exec(path);
    if (!volume) return null;
    anchor = volume[1] || `//${volume[2]}/${volume[3]}`;
    path = path.slice(volume[0].length);
    if (/[:*?"<>|]/.test(path)) return null;
  } else if (!path.startsWith("/")) return null;

  const parts: string[] = [];
  for (const part of path.split("/")) {
    if (part === "..") parts.pop();
    else if (part && part !== ".") parts.push(part);
  }
  return { anchor, parts };
}

export function workspaceRelativePath(path: string, cwd: string, root: string, windows: boolean) {
  if (windows) {
    path = path.replace(/\\/g, "/");
    cwd = cwd.replace(/\\/g, "/");
    root = root.replace(/\\/g, "/");
  }
  const base = absolutePath(root, windows);
  if (!base || !path || /^[a-z][\w+.-]*:\/\//i.test(path)) return null;
  const anchored = path.startsWith("/") || /^\/?[a-z]:/i.test(path);
  if (!anchored && !absolutePath(cwd, windows)) return null;
  const target = absolutePath(anchored ? path : `${cwd}/${path}`, windows);
  const equal = (a: string, b: string) => windows ? a.toLowerCase() === b.toLowerCase() : a === b;
  if (!target || !equal(base.anchor, target.anchor) || target.parts.length <= base.parts.length
    || !base.parts.every((part, index) => equal(part, target.parts[index]))) return null;
  return target.parts.slice(base.parts.length).join("/");
}
