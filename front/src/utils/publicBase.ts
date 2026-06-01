function normalizeBasePath(value: string | undefined): string {
  const raw = String(value || "").trim();
  if (!raw || raw === "/") {
    return "";
  }
  return `/${raw.replace(/^\/+/, "").replace(/\/+$/, "")}`;
}

export function publicBasePath(): string {
  const env = typeof __PUBLIC_ENV__ !== "undefined" ? __PUBLIC_ENV__ : {};
  return normalizeBasePath(env.VITE_API_BASE_URL || env.VITE_BASE_PATH || env.WEB_BASE_PATH);
}

export function withApiBase(path: string): string {
  const base = publicBasePath();
  const rawPath = String(path || "");
  if (!base || /^https?:\/\//i.test(rawPath) || /^wss?:\/\//i.test(rawPath)) {
    return rawPath;
  }
  const normalizedPath = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
  if (normalizedPath === base || normalizedPath.startsWith(`${base}/`)) {
    return normalizedPath;
  }
  return `${base}${normalizedPath}`;
}

export function buildWsUrl(path: string, params?: URLSearchParams | Record<string, string | number | boolean | undefined>): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
  const url = new URL(withApiBase(path), origin);
  if (params instanceof URLSearchParams) {
    params.forEach((value, key) => url.searchParams.set(key, value));
  } else if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    });
  }
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
