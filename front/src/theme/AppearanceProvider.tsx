import { createContext, lazy, Suspense, useCallback, useContext, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { WebBotClient } from "../services/webBotClient";
import { applyResolvedAppearance } from "./appearanceRuntime";
import { BUILTIN_THEME, builtinLibrary, resolveAppearance } from "./resolveAppearance";
import type { ThemeCreateInput, ThemeLibrary, ThemeUpdateInput } from "./types";
import "./appearance.css";

const ThemeManagerScreen = lazy(() => import("../screens/ThemeManagerScreen").then((module) => ({ default: module.ThemeManagerScreen })));
type Account = { key: string; client: WebBotClient };
type CreateInput = Omit<ThemeCreateInput, "expectedRevision"> & { expectedRevision?: number };
type UpdateInput = Omit<ThemeUpdateInput, "expectedRevision"> & { expectedRevision?: number };

export function requestThemeManagerLeave(action: () => void) {
  const event = new CustomEvent("theme-manager-before-leave", { cancelable: true, detail: action });
  if (window.dispatchEvent(event)) action();
}

function errorMessage(error: unknown) { return error instanceof Error ? error.message : "主题操作失败，请重试"; }

function validateLibrary(library: ThemeLibrary): ThemeLibrary {
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

function cacheKey(account: Account) {
  return `web-ui-themes:${window.location.pathname}:${encodeURIComponent(account.key)}`;
}

function verifyOwner(library: ThemeLibrary, owner: Account) {
  if (library.accountId !== owner.key) throw new Error("登录账户已变化或主题响应缺少账户标识，请刷新页面后管理主题");
}

function useAppearanceState() {
  const accountRef = useRef<Account | null>(null);
  const generationRef = useRef(0);
  const reloadSequenceRef = useRef(0);
  const libraryRef = useRef<ThemeLibrary>(builtinLibrary());
  const [account, setAccount] = useState<Account | null>(null);
  const [library, setLibrary] = useState<ThemeLibrary>(libraryRef.current);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [managerOpen, setManagerOpen] = useState(false);
  const accept = useCallback((next: ThemeLibrary, owner: Account | null, cache = true) => {
    if (owner) verifyOwner(next, owner);
    const valid = validateLibrary(next);
    libraryRef.current = valid;
    setLibrary(valid);
    setError(valid.error || "");
    if (owner && cache && !valid.error) {
      try { localStorage.setItem(cacheKey(owner), JSON.stringify(valid)); } catch { /* In-memory operation remains available. */ }
    }
    return valid;
  }, []);

  const reload = useCallback(async () => {
    const owner = accountRef.current;
    if (!owner) return;
    const generation = generationRef.current;
    const requestSequence = ++reloadSequenceRef.current;
    const startedRevision = libraryRef.current.revision;
    setLoading(true);
    try {
      const next = await owner.client.listUiThemes();
      if (generation !== generationRef.current || requestSequence !== reloadSequenceRef.current) return;
      verifyOwner(next, owner);
      if (libraryRef.current.revision === startedRevision || next.revision >= libraryRef.current.revision) accept(next, owner);
    } catch (failure) {
      if (generation !== generationRef.current || requestSequence !== reloadSequenceRef.current) return;
      if (libraryRef.current.revision === startedRevision) {
        accept(builtinLibrary(), null, false);
        setError(errorMessage(failure));
      }
      throw failure;
    } finally {
      if (generation === generationRef.current && requestSequence === reloadSequenceRef.current) setLoading(false);
    }
  }, [accept]);

  const bindAccount = useCallback((next: Account | null) => {
    const previous = accountRef.current;
    if (previous?.key === next?.key && previous?.client === next?.client) return;
    generationRef.current += 1;
    accountRef.current = next;
    setAccount(next);
    setManagerOpen(false);
    const fallback = builtinLibrary();
    accept(fallback, null, false);
    applyResolvedAppearance(resolveAppearance(BUILTIN_THEME));
    if (!next) { setLoading(false); return; }
    next.client.bindThemeAccount?.(next.key);
    try {
      const raw = localStorage.getItem(cacheKey(next));
      if (raw) accept(validateLibrary(JSON.parse(raw)), next, false);
    } catch { /* The server remains authoritative if the cache is unavailable. */ }
    void reload().catch(() => {});
  }, [accept, reload]);

  useLayoutEffect(() => {
    const theme = library.themes.find((item) => item.id === library.selectedThemeId) || BUILTIN_THEME;
    applyResolvedAppearance(resolveAppearance(theme));
  }, [library]);

  useLayoutEffect(() => {
    if (!account) return;
    const onStorage = (event: StorageEvent) => {
      if (event.key === cacheKey(account)) void reload().catch(() => {});
    };
    const onVisibility = () => { if (document.visibilityState === "visible") void reload().catch(() => {}); };
    window.addEventListener("storage", onStorage);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("storage", onStorage);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [account, reload]);

  const mutate = useCallback(async (operation: (client: WebBotClient, revision: number) => Promise<ThemeLibrary>) => {
    const owner = accountRef.current;
    if (!owner) throw new Error("请登录正式账户后管理个人主题");
    const generation = generationRef.current;
    try {
      const next = await operation(owner.client, libraryRef.current.revision);
      if (generation !== generationRef.current) throw new Error("账户已切换，请重新打开主题管理");
      verifyOwner(next, owner);
      if (next.revision < libraryRef.current.revision) {
        throw new Error("主题已提交，随后主题库又有更新。请重新加载并核对当前版本");
      }
      return accept(next, owner);
    } catch (failure) {
      if (generation === generationRef.current) setError(errorMessage(failure));
      throw failure;
    }
  }, [accept]);

  const createTheme = useCallback((input: CreateInput) => mutate((client, revision) => client.createUiTheme({ ...input, expectedRevision: input.expectedRevision ?? revision })), [mutate]);
  const updateTheme = useCallback((id: string, input: UpdateInput) => mutate((client, revision) => client.updateUiTheme(id, { ...input, expectedRevision: input.expectedRevision ?? revision })), [mutate]);
  const deleteTheme = useCallback((id: string) => mutate((client, revision) => client.deleteUiTheme(id, revision)), [mutate]);
  const selectTheme = useCallback((id: string) => mutate((client, revision) => client.selectUiTheme(id, revision)), [mutate]);
  const openManager = useCallback(() => { if (accountRef.current) setManagerOpen(true); }, []);
  const closeManager = useCallback(() => setManagerOpen(false), []);
  const appearance = useMemo(() => resolveAppearance(library.themes.find((theme) => theme.id === library.selectedThemeId) || BUILTIN_THEME), [library]);
  return { library, appearance, loading, error, canManage: Boolean(account), bindAccount, reload, createTheme, updateTheme, deleteTheme, selectTheme, managerOpen, openManager, closeManager };
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
    {value.managerOpen && <dialog ref={dialogRef} className="theme-manager-overlay" aria-label="个人主题管理" onCancel={(event) => { event.preventDefault(); requestThemeManagerLeave(value.closeManager); }}
      onKeyDown={(event) => {
        event.stopPropagation();
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") event.preventDefault();
      }}>
      <Suspense fallback={<p className="p-6">正在加载主题管理…</p>}><ThemeManagerScreen onClose={value.closeManager} /></Suspense>
    </dialog>}
  </AppearanceContext.Provider>;
}
