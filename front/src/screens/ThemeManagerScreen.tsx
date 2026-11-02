import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useAppearance } from "../theme/AppearanceProvider";
import {
  BUILTIN_THEME,
  THEME_TOKENS,
  contrastRatio,
  MAX_THEME_ILLUSTRATION_UPLOAD_BYTES,
  normalizeColor,
  normalizeIllustrationUpload,
  normalizeIllustrations,
  resolveAppearance,
} from "../theme/resolveAppearance";
import {
  CHAT_BODY_FONT_FAMILY_OPTIONS,
  CHAT_BODY_FONT_SIZE_OPTIONS,
  CHAT_BODY_LINE_HEIGHT_OPTIONS,
  CHAT_BODY_PARAGRAPH_SPACING_OPTIONS,
  normalizeChatTypography,
} from "../theme/chatTypography";
import type { ChatTypography, ThemeIllustrationSurface, ThemeIllustrationUploadMime, ThemeIllustrations, UiTheme, ThemeLibrary } from "../theme/types";
import { downloadThemeDocument, portableTheme, readThemeFile } from "../theme/themeTransfer";
import { builtinIllustrationScene, illustrationSetIdForScene, ILLUSTRATION_TEMPLATES, THEME_ILLUSTRATION_OPTIONS, THEME_ILLUSTRATION_SURFACES } from "../theme/illustrationPresets";
import { ThemeIllustrationLayer } from "../theme/ThemeIllustrationLayer";
import { withPublicBase } from "../utils/publicBase";
import "../styles/theme-manager.css";

type Draft = {
  revision: number;
  original: UiTheme;
  theme: UiTheme;
  sourceId?: string;
  inputs: Record<string, string>;
};
type IllustrationPatch = Omit<Partial<ThemeIllustrations>, "surfaces" | "scenes"> & {
  surfaces?: Partial<ThemeIllustrations["surfaces"]>;
  scenes?: Partial<ThemeIllustrations["scenes"]>;
};

function cloneIllustrations(value: unknown): ThemeIllustrations {
  const normalized = normalizeIllustrations(value);
  return {
    ...normalized,
    surfaces: { ...normalized.surfaces },
    scenes: Object.fromEntries(
      THEME_ILLUSTRATION_SURFACES.map((surface) => [surface, {
        layers: normalized.scenes[surface].layers.map((layer) => ({ ...layer, asset: { ...layer.asset } })),
      }]),
    ) as ThemeIllustrations["scenes"],
  };
}
type Pane = "themes" | "editor" | "preview";
type LeaveAction =
  | { kind: "select"; id: string }
  | { kind: "create"; source: UiTheme; name: string }
  | { kind: "import"; file: File }
  | { kind: "cancel" }
  | { kind: "close" }
  | { kind: "external"; action: () => void };
type Confirmation =
  | { kind: "leave"; action: LeaveAction }
  | { kind: "delete" }
  | { kind: "reload" };

function draftFrom(theme: UiTheme, revision: number): Draft {
  const illustrations = cloneIllustrations(theme.appearance.illustrations);
  const copy = {
    ...theme,
    appearance: {
      ...theme.appearance,
      colors: {
        ...theme.appearance.colors,
        overrides: { ...theme.appearance.colors.overrides },
      },
      typography: normalizeChatTypography(theme.appearance.typography),
      illustrations,
    },
  };
  return {
    revision,
    original: copy,
    theme: { ...copy, appearance: { ...copy.appearance, colors: { ...copy.appearance.colors, overrides: { ...copy.appearance.colors.overrides } }, illustrations: cloneIllustrations(illustrations) } },
    inputs: {},
  };
}

function editableValue(theme: UiTheme) {
  return JSON.stringify([
    theme.name,
    theme.appearance.colors.scheme,
    Object.entries(theme.appearance.colors.overrides).sort(([a], [b]) =>
      a.localeCompare(b),
    ),
    normalizeChatTypography(theme.appearance.typography),
    normalizeIllustrations(theme.appearance.illustrations),
  ]);
}

function initialTheme(library: ThemeLibrary) {
  return (
    library.themes.find((theme) => theme.id === library.selectedThemeId) ||
    library.themes[0] ||
    BUILTIN_THEME
  );
}

function failureMessage(error: unknown) {
  const status =
    error && typeof error === "object"
      ? (error as { status?: number; statusCode?: number }).status ||
        (error as { statusCode?: number }).statusCode
      : undefined;
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : "操作未完成，请稍后重试。";
  return status === 409 || /409|conflict|版本冲突/i.test(message)
    ? "主题库已在其他页面更新。草稿已保留，请重新加载主题库，核对后再次保存。"
    : `操作失败，草稿已保留。${message}`;
}

function ConfirmPanel({
  title,
  children,
  onDismiss,
  busy,
}: {
  title: string;
  children: ReactNode;
  onDismiss: () => void;
  busy: boolean;
}) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    (
      panel.current?.querySelector<HTMLButtonElement>(
        "button:not(:disabled)",
      ) || panel.current
    )?.focus();
    return () => {
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <div className="theme-manager-dialog-backdrop">
      <div
        ref={panel}
        className="theme-manager-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            if (!busy) onDismiss();
          }
          if (event.key === "Tab") {
            const controls = [
              ...(panel.current?.querySelectorAll<HTMLButtonElement>(
                "button:not(:disabled)",
              ) || []),
            ];
            const first = controls[0];
            const last = controls.at(-1);
            if (!first) {
              event.preventDefault();
              return;
            }
            if (
              !controls.includes(document.activeElement as HTMLButtonElement)
            ) {
              event.preventDefault();
              (event.shiftKey ? last : first)?.focus();
              return;
            }
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last?.focus();
            }
            if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first.focus();
            }
          }
        }}
      >
        <h2 id={titleId}>{title}</h2>
        {children}
      </div>
    </div>
  );
}

function ThemePreview({
  appearance,
}: {
  appearance: ReturnType<typeof resolveAppearance>;
}) {
  const terminalTokens = THEME_TOKENS.filter((token) => token.terminal);
  const terminalColors = Object.fromEntries(
    terminalTokens.map((token) => [
      token.terminal,
      appearance.colors[token.key],
    ]),
  );
  const ansiTokens = terminalTokens.filter(
    (token) =>
      ![
        "background",
        "foreground",
        "cursor",
        "cursorAccent",
        "selectionBackground",
        "selectionInactiveBackground",
        "selectionForeground",
      ].includes(token.terminal!),
  );
  return (
    <div
      className="theme-preview theme-illustration-host"
      data-testid="theme-local-preview"
      data-style-profile="paper"
      data-motion-profile="paper"
      data-color-scheme={appearance.scheme}
      style={
        {
          "--workbench-titlebar-bg": "var(--surface-strong, var(--surface))",
          "--workbench-sidebar-bg": "var(--surface)",
          "--chat-user-bg": "var(--surface-muted)",
          "--input-bg": "var(--surface)",
          "--editor-bg": "var(--surface)",
          "--editor-text": "var(--text)",
          "--editor-syntax-keyword": "var(--accent)",
          "--editor-syntax-string": "var(--text)",
          "--terminal-background": "var(--surface)",
          "--terminal-foreground": "var(--text)",
          "--terminal-cursor": "var(--accent)",
          "--file-tree-git-ignored": "var(--muted)",
          "--focus-ring": "var(--accent)",
          "--diagram-border": "var(--diagram-primary-border, var(--accent))",
          "--diagram-node-bg": "var(--diagram-primary, var(--surface-muted))",
          "--diagram-text": "var(--text)",
          "--diagram-line": "var(--muted)",
          ...appearance.cssVariables,
          colorScheme: appearance.scheme,
        } as CSSProperties
      }
    >
      <ThemeIllustrationLayer surface="workbench" appearance={appearance} />
      <div className="theme-preview-titlebar theme-illustration-host theme-illustration-content">
        <span>工作台</span>
        <span>示例项目 · 已就绪</span>
      </div>
      <div className="theme-preview-controls theme-illustration-content">
        <button type="button" className="theme-preview-primary">
          主要按钮
        </button>
        <button type="button">普通按钮</button>
        <button type="button" disabled>
          禁用
        </button>
        <span className="theme-preview-selected">选中</span>
        <button type="button" className="theme-preview-focus">
          焦点
        </button>
      </div>
      <div className="theme-preview-files theme-illustration-content" aria-label="文件树示例">
        <div>⌄ 示例项目</div>
        <div className="theme-preview-file-added">
          <span>＋ 新建说明.md</span>
          <span>新增</span>
        </div>
        <div className="theme-preview-file-modified">
          <span>◇ 工作台.tsx</span>
          <span>修改</span>
        </div>
        <div className="theme-preview-file-ignored">
          <span>· 本地缓存</span>
          <span>忽略</span>
        </div>
      </div>
      <div className="theme-preview-chat theme-illustration-host theme-illustration-content">
        <div className="theme-preview-user">
          <small>你 · 现在</small>
          <p>请为我的工作台调一套配色。</p>
        </div>
        <div className="theme-preview-assistant">
          <small>助手</small>
          <p>可以先看看正文、按钮和代码是否清晰。</p>
          <blockquote>舒适的对比度有助于持续阅读。</blockquote>
        </div>
        <pre className="theme-preview-code">
          <code>
            <span>const</span> theme = <em>"新主题"</em>;<br />
            <span>return</span> theme;
          </code>
        </pre>
        <div className="theme-preview-composer">
          <span>输入消息…</span>
          <button type="button" className="theme-preview-primary">
            发送
          </button>
        </div>
      </div>
      <div className="theme-preview-bottom theme-illustration-content">
        <div className="theme-preview-menu" aria-label="菜单示例">
          <strong>文件操作</strong>
          <span>打开文件</span>
          <span className="theme-preview-selected">复制路径</span>
        </div>
        <div className="theme-preview-diagram" aria-label="图表示例">
          <span>准备</span>
          <i aria-hidden="true">→</i>
          <span>完成</span>
        </div>
      </div>
      <div
        className="theme-preview-terminal"
        aria-label="终端色板示例"
        style={{
          backgroundColor: terminalColors.background,
          color: terminalColors.foreground,
        }}
      >
        <small>终端示例</small>
        <p>
          ❯ 配色预览已就绪
          <span
            className="theme-preview-cursor"
            style={{ color: terminalColors.cursor }}
          >
            ▌
          </span>
        </p>
        <div className="theme-preview-palette">
          {ansiTokens.map((token) => (
            <span
              key={token.key}
              title={token.label}
              aria-label={token.label}
              style={{ backgroundColor: appearance.colors[token.key] }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function ThemeManagerScreen({ onClose }: { onClose?: () => void }) {
  const {
    library,
    appearance,
    loading,
    error: providerError,
    canManage,
    reload,
    createTheme,
    importThemes,
    uploadThemeAsset,
    updateTheme,
    deleteTheme,
    selectTheme,
  } = useAppearance();
  const [draft, setDraft] = useState<Draft>(() =>
    draftFrom(initialTheme(library), library.revision),
  );
  const [preview, setPreview] = useState(() => resolveAppearance(draft.theme));
  const [activePane, setActivePane] = useState<Pane>("editor");
  const [group, setGroup] = useState("");
  const [search, setSearch] = useState("");
  const [operationBusy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const initialized = useRef(!loading);
  const operationInFlight = useRef(false);
  const reloadRequested = useRef<"keep" | "discard" | null>(null);
  const busy = operationBusy || Boolean(reloadRequested.current);
  const nameInput = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const groups = useMemo(
    () => [...new Set(THEME_TOKENS.map((token) => token.group))],
    [],
  );
  const invalidTokens = THEME_TOKENS.filter(
    (token) =>
      draft.inputs[token.key] !== undefined &&
      !normalizeColor(draft.inputs[token.key], token.allowAlpha),
  );
  const dirty =
    Boolean(draft.sourceId) ||
    editableValue(draft.theme) !== editableValue(draft.original) ||
    invalidTokens.length > 0;
  const presetsOnly = library.themes.length > 0 && library.themes.every((theme) => theme.readonly);
  const editable = canManage && !presetsOnly && !draft.theme.readonly;
  const valid = Boolean(draft.theme.name.trim()) && invalidTokens.length === 0;
  const typography = normalizeChatTypography(draft.theme.appearance.typography);
  const illustrations = normalizeIllustrations(draft.theme.appearance.illustrations);
  const visibleTokens = THEME_TOKENS.filter(
    (token) =>
      (!group || token.group === group) &&
      `${token.label} ${token.group} ${token.description} ${token.key}`
        .toLocaleLowerCase()
        .includes(search.trim().toLocaleLowerCase()),
  );
  const contrastWarnings = THEME_TOKENS.flatMap((token) => {
    if (!token.contrastAgainst) return [];
    const backgrounds = Array.isArray(token.contrastAgainst)
      ? token.contrastAgainst
      : [token.contrastAgainst];
    return backgrounds.flatMap((key) => {
      const foreground = preview.colors[token.key];
      const background = preview.colors[key];
      if (!foreground || !background) return [];
      const ratio = contrastRatio(foreground, background, preview.colors.canvas);
      const target = token.minContrast ?? 4.5;
      return ratio < target
        ? [
            {
              key: `${token.key}:${key}`,
              label: token.label,
              background:
                THEME_TOKENS.find((item) => item.key === key)?.label || key,
              ratio,
              target,
            },
          ]
        : [];
    });
  });

  useEffect(() => {
    const frame = requestAnimationFrame(() =>
      setPreview(resolveAppearance(draft.theme)),
    );
    return () => cancelAnimationFrame(frame);
  }, [draft.theme]);

  useEffect(() => {
    if (loading || dirty) return;
    const current = initialized.current
      ? library.themes.find((theme) => theme.id === draft.original.id) ||
        initialTheme(library)
      : initialTheme(library);
    initialized.current = true;
    const next = draftFrom(current, library.revision);
    if (
      editableValue(next.theme) !== editableValue(draft.original) ||
      draft.revision !== library.revision
    )
      setDraft(next);
  }, [library, loading, dirty, draft.original, draft.revision]);

  useEffect(() => {
    const beforeLeave = (event: Event) => {
      if (!dirty && !operationInFlight.current && !reloadRequested.current)
        return;
      const action = (event as CustomEvent<() => void>).detail;
      if (typeof action !== "function") return;
      event.preventDefault();
      setConfirmation({ kind: "leave", action: { kind: "external", action } });
    };
    window.addEventListener("theme-manager-before-leave", beforeLeave);
    return () =>
      window.removeEventListener("theme-manager-before-leave", beforeLeave);
  }, [dirty]);

  useEffect(() => {
    if (!reloadRequested.current || operationBusy || loading) return;
    const choice = reloadRequested.current;
    reloadRequested.current = null;
    if (providerError || library.error) {
      setError(providerError || library.error || "主题库重载失败。");
      return;
    }
    if (choice === "discard") {
      setDraft((current) =>
        draftFrom(
          library.themes.find(
            (theme) => theme.id === (current.sourceId || current.original.id),
          ) || initialTheme(library),
          library.revision,
        ),
      );
    } else {
      setDraft((current) => ({ ...current, revision: library.revision }));
    }
    setNotice(
      dirty && choice === "keep"
        ? "主题库已重新加载，草稿已保留。下一次保存将以最新版本提交，覆盖该主题的已保存配色。"
        : "主题库已重新加载。",
    );
  }, [operationBusy, loading, library, providerError, dirty]);

  useEffect(() => {
    if (!dirty && !busy) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [dirty, busy]);

  function performAction(action: LeaveAction, currentLibrary = library) {
    setConfirmation(null);
    setError("");
    setNotice("");
    if (action.kind === "close") {
      onClose?.();
      return;
    }
    if (action.kind === "external") {
      action.action();
      return;
    }
    if (action.kind === "import") {
      void importFile(action.file, currentLibrary);
      return;
    }
    if (action.kind === "create") {
      const source =
        currentLibrary.themes.find((theme) => theme.id === action.source.id) ||
        action.source;
      const next = draftFrom(source, currentLibrary.revision);
      next.sourceId = action.source.id;
      next.theme = { ...next.theme, name: action.name, readonly: false };
      setDraft(next);
      setActivePane("editor");
      return;
    }
    const id =
      action.kind === "select"
        ? action.id
        : draft.sourceId || draft.original.id;
    setDraft(
      draftFrom(
        currentLibrary.themes.find((theme) => theme.id === id) ||
          initialTheme(currentLibrary),
        currentLibrary.revision,
      ),
    );
    if (action.kind === "select") setActivePane("editor");
  }

  function requestAction(action: LeaveAction) {
    if (dirty || operationInFlight.current || reloadRequested.current)
      setConfirmation({ kind: "leave", action });
    else performAction(action);
  }

  function changeColor(key: string, raw: string) {
    const token = THEME_TOKENS.find((item) => item.key === key);
    if (!editable || !token || busy) return;
    const normalized = normalizeColor(raw, token.allowAlpha);
    setNotice("");
    setDraft((current) => ({
      ...current,
      inputs: { ...current.inputs, [key]: raw },
      theme: normalized
        ? {
            ...current.theme,
            appearance: {
              ...current.theme.appearance,
              colors: {
                ...current.theme.appearance.colors,
                overrides: {
                  ...current.theme.appearance.colors.overrides,
                  [key]: normalized,
                },
              },
            },
          }
        : current.theme,
    }));
  }

  function resetColor(key: string) {
    setNotice("");
    setDraft((current) => {
      const inputs = { ...current.inputs };
      const overrides = { ...current.theme.appearance.colors.overrides };
      delete inputs[key];
      delete overrides[key];
      return {
        ...current,
        inputs,
        theme: {
          ...current.theme,
          appearance: {
            ...current.theme.appearance,
            colors: { ...current.theme.appearance.colors, overrides },
          },
        },
      };
    });
  }

  function changeTypography<Key extends keyof ChatTypography>(key: Key, value: ChatTypography[Key]) {
    if (!editable || busy) return;
    setNotice("");
    setDraft((current) => ({
      ...current,
      theme: {
        ...current.theme,
        appearance: {
          ...current.theme.appearance,
          typography: {
            ...normalizeChatTypography(current.theme.appearance.typography),
            [key]: value,
          },
        },
      },
    }));
  }

  function changeIllustrations(patch: IllustrationPatch) {
    if (!editable || busy) return;
    setNotice("");
    setDraft((current) => {
      const currentIllustrations = normalizeIllustrations(current.theme.appearance.illustrations);
      const nextIllustrations: ThemeIllustrations = {
        ...currentIllustrations,
        ...patch,
        surfaces: {
          ...currentIllustrations.surfaces,
          ...(patch.surfaces || {}),
        },
        scenes: {
          ...currentIllustrations.scenes,
          ...(patch.scenes || {}),
        },
      };
      return {
        ...current,
        theme: {
          ...current.theme,
          appearance: {
            ...current.theme.appearance,
            illustrations: nextIllustrations,
          },
        },
      };
    });
  }

  function applyIllustrationTemplate(template: (typeof ILLUSTRATION_TEMPLATES)[number]) {
    if (!editable || busy) return;
    setNotice("");
    setDraft((current) => ({
      ...current,
      inputs: {
        ...current.inputs,
        ...template.colors,
      },
      theme: {
        ...current.theme,
        appearance: {
          ...current.theme.appearance,
          colors: {
            ...current.theme.appearance.colors,
            overrides: {
              ...current.theme.appearance.colors.overrides,
              ...template.colors,
            },
          },
          illustrations: {
            opacity: 0.12,
            surfaces: {
              workbench: true,
              adminCenter: true,
              agentManager: true,
            },
            scenes: Object.fromEntries(
              THEME_ILLUSTRATION_SURFACES.map((surface) => [surface, builtinIllustrationScene(template.id, surface)]),
            ) as ThemeIllustrations["scenes"],
          },
        },
      },
    }));
  }

  async function uploadIllustration(surface: ThemeIllustrationSurface, file: File | undefined) {
    if (!editable || busy || !file) return;
    const mimeType = file.type as ThemeIllustrationUploadMime;
    if (!(["image/png", "image/jpeg", "image/webp"] as const).includes(mimeType)) {
      setError("上传插画只支持 PNG、JPEG 或 WebP 文件。");
      return;
    }
    if (file.size > MAX_THEME_ILLUSTRATION_UPLOAD_BYTES) {
      setError("上传插画不能超过 4 MiB。");
      return;
    }
    try {
      const asset = await uploadThemeAsset(file);
      changeIllustrations({ scenes: { [surface]: {
        layers: [{
          id: `${surface}-uploaded`,
          asset,
          anchor: "center",
          width: 100,
          height: 100,
          objectPosition: "50% 50%",
          enabled: true,
        }],
      } } });
      setError("");
      setNotice("已上传场景插画，保存主题后生效。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "上传插画无效。");
    }
  }

  async function save(activate: boolean) {
    if (
      !editable ||
      !valid ||
      operationInFlight.current ||
      reloadRequested.current
    )
      return null;
    operationInFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const input = {
        schemaVersion: 1 as const,
        expectedRevision: draft.revision,
        name: draft.theme.name.trim(),
        appearance: draft.theme.appearance,
        activate,
      };
      const result = draft.sourceId
        ? await createTheme({ ...input, sourceId: draft.sourceId })
        : await updateTheme(draft.theme.id, input);
      const previousIds = new Set(library.themes.map((theme) => theme.id));
      const saved = result.themes.find((theme) =>
        draft.sourceId
          ? !previousIds.has(theme.id) && !theme.readonly
          : theme.id === draft.theme.id,
      );
      if (!saved) throw new Error("未收到保存后的主题，请重新加载主题库确认。");
      setDraft(draftFrom(saved, result.revision));
      setNotice(activate ? "主题已保存并应用。" : "主题已保存。");
      return result;
    } catch (cause) {
      setError(failureMessage(cause));
      return null;
    } finally {
      operationInFlight.current = false;
      setBusy(false);
    }
  }

  async function importFile(file: File, currentLibrary: ThemeLibrary) {
    if (!canManage || operationInFlight.current || reloadRequested.current) return;
    operationInFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const importedFile = await readThemeFile(file);
      const isPackage = Boolean(importedFile && typeof importedFile === "object" && "document" in importedFile && "assets" in importedFile);
      const document = isPackage ? (importedFile as { document: unknown }).document : importedFile;
      const assets = isPackage ? (importedFile as { assets: Parameters<typeof importThemes>[2] }).assets : undefined;
      const result = await importThemes(document, currentLibrary.revision, assets);
      const previousIds = new Set(currentLibrary.themes.map((theme) => theme.id));
      const imported = result.themes.filter((theme) => !previousIds.has(theme.id));
      if (!imported.length) throw new Error("未收到导入后的主题，请重新加载主题库确认。");
      setDraft(draftFrom(imported[0], result.revision));
      setActivePane("editor");
      setNotice(`已导入 ${imported.length} 个主题，可编辑或应用。当前应用主题保持不变。`);
    } catch (cause) {
      setError(failureMessage(cause));
    } finally {
      operationInFlight.current = false;
      setBusy(false);
    }
  }

  async function exportThemes(pack: boolean) {
    if (busy || loading || library.error || (!pack && dirty)) return;
    setError("");
    try {
      const themes = pack ? library.themes : [draft.original];
      const assets = new Map<string, { assetId: string; mimeType: string; data: ArrayBuffer }>();
      for (const theme of themes) {
        const illustrations = normalizeIllustrations(theme.appearance.illustrations);
        for (const scene of Object.values(illustrations.scenes)) {
          for (const layer of scene.layers) {
            const asset = layer.asset;
            if (asset.kind !== "uploaded" || assets.has(asset.assetId)) continue;
            const response = await fetch(withPublicBase(`/api/ui/theme-assets/${encodeURIComponent(asset.assetId)}`), { credentials: "same-origin" });
            if (!response.ok) throw new Error("无法读取主题插画资源，请刷新主题库后重试。");
            assets.set(asset.assetId, { assetId: asset.assetId, mimeType: asset.mimeType, data: await response.arrayBuffer() });
          }
        }
      }
      await downloadThemeDocument(
        pack ? { schemaVersion: 1, themes: themes.map(portableTheme) } : portableTheme(draft.original),
        pack ? "pack" : draft.original.name,
        [...assets.values()],
      );
      setNotice(pack ? `已导出主题包，包含 ${library.themes.length} 个已保存主题。` : "已导出当前主题。");
    } catch (cause) {
      setError(failureMessage(cause));
    }
  }

  async function applyTheme() {
    if (!canManage || dirty || operationInFlight.current) return;
    operationInFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await selectTheme(draft.theme.id);
      setNotice("主题已应用。");
    } catch (cause) {
      setError(failureMessage(cause));
    } finally {
      operationInFlight.current = false;
      setBusy(false);
    }
  }

  async function removeTheme() {
    if (!editable || draft.sourceId || operationInFlight.current) return;
    operationInFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await deleteTheme(draft.theme.id);
      setDraft(draftFrom(initialTheme(result), result.revision));
      setConfirmation((current) =>
        current?.kind === "leave" ? current : null,
      );
      setNotice("主题已删除。");
    } catch (cause) {
      setError(failureMessage(cause));
    } finally {
      operationInFlight.current = false;
      setBusy(false);
    }
  }

  async function reloadLibrary(choice: "keep" | "discard") {
    if (operationInFlight.current) return;
    operationInFlight.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    setConfirmation(null);
    reloadRequested.current = choice;
    try {
      await reload();
    } catch (cause) {
      reloadRequested.current = null;
      setError(failureMessage(cause));
    } finally {
      operationInFlight.current = false;
      setBusy(false);
    }
  }

  const currentError = error || providerError || library.error;
  return (
    <section
      className="theme-manager"
      aria-label="全局主题管理"
      aria-busy={busy || loading}
      data-theme-manager-dirty={dirty ? "true" : "false"}
      onKeyDown={(event) => {
        if (event.key === "Escape" && onClose && !confirmation) {
          event.preventDefault();
          event.stopPropagation();
          requestAction({ kind: "close" });
        }
      }}
    >
      <header className="theme-manager-header">
        <div>
          <h1>主题管理</h1>
          <p>主题随应用版本发布，所有账户只能选择预置主题</p>
        </div>
        <div className="theme-manager-header-actions">
          <span>
            当前应用：
            {library.themes.find((theme) => theme.id === appearance.themeId)
              ?.name || "钢铁核心"}
          </span>
          {onClose && (
            <button
              type="button"
              disabled={busy}
              onClick={() => requestAction({ kind: "close" })}
            >
              关闭主题管理
            </button>
          )}
        </div>
      </header>
      {!canManage && !loading && (
        <p className="theme-manager-banner">
          登录正式账户后，可以保存和管理全局主题。
        </p>
      )}
      {loading && (
        <p className="theme-manager-banner" role="status">
          正在加载主题库…
        </p>
      )}
      {currentError && (
        <div className="theme-manager-error" role="alert">
          <span>{currentError}</span>
          <button
            type="button"
            disabled={busy || loading}
            onClick={() =>
              dirty
                ? setConfirmation({ kind: "reload" })
                : void reloadLibrary("keep")
            }
          >
            重新加载主题库
          </button>
        </div>
      )}
      {notice && (
        <p className="theme-manager-banner" role="status">
          {notice}
        </p>
      )}
      <nav className="theme-manager-sections" aria-label="主题管理分区">
        {(
          [
            ["themes", "主题列表"],
            ["editor", "主题详情"],
            ["preview", "局部预览"],
          ] as const
        ).map(([id, label]) => (
          <button
            type="button"
            key={id}
            aria-pressed={activePane === id}
            onClick={() => setActivePane(id)}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="theme-manager-columns" data-active-pane={activePane}>
        <aside
          className="theme-manager-library"
          data-pane="themes"
          aria-label="主题列表"
        >
          <div className="theme-manager-panel-title">
            <h2>全局主题</h2>
            <span>
              {library.themes.length} 个预置
            </span>
          </div>
          <div className="theme-manager-transfer">
              <button type="button" disabled={busy || loading || Boolean(library.error)} onClick={() => void exportThemes(true)}>
              导出主题包
            </button>
            <p className="theme-manager-hint">预置主题由应用版本统一提供，管理员也不能编辑、导入或删除。</p>
          </div>
          {(["preset"] as const).map((group) => {
            const themes = library.themes;
            return (
            <div className="theme-manager-theme-group" key={group}>
              <h3>预置主题</h3>
              {themes.map((theme) => (
                  <button
                    className="theme-manager-theme"
                    type="button"
                    key={theme.id}
                    aria-pressed={
                      !draft.sourceId && draft.theme.id === theme.id
                    }
                    disabled={busy || loading}
                    onClick={() => {
                      if (draft.sourceId || draft.theme.id !== theme.id)
                        requestAction({ kind: "select", id: theme.id });
                      else setActivePane("editor");
                    }}
                  >
                    <strong>{theme.name}</strong>
                    <span>
                      {theme.appearance.colors.scheme === "dark"
                        ? "深色"
                        : "浅色"}
                      {theme.id === BUILTIN_THEME.id ? " · 默认主题" : " · 只读"}
                      {theme.id === library.selectedThemeId
                        ? " · 当前应用"
                        : ""}
                    </span>
                  </button>
                ))}
            </div>
            );
          })}
          {draft.sourceId && (
            <div className="theme-manager-draft-item">
              <strong>{draft.theme.name || "未命名主题"}</strong>
              <span>新主题 · 待保存</span>
            </div>
          )}
        </aside>
        <section
          className="theme-manager-editor"
          data-pane="editor"
          aria-label="主题详情"
        >
          <div className="theme-manager-panel-title">
            <h2>查看主题</h2>
            <span>{dirty ? "有未保存的更改" : "预置主题"}</span>
          </div>
          <div className="theme-manager-export">
            <button type="button" disabled={dirty || busy || loading || Boolean(library.error)} onClick={() => void exportThemes(false)}>
              导出当前主题
            </button>
            {dirty && <small>保存草稿后可导出当前主题。</small>}
          </div>
          {draft.theme.readonly && (
            <div className="theme-manager-readonly">
              <span>该主题是随应用发布的预置主题，内容由版本固定。</span>
            </div>
          )}
          <fieldset
            disabled={!editable || busy || loading}
            className="theme-manager-fields"
          >
            <div className="theme-manager-identity">
              <label htmlFor={`${inputId}-name`}>主题名称</label>
              <div className="theme-manager-name-row">
                <input
                  ref={nameInput}
                  id={`${inputId}-name`}
                  value={draft.theme.name}
                  aria-invalid={!draft.theme.name.trim()}
                  onChange={(event) => {
                    setNotice("");
                    setDraft({
                      ...draft,
                      theme: { ...draft.theme, name: event.target.value },
                    });
                  }}
                />
                <button
                  type="button"
                  onClick={() => {
                    nameInput.current?.focus();
                    nameInput.current?.select();
                  }}
                >
                  重命名
                </button>
              </div>
              {!draft.theme.name.trim() && (
                <small className="theme-manager-field-error">
                  请填写主题名称。
                </small>
              )}
              <label htmlFor={`${inputId}-scheme`}>明暗模式</label>
              <select
                id={`${inputId}-scheme`}
                value={draft.theme.appearance.colors.scheme}
                onChange={(event) => {
                  setNotice("");
                  setDraft({
                    ...draft,
                    theme: {
                      ...draft.theme,
                      appearance: {
                        ...draft.theme.appearance,
                        colors: {
                          ...draft.theme.appearance.colors,
                          scheme: event.target.value as "light" | "dark",
                        },
                      },
                    },
                  });
                }}
              >
                <option value="light">浅色</option>
                <option value="dark">深色</option>
              </select>
              <small>用于浏览器控件、编辑器和终端适配；颜色可逐项调整。</small>
              <div className="theme-manager-typography">
                <strong>聊天正文</strong>
                <label htmlFor={`${inputId}-chat-font-family`}>聊天正文字体</label>
                <select
                  id={`${inputId}-chat-font-family`}
                  aria-label="聊天正文字体"
                  value={typography.chatBodyFontFamily}
                  onChange={(event) => changeTypography("chatBodyFontFamily", event.target.value as ChatTypography["chatBodyFontFamily"])}
                >
                  {CHAT_BODY_FONT_FAMILY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                <label htmlFor={`${inputId}-chat-line-height`}>聊天行间距</label>
                <select
                  id={`${inputId}-chat-line-height`}
                  aria-label="聊天行间距"
                  value={typography.chatBodyLineHeight}
                  onChange={(event) => changeTypography("chatBodyLineHeight", event.target.value as ChatTypography["chatBodyLineHeight"])}
                >
                  {CHAT_BODY_LINE_HEIGHT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                <label htmlFor={`${inputId}-chat-font-size`}>聊天正文字号</label>
                <select
                  id={`${inputId}-chat-font-size`}
                  aria-label="聊天正文字号"
                  value={typography.chatBodyFontSize}
                  onChange={(event) => changeTypography("chatBodyFontSize", event.target.value as ChatTypography["chatBodyFontSize"])}
                >
                  {CHAT_BODY_FONT_SIZE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                <label htmlFor={`${inputId}-chat-paragraph-spacing`}>聊天段间距</label>
                <select
                  id={`${inputId}-chat-paragraph-spacing`}
                  aria-label="聊天段间距"
                  value={typography.chatBodyParagraphSpacing}
                  onChange={(event) => changeTypography("chatBodyParagraphSpacing", event.target.value as ChatTypography["chatBodyParagraphSpacing"])}
                >
                  {CHAT_BODY_PARAGRAPH_SPACING_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </div>
              <div className="theme-manager-illustrations">
                <div className="theme-manager-illustration-heading">
                  <strong>界面插画</strong>
                  <small>三个场景分别使用独立资源，装饰层不参与布局和交互。</small>
                </div>
                <label className="theme-manager-alpha">
                  插画透明度
                  <input
                    type="range"
                    aria-label="插画透明度"
                    min="0"
                    max="0.25"
                    step="0.01"
                    value={illustrations.opacity}
                    onChange={(event) => changeIllustrations({ opacity: Number(event.target.value) })}
                  />
                  <output>{Math.round(illustrations.opacity * 100)}%</output>
                </label>
                <div className="theme-manager-scene-grid">
                  {([
                    ["workbench", "主工作台插画", "编辑器、聊天区、终端和工作区留白"],
                    ["adminCenter", "管理中心插画", "管理页背景和顶部构图"],
                    ["agentManager", "智能体管理插画", "智能体列表、顶部横幅和详情区域"],
                  ] as const).map(([surface, label, description]) => {
                    const scene = illustrations.scenes[surface];
                    const asset = scene.layers[0]?.asset;
                    const selectedGroup = illustrationSetIdForScene(scene, surface);
                    const resource = preview.illustrations.resources[surface];
                    return (
                      <article className="theme-manager-scene-card" key={surface}>
                        <div className="theme-manager-scene-card-header">
                          <div>
                            <strong>{label}</strong>
                            <small>{description}</small>
                          </div>
                          <label>
                            <input
                              type="checkbox"
                              aria-label={`启用${label}`}
                              checked={illustrations.surfaces[surface]}
                              onChange={(event) => changeIllustrations({ surfaces: { [surface]: event.target.checked } })}
                            />
                            启用
                          </label>
                        </div>
                        <div className="theme-manager-scene-preview" style={{ objectPosition: surface === "workbench" ? "50% 50%" : "50% 35%" }}>
                          <img src={resource} alt="" aria-hidden="true" />
                        </div>
                        <div className="theme-manager-scene-meta">
                          <span>{asset?.width && asset.height ? `${asset.width} × ${asset.height}` : "等待资源信息"}</span>
                          <span>{scene.layers.length} 个图层 · {asset?.kind === "builtin" ? "内置资源" : "已上传资源"}</span>
                        </div>
                        <label htmlFor={`${inputId}-${surface}-set`}>内置插画组</label>
                        <select
                          id={`${inputId}-${surface}-set`}
                          aria-label={`${label}内置插画组`}
                          value={selectedGroup}
                          onChange={(event) => changeIllustrations({ scenes: { [surface]: builtinIllustrationScene(event.target.value as typeof ILLUSTRATION_TEMPLATES[number]["id"], surface) } })}
                        >
                          {selectedGroup === "" && <option value="" disabled>当前上传资源</option>}
                          {THEME_ILLUSTRATION_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                        </select>
                        <div className="theme-manager-scene-actions">
                          <label className="theme-manager-upload-button">
                            上传图片
                            <input
                              type="file"
                              aria-label={`上传${label}`}
                              accept="image/png,image/jpeg,image/webp"
                              onChange={(event) => {
                                void uploadIllustration(surface, event.target.files?.[0]);
                                event.currentTarget.value = "";
                              }}
                            />
                          </label>
                          <button type="button" onClick={() => changeIllustrations({ scenes: { [surface]: builtinIllustrationScene("none", surface) } })}>恢复默认资源</button>
                        </div>
                        <small>推荐 1600 × 900；预览会按场景裁剪 object-position。</small>
                      </article>
                    );
                  })}
                </div>
                <div className="theme-manager-illustration-templates" aria-label="插画模板">
                  {ILLUSTRATION_TEMPLATES.map((template) => (
                    <button
                      type="button"
                      key={template.id}
                      aria-label={`使用${template.label}模板`}
                      onClick={() => applyIllustrationTemplate(template)}
                    >
                      {template.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </fieldset>
          <div className="theme-manager-filters">
            <label htmlFor={`${inputId}-search`}>搜索颜色</label>
            <input
              id={`${inputId}-search`}
              type="search"
              placeholder="名称、用途或分组"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <label htmlFor={`${inputId}-group`}>颜色分组</label>
            <select
              id={`${inputId}-group`}
              value={group}
              onChange={(event) => setGroup(event.target.value)}
            >
              <option value="">全部分组</option>
              {groups.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
          <div className="theme-manager-color-heading">
            <span>{visibleTokens.length} 项颜色</span>
            <button
              type="button"
              disabled={!editable || busy || loading}
              onClick={() => {
                setNotice("");
                setDraft({
                  ...draft,
                  inputs: {},
                  theme: {
                    ...draft.theme,
                    appearance: {
                      ...draft.theme.appearance,
                      colors: {
                        scheme: BUILTIN_THEME.appearance.colors.scheme,
                        overrides: {},
                      },
                      illustrations: normalizeIllustrations(draft.theme.appearance.illustrations),
                    },
                  },
                });
              }}
            >
              整份恢复纸感配色
            </button>
          </div>
          <fieldset
            disabled={!editable || busy || loading}
            className="theme-manager-fields theme-manager-colors"
          >
            {visibleTokens.map((token) => {
              const value =
                draft.theme.appearance.colors.overrides[token.key] ||
                preview.colors[token.key] ||
                token.default;
              const normalized = normalizeColor(value, true) || token.default;
              const input = draft.inputs[token.key] ?? value;
              const invalid =
                draft.inputs[token.key] !== undefined &&
                !normalizeColor(input, token.allowAlpha);
              const overridden = Object.hasOwn(
                draft.theme.appearance.colors.overrides,
                token.key,
              );
              const tokenId = `${inputId}-${token.key}`;
              const alpha = parseInt(normalized.slice(7, 9) || "ff", 16);
              return (
                <div className="theme-manager-color" key={token.key}>
                  <div className="theme-manager-color-label">
                    <label htmlFor={`${tokenId}-hex`}>{token.label}</label>
                    <span>
                      {overridden
                        ? "已覆盖"
                        : token.derive
                          ? "跟随基础色"
                          : "默认"}
                    </span>
                  </div>
                  <p id={`${tokenId}-description`}>{token.description}</p>
                  <div className="theme-manager-color-inputs">
                    <input
                      type="color"
                      aria-label={`${token.label} 颜色选择器`}
                      value={normalized.slice(0, 7)}
                      onChange={(event) =>
                        changeColor(
                          token.key,
                          `${event.target.value}${token.allowAlpha ? normalized.slice(7, 9) || "ff" : "ff"}`,
                        )
                      }
                    />
                    <input
                      id={`${tokenId}-hex`}
                      className="theme-manager-hex"
                      type="text"
                      spellCheck={false}
                      autoComplete="off"
                      aria-label={`${token.label} HEX`}
                      aria-invalid={invalid}
                      aria-describedby={`${tokenId}-description${invalid ? ` ${tokenId}-error` : ""}`}
                      value={input}
                      onChange={(event) =>
                        changeColor(token.key, event.target.value)
                      }
                    />
                    <button
                      type="button"
                      disabled={
                        !overridden && draft.inputs[token.key] === undefined
                      }
                      aria-label={`${token.label} ${token.derive ? "恢复跟随" : "恢复默认"}`}
                      onClick={() => resetColor(token.key)}
                    >
                      {token.derive ? "恢复跟随" : "恢复默认"}
                    </button>
                  </div>
                  {token.allowAlpha ? (
                    <label className="theme-manager-alpha">
                      不透明度
                      <input
                        type="range"
                        aria-label={`${token.label} 不透明度`}
                        min="0"
                        max="100"
                        step="1"
                        value={Math.round((alpha / 255) * 100)}
                        onChange={(event) =>
                          changeColor(
                            token.key,
                            `${normalized.slice(0, 7)}${Math.round(
                              (Number(event.target.value) / 100) * 255,
                            )
                              .toString(16)
                              .padStart(2, "0")}`,
                          )
                        }
                      />
                      <output>{Math.round((alpha / 255) * 100)}%</output>
                    </label>
                  ) : (
                    <small>此颜色不支持透明度。</small>
                  )}
                  {invalid && (
                    <p
                      className="theme-manager-field-error"
                      id={`${tokenId}-error`}
                    >
                      请输入有效的 HEX 颜色
                      {token.allowAlpha
                        ? "（如 #336699 或 #33669980）"
                        : "，不透明度必须为 100%"}
                      。预览保留最近有效值。
                    </p>
                  )}
                </div>
              );
            })}
          </fieldset>
          {!visibleTokens.length && (
            <p className="theme-manager-hint">
              没有匹配的颜色，请调整搜索词或分组。
            </p>
          )}
          {!draft.theme.readonly && !draft.sourceId && draft.theme.id !== BUILTIN_THEME.id && (
            <button
              type="button"
              className="theme-manager-delete"
              disabled={!canManage || busy || loading}
              onClick={() => setConfirmation({ kind: "delete" })}
            >
              删除主题
            </button>
          )}
        </section>
        <section
          className="theme-manager-preview-panel"
          data-pane="preview"
          aria-label="局部预览"
        >
          <div className="theme-manager-panel-title">
            <h2>即时预览</h2>
            <span>{preview.scheme === "dark" ? "深色" : "浅色"}</span>
          </div>
          <p className="theme-manager-hint">
            编辑仅作用于下方示例，保存并应用后更新工作台。
          </p>
          <ThemePreview appearance={preview} />
          <details
            className="theme-manager-contrast"
            open={contrastWarnings.length > 0}
          >
            <summary>
              {contrastWarnings.length
                ? `${contrastWarnings.length} 项对比度建议`
                : "对比度检查"}
            </summary>
            <p>
              正文建议至少 4.5:1，关键图标与焦点建议至少
              3:1。对比度提示不影响保存。
            </p>
            {contrastWarnings.length ? (
              <ul>
                {contrastWarnings.map((item) => (
                  <li key={item.key}>
                    {item.label} / {item.background}：{item.ratio.toFixed(2)}
                    :1，建议 ≥ {item.target}:1
                  </li>
                ))}
              </ul>
            ) : (
              <p>已配置的颜色组合达到建议对比度。</p>
            )}
          </details>
        </section>
      </div>
      <footer className="theme-manager-footer">
        <div aria-live="polite">
          {invalidTokens.length
            ? `${invalidTokens.length} 项颜色格式有误，请修正后保存。`
            : !valid
              ? "请填写主题名称。"
              : dirty
                ? "草稿尚未保存"
                : "主题设置已保存"}
        </div>
        <div className="theme-manager-footer-actions">
          <button
            type="button"
            disabled={busy || !dirty}
            onClick={() => requestAction({ kind: "cancel" })}
          >
            取消
          </button>
          <button
            type="button"
            disabled={!editable || !dirty || !valid || busy || loading}
            onClick={() => void save(false)}
          >
            保存
          </button>
          {dirty ? (
            <button
              type="button"
              className="theme-manager-primary"
              disabled={!editable || !valid || busy || loading}
              onClick={() => void save(true)}
            >
              {busy ? "处理中…" : "保存并应用"}
            </button>
          ) : (
            <button
              type="button"
              className="theme-manager-primary"
              disabled={
                !canManage ||
                busy ||
                loading ||
                draft.theme.id === library.selectedThemeId
              }
              onClick={() => void applyTheme()}
            >
              {draft.theme.id === library.selectedThemeId
                ? "已应用"
                : "应用主题"}
            </button>
          )}
        </div>
      </footer>
      {confirmation && (
        <ConfirmPanel
          title={
            confirmation.kind === "delete"
              ? "删除这个主题？"
              : confirmation.kind === "reload"
                ? "重新加载主题库"
                : busy
                  ? "正在处理主题"
                  : dirty
                    ? "有未保存的更改"
                    : "更改已保存"
          }
          busy={busy}
          onDismiss={() => setConfirmation(null)}
        >
          {confirmation.kind === "delete" ? (
            <>
              <p>
                将删除“{draft.theme.name}”。
                {draft.theme.id === library.selectedThemeId
                  ? "当前应用会恢复为钢铁核心。"
                  : ""}
                {dirty ? "未保存的更改也会丢弃。" : ""}
              </p>
              {error && (
                <p role="alert" className="theme-manager-field-error">
                  {error}
                </p>
              )}
              <div className="theme-manager-dialog-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setConfirmation(null)}
                >
                  保留主题
                </button>
                <button
                  type="button"
                  disabled={busy}
                  className="theme-manager-delete"
                  onClick={() => void removeTheme()}
                >
                  确认删除
                </button>
              </div>
            </>
          ) : confirmation.kind === "reload" ? (
            <>
              <p>
                保留草稿并重载后，下一次保存会以最新版本提交，覆盖这个主题在其他页面的修改。也可以放弃草稿，读取服务器上已保存的主题。
              </p>
              <div className="theme-manager-dialog-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setConfirmation(null)}
                >
                  继续编辑
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void reloadLibrary("discard")}
                >
                  放弃草稿并重载
                </button>
                <button
                  type="button"
                  className="theme-manager-primary"
                  disabled={busy}
                  onClick={() => void reloadLibrary("keep")}
                >
                  保留草稿并重载
                </button>
              </div>
            </>
          ) : (
            <>
              <p>
                {busy
                  ? "请等待当前操作完成，再选择是否离开。"
                  : dirty
                    ? confirmation.action.kind === "import"
                      ? "导入后会打开新主题，可以先保存这份配色，或放弃本次更改。"
                      : "离开前，可以保存这份配色，或放弃本次更改。"
                    : "更改已保存，可以离开此页。"}
              </p>
              {!valid && (
                <p className="theme-manager-field-error">
                  请继续编辑并修正输入后保存。
                </p>
              )}
              {error && (
                <p role="alert" className="theme-manager-field-error">
                  {error}
                </p>
              )}
              <div className="theme-manager-dialog-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setConfirmation(null)}
                >
                  继续编辑
                </button>
                <button
                  type="button"
                  disabled={busy || !dirty}
                  onClick={() => performAction(confirmation.action)}
                >
                  放弃更改
                </button>
                <button
                  type="button"
                  className="theme-manager-primary"
                  disabled={busy || (dirty && (!editable || !valid))}
                  onClick={async () => {
                    const action = confirmation.action;
                    if (!dirty) {
                      performAction(action);
                      return;
                    }
                    const result = await save(false);
                    if (result) {
                      if (action.kind === "cancel") setConfirmation(null);
                      else performAction(action, result);
                    }
                  }}
                >
                  {dirty ? "保存后离开" : "离开"}
                </button>
              </div>
            </>
          )}
        </ConfirmPanel>
      )}
    </section>
  );
}
