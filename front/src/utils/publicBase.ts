function normalizeBasePath(value: string | undefined): string {
  const raw = String(value || "").trim();
  if (!raw || raw === "/") {
    return "";
  }
  return `/${raw.replace(/^\/+/, "").replace(/\/+$/, "")}`;
}

const API_BASE_KEYS = ["VITE_API_BASE_URL", "VITE_BASE_PATH", "WEB_BASE_PATH"] as const;
const ASSET_BASE_KEYS = ["VITE_BASE_PATH", "WEB_BASE_PATH", "VITE_API_BASE_URL"] as const;

type PublicEnvSource = "runtime" | "build";

export type PublicBaseDiagnostics = {
  pagePath: string;
  selectedBasePath: string;
  configuredBasePath: string;
  source: PublicEnvSource;
  envKey: string;
};

function publicEnvWithSource(): { env: Record<string, string | undefined>; source: PublicEnvSource } {
  const runtimeEnv = typeof window !== "undefined"
    ? (window as Window & { __TCB_PUBLIC_ENV__?: Record<string, string | undefined> }).__TCB_PUBLIC_ENV__
    : undefined;
  if (runtimeEnv) {
    return { env: runtimeEnv, source: "runtime" };
  }
  return {
    env: typeof __PUBLIC_ENV__ !== "undefined" ? __PUBLIC_ENV__ : {},
    source: "build",
  };
}

function currentPagePath(): string {
  return typeof window !== "undefined" ? window.location.pathname || "/" : "/";
}

function pageUsesBasePath(base: string): boolean {
  if (!base) {
    return true;
  }
  const pathname = currentPagePath();
  return pathname === base || pathname.startsWith(`${base}/`);
}

function selectBaseValue(env: Record<string, string | undefined>, keys: readonly string[]) {
  for (const key of keys) {
    const value = String(env[key] || "").trim();
    if (value) {
      return { key, value };
    }
  }
  return { key: "", value: "" };
}

function resolveBaseDiagnostics(keys: readonly string[]): PublicBaseDiagnostics {
  const { env, source } = publicEnvWithSource();
  const selected = selectBaseValue(env, keys);
  const configuredBasePath = normalizeBasePath(selected.value);
  return {
    pagePath: currentPagePath(),
    selectedBasePath: pageUsesBasePath(configuredBasePath) ? configuredBasePath : "",
    configuredBasePath,
    source,
    envKey: selected.key,
  };
}

export function publicBasePath(): string {
  return resolveBaseDiagnostics(API_BASE_KEYS).selectedBasePath;
}

export function publicAssetBasePath(): string {
  return resolveBaseDiagnostics(ASSET_BASE_KEYS).configuredBasePath;
}

export function publicApiBaseDiagnostics(): PublicBaseDiagnostics {
  return resolveBaseDiagnostics(API_BASE_KEYS);
}

function withBasePath(base: string, path: string): string {
  const rawPath = String(path || "");
  if (!rawPath) {
    return rawPath;
  }
  if (!base || /^https?:\/\//i.test(rawPath) || /^wss?:\/\//i.test(rawPath)) {
    return rawPath;
  }
  const normalizedPath = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
  if (normalizedPath === base || normalizedPath.startsWith(`${base}/`)) {
    return normalizedPath;
  }
  return `${base}${normalizedPath}`;
}

export function withApiBase(path: string): string {
  return withBasePath(publicBasePath(), path);
}

export function withPublicBase(path: string): string {
  return withBasePath(publicAssetBasePath(), path);
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

export function buildApiUrl(path: string, params?: URLSearchParams | Record<string, string | number | boolean | undefined>): string {
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
  return url.toString();
}
