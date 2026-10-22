import { createContext, lazy, Suspense, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { WebBotClient } from "../services/webBotClient";
import { applyResolvedAppearance } from "./appearanceRuntime";
import { BUILTIN_THEME, builtinLibrary, resolveAppearance } from "./resolveAppearance";
import type { ThemeCreateInput, ThemeLibrary, ThemeUpdateInput } from "./types";
import "./appearance.css";

const ThemeManagerScreen = lazy(() => import("../screens/ThemeManagerScreen").then((module) => ({ default: module.ThemeManagerScreen })));
type ThemeSession = { key: string; client: WebBotClient; canManage?: boolean; previewOnly?: boolean };
type CreateInput = Omit<ThemeCreateInput, "expectedRevision"> & { expectedRevision?: number };
type UpdateInput = Omit<ThemeUpdateInput, "expectedRevision"> & { expectedRevision?: number };

export function requestThemeManagerLeave(action: () => void) {
  const event = new CustomEvent("theme-manager-before-leave", { cancelable: true, detail: action });
  if (window.dispatchEvent(event)) action();
}

function errorMessage(error: unknown) { return error instanceof Error ? error.message : "主题操作失败，请重试"; }

function validateLibrary(library: ThemeLibrary): ThemeLibrary {
  if (library?.scope !== "global") throw new Error("主题服务需要更新，请重载宿主服务后重试");
  if (library?.schemaVersion !== 1 || !Number.isSafeInteger(library.revision) || library.revision < 0 || !Array.isArray(library.themes)
    || (library.error !== undefined && typeof library.error !== "string")) {
    throw new Error("主题库数据版本或格式不受支持");
  }
  const ids = new Set<string>();
  for (const theme of library.themes) {
    if (!theme || typeof theme.id !== "string" || !theme.id || ids.has(theme.id)
      || typeof theme.name !== "string" || !theme.name.trim() || theme.baseId !== BUILTIN_THEME.id
      || typeof theme.readonly !== "boolean" || theme.readonly !== (theme.id === BUILTIN_THEME.id)) throw new Error("主题库包含无效的主题信息");
    ids.add(theme.id);
    resolveAppearance(theme);
  }
  const themes = [BUILTIN_THEME, ...library.themes.filter((theme) => theme.id !== BUILTIN_THEME.id)];
  return { ...library, themes, selectedThemeId: themes.some((theme) => theme.id === library.selectedThemeId) ? library.selectedThemeId : BUILTIN_THEME.id };
}

function cacheKey() {
  return `web-ui-themes:global:v1:${window.location.pathname}`;
}

function loginThemeKey() {
  return `web-ui-theme:login:v1:${window.location.pathname}`;
}

function useAppearanceState() {
  const sessionRef = useRef<ThemeSession | null>(null);
  const readyRef = useRef(false);
  const generationRef = useRef(0);
  const reloadSequenceRef = useRef(0);
  const libraryRef = useRef<ThemeLibrary>(builtinLibrary());
  const [session, setSession] = useState<ThemeSession | null>(null);
  const [library, setLibrary] = useState<ThemeLibrary>(libraryRef.current);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [managerOpen, setManagerOpen] = useState(false);
  const [loginThemeId, setLoginThemeId] = useState<string | null>(null);
  const accept = useCallback((next: ThemeLibrary, cache = true) => {
    const valid = validateLibrary(next);
    libraryRef.current = valid;
    setLibrary(valid);
    setError(valid.error || "");
    if (cache && !valid.error) {
      try { localStorage.setItem(cacheKey(), JSON.stringify(valid)); } catch { /* In-memory operation remains available. */ }
    }
    return valid;
  }, []);

  const reload = useCallback(async () => {
    const activeSession = sessionRef.current;
    if (!activeSession) return;
    const generation = generationRef.current;
    const requestSequence = ++reloadSequenceRef.current;
    const startedRevision = libraryRef.current.revision;
    setLoading(true);
    try {
      const next = await (activeSession.previewOnly
        ? activeSession.client.listPublicUiThemes()
        : activeSession.client.listUiThemes());
      if (generation !== generationRef.current || requestSequence !== reloadSequenceRef.current) return;
      validateLibrary(next);
      if (libraryRef.current.revision === startedRevision || next.revision >= libraryRef.current.revision) {
        const accepted = accept(next);
        readyRef.current = !accepted.error;
      }
    } catch (failure) {
      if (generation !== generationRef.current || requestSequence !== reloadSequenceRef.current) return;
      if (libraryRef.current.revision === startedRevision) {
        readyRef.current = false;
        accept(builtinLibrary(), false);
        setError(errorMessage(failure));
      }
      throw failure;
    } finally {
      if (generation === generationRef.current && requestSequence === reloadSequenceRef.current) setLoading(false);
    }
  }, [accept]);

  const bindSession = useCallback((next: ThemeSession | null) => {
    const previous = sessionRef.current;
    if (previous?.key === next?.key && previous?.client === next?.client && previous?.canManage === next?.canManage && previous?.previewOnly === next?.previewOnly) return;
    generationRef.current += 1;
    sessionRef.current = next;
    readyRef.current = false;
    setSession(next);
    setManagerOpen(false);
    setLoginThemeId(null);
    const fallback = builtinLibrary();
    accept(fallback, false);
    applyResolvedAppearance(resolveAppearance(BUILTIN_THEME));
    if (!next) { setLoading(false); return; }
    if (next.previewOnly) {
      try { setLoginThemeId(localStorage.getItem(loginThemeKey())); } catch { /* Login themes also work without browser storage. */ }
    }
    try {
      const raw = localStorage.getItem(cacheKey());
      if (raw) accept(validateLibrary(JSON.parse(raw)), false);
    } catch { /* The server remains authoritative if the cache is unavailable. */ }
    void reload().catch(() => {});
  }, [accept, reload]);

  const appearance = useMemo(() => {
    const preview = session?.previewOnly && library.themes.find((theme) => theme.id === loginThemeId);
    return resolveAppearance(preview || library.themes.find((theme) => theme.id === library.selectedThemeId) || BUILTIN_THEME);
  }, [library, loginThemeId, session?.previewOnly]);

  useLayoutEffect(() => {
    applyResolvedAppearance(appearance);
  }, [appearance]);

  useLayoutEffect(() => {
    if (!session) return;
    const onStorage = (event: StorageEvent) => {
      if (event.key === cacheKey()) void reload().catch(() => {});
    };
    const onVisibility = () => { if (document.visibilityState === "visible") void reload().catch(() => {}); };
    window.addEventListener("storage", onStorage);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("storage", onStorage);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [session, reload]);

  const mutate = useCallback(async (operation: (client: WebBotClient, revision: number) => Promise<ThemeLibrary>) => {
    const activeSession = sessionRef.current;
    if (!activeSession || activeSession.previewOnly || activeSession.canManage === false) throw new Error("请登录正式账户后管理全局主题");
    if (!readyRef.current) throw new Error("全局主题库尚未加载成功，请重新加载后再保存");
    const generation = generationRef.current;
    try {
      const next = await operation(activeSession.client, libraryRef.current.revision);
      if (generation !== generationRef.current) throw new Error("账户已切换，请重新打开主题管理");
      validateLibrary(next);
      if (next.revision < libraryRef.current.revision) {
        throw new Error("主题已提交，随后主题库又有更新。请重新加载并核对当前版本");
      }
      return accept(next);
    } catch (failure) {
      if (generation === generationRef.current) setError(errorMessage(failure));
      throw failure;
    }
  }, [accept]);

  const createTheme = useCallback((input: CreateInput) => mutate((client, revision) => client.createUiTheme({ ...input, expectedRevision: input.expectedRevision ?? revision })), [mutate]);
  const updateTheme = useCallback((id: string, input: UpdateInput) => mutate((client, revision) => client.updateUiTheme(id, { ...input, expectedRevision: input.expectedRevision ?? revision })), [mutate]);
  const deleteTheme = useCallback((id: string) => mutate((client, revision) => client.deleteUiTheme(id, revision)), [mutate]);
  const selectTheme = useCallback(async (id: string) => {
    if (sessionRef.current?.previewOnly) {
      if (!libraryRef.current.themes.some((theme) => theme.id === id)) throw new Error("主题不存在");
      setLoginThemeId(id);
      try { localStorage.setItem(loginThemeKey(), id); } catch { /* Keep the selection for this page when storage is unavailable. */ }
      return libraryRef.current;
    }
    return mutate((client, revision) => client.selectUiTheme(id, revision));
  }, [mutate]);
  const openManager = useCallback(() => { if (sessionRef.current && !sessionRef.current.previewOnly && sessionRef.current.canManage !== false) setManagerOpen(true); }, []);
  const closeManager = useCallback(() => setManagerOpen(false), []);
  const canManage = Boolean(session && !session.previewOnly && session.canManage !== false);
  return { library, appearance, loading, error, canManage, canSelect: Boolean(session?.previewOnly || canManage), bindSession, reload, createTheme, updateTheme, deleteTheme, selectTheme, managerOpen, openManager, closeManager };
}

type AppearanceContextValue = ReturnType<typeof useAppearanceState>;
const AppearanceContext = createContext<AppearanceContextValue | null>(null);

export function useOptionalAppearance() { return useContext(AppearanceContext); }
export function useAppearance() {
  const context = useOptionalAppearance();
  if (!context) throw new Error("主题管理需要 AppearanceProvider");
  return context;
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const value = useAppearanceState();
  const dialogRef = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    if (!value.managerOpen) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.showModal();
    return () => previous?.focus();
  }, [value.managerOpen]);
  return <AppearanceContext.Provider value={value}>
    {children}
    {value.managerOpen && <dialog ref={dialogRef} className="theme-manager-overlay" aria-label="全局主题管理" onCancel={(event) => { event.preventDefault(); requestThemeManagerLeave(value.closeManager); }}
      onKeyDown={(event) => {
        event.stopPropagation();
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") event.preventDefault();
      }}>
      <Suspense fallback={<p className="p-6">正在加载主题管理…</p>}><ThemeManagerScreen onClose={value.closeManager} /></Suspense>
    </dialog>}
  </AppearanceContext.Provider>;
}
