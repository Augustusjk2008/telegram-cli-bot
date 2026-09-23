import { withApiBase } from "./publicBase";
import type { RemoteWorkspace } from "../services/types";
import { normalizeRemotePath, relativeRemotePath } from "../services/remoteWorkspace";

const EXTERNAL_PROTOCOL_RE = /^(https?:|mailto:|tel:)/i;
const BLOCKED_PROTOCOL_RE = /^(javascript|vbscript|data):/i;
const ABS_PATH_PREFIX = "/abs/path/";

function unwrapLocalFileUrl(href: string) {
  if (href.startsWith(ABS_PATH_PREFIX)) {
    return href.slice(ABS_PATH_PREFIX.length) || "";
  }

  if (!EXTERNAL_PROTOCOL_RE.test(href)) {
    return href;
  }

  try {
    const url = new URL(href);
    const pathname = decodeURIComponent(url.pathname || "");

    if (pathname.startsWith(ABS_PATH_PREFIX)) {
      return pathname.slice(ABS_PATH_PREFIX.length) || "";
    }

    if (/^\/[A-Za-z]:\//.test(pathname)) {
      return pathname;
    }
  } catch {
    return href;
  }

  return href;
}

function cleanHref(href: string) {
  const decoded = decodeURIComponent((href || "").trim());
  if (!decoded) {
    return "";
  }
  const unwrapped = unwrapLocalFileUrl(decoded);
  return unwrapped
    .replace(/^file:\/\/\/?/i, "")
    .split("#")[0]
    .split("?")[0]
    .trim();
}

function normalizePath(path: string) {
  const normalized = path.replace(/\\/g, "/").replace(/\/+/g, "/").replace(/\/$/, "");
  return normalized.replace(/^\/([A-Za-z]:\/)/, "$1");
}

function stripTrailingLocation(path: string) {
  const match = /^(.*?)(:\d+)(:\d+)?$/.exec(path);
  if (!match) {
    return path;
  }
  const candidate = match[1] || "";
  return /^[A-Za-z]$/.test(candidate) ? path : candidate;
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

export function resolvePreviewFilePath(href: string, workingDir: string, platform?: RemoteWorkspace["platform"]) {
  const cleaned = cleanHref(href);
  if (!cleaned || cleaned.startsWith("#") || !isSafeMarkdownHref(cleaned) || isExternalHref(cleaned)) {
    return null;
  }

  if (platform) {
    const candidate = stripTrailingLocation(normalizeRemotePath(cleaned, platform));
    return !candidate || candidate === "." ? null : relativeRemotePath(candidate, workingDir, platform).replace(/^\.\//, "");
  }

  const normalizedCandidate = stripTrailingLocation(normalizePath(cleaned));
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

export function resolveMarkdownImagePath(src: string, markdownPath: string, platform?: RemoteWorkspace["platform"]) {
  const cleaned = cleanHref(src);
  if (!cleaned || cleaned.startsWith("#") || !isSafeMarkdownHref(cleaned) || isExternalHref(cleaned)) {
    return null;
  }

  const normalizedSrc = stripTrailingLocation(platform ? normalizeRemotePath(cleaned, platform) : normalizePath(cleaned));
  if (!normalizedSrc || normalizedSrc === ".") {
    return null;
  }

  if (platform) {
    if (normalizedSrc.startsWith("/")) return normalizedSrc;
    const normalizedMarkdownPath = normalizeRemotePath(markdownPath, platform);
    const slash = normalizedMarkdownPath.lastIndexOf("/");
    return `${slash < 0 ? "" : normalizedMarkdownPath.slice(0, slash + 1)}${normalizedSrc}`.replace(/^\.\//, "");
  }

  if (/^[A-Za-z]:\//.test(normalizedSrc)) {
    return normalizedSrc;
  }

  if (normalizedSrc.startsWith("/")) {
    return normalizedSrc.replace(/^\/+/, "");
  }

  const normalizedMarkdownPath = normalizePath(markdownPath || "");
  const pathParts = normalizedMarkdownPath.split("/").filter(Boolean);
  if (pathParts.length > 0) {
    pathParts.pop();
  }
  const baseDir = pathParts.join("/");
  const joinedPath = baseDir ? `${baseDir}/${normalizedSrc}` : normalizedSrc;
  return normalizePath(joinedPath).replace(/^\.\//, "");
}

export function buildFileDownloadUrl(botAlias: string, filename: string) {
  const params = new URLSearchParams({ filename });
  return withApiBase(`/api/bots/${encodeURIComponent(botAlias)}/files/download?${params.toString()}`);
}
