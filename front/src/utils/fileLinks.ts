const EXTERNAL_PROTOCOL_RE = /^(https?:|mailto:|tel:)/i;
const BLOCKED_PROTOCOL_RE = /^(javascript|vbscript|data):/i;

function cleanHref(href: string) {
  const decoded = decodeURIComponent((href || "").trim());
  if (!decoded) {
    return "";
  }
  return decoded
    .replace(/^file:\/\/\/?/i, "")
    .split("#")[0]
    .split("?")[0]
    .trim();
}

function normalizePath(path: string) {
  return path.replace(/\\/g, "/").replace(/\/+/g, "/").replace(/\/$/, "");
}

export function isExternalHref(href: string) {
  return EXTERNAL_PROTOCOL_RE.test(cleanHref(href));
}

export function isSafeMarkdownHref(href: string) {
  const cleaned = cleanHref(href);
  if (!cleaned) {
    return false;
  }
  return !BLOCKED_PROTOCOL_RE.test(cleaned);
}

export function isLikelyLocalFileHref(href: string) {
  const cleaned = cleanHref(href);
  if (!cleaned || cleaned.startsWith("#") || !isSafeMarkdownHref(cleaned) || isExternalHref(cleaned)) {
    return false;
  }

  return (
    /^[A-Za-z]:[\\/]/.test(cleaned)
    || cleaned.startsWith("/")
    || cleaned.startsWith("./")
    || cleaned.startsWith("../")
    || cleaned.includes("\\")
    || cleaned.includes("/")
    || /\.[A-Za-z0-9_-]{1,16}$/.test(cleaned)
  );
}

export function resolvePreviewFilePath(href: string, workingDir: string) {
  const cleaned = cleanHref(href);
  if (!cleaned || cleaned.startsWith("#") || !isSafeMarkdownHref(cleaned) || isExternalHref(cleaned)) {
    return null;
  }

  const normalizedCandidate = normalizePath(cleaned);
  const normalizedWorkingDir = normalizePath(workingDir || "");

  if (!normalizedCandidate || normalizedCandidate === ".") {
    return null;
  }

  if (/^[A-Za-z]:\//.test(normalizedCandidate)) {
    if (normalizedWorkingDir) {
      const lowerCandidate = normalizedCandidate.toLowerCase();
      const lowerWorkingDir = normalizedWorkingDir.toLowerCase();
      if (lowerCandidate.startsWith(`${lowerWorkingDir}/`)) {
        return normalizedCandidate.slice(normalizedWorkingDir.length + 1);
      }
    }
    return normalizedCandidate;
  }

  if (normalizedWorkingDir && normalizedCandidate.toLowerCase().startsWith(`${normalizedWorkingDir.toLowerCase()}/`)) {
    return normalizedCandidate.slice(normalizedWorkingDir.length + 1);
  }

  return normalizedCandidate.replace(/^\.\//, "");
}
