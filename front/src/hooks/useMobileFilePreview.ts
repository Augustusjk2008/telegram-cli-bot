import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { WebBotClient } from "../services/webBotClient";
import type { FileDownloadProgress, FileReadOptions, HostEffect, PluginOpenTarget, PluginRenderResult, RemoteWorkspace } from "../services/types";
import { applyPluginUtilityEffect, pluginViewTabPath } from "../components/plugins/pluginActions";
import { absoluteWorkspacePath, workspaceRelativePath } from "../services/workspacePath";
import { normalizeRemotePath } from "../services/remoteWorkspace";
import { isHtmlPreviewPath, loadFilePreview, type FilePreviewData } from "../utils/filePreview";
import { useMobilePreviewHistory } from "./useMobilePreviewHistory";
import { resolvePreviewFilePath } from "../utils/fileLinks";

export type MobileFilePreviewRequest = {
  origin: "files" | "chat";
  botAlias: string;
  path: string;
  directory: string;
  client: WebBotClient;
  agentId?: string;
  sessionId?: string;
  hostAttachment?: boolean;
  supportsWorkspaceFileBase?: boolean;
  onEdit?: (filename: string, isCurrent: () => boolean, options?: FileReadOptions) => Promise<boolean>;
};

export type MobilePreviewScope = {
  client: WebBotClient;
  accountId: string;
  botAlias: string;
  workspace: string;
  remote?: RemoteWorkspace;
  canRead: boolean;
  canWrite: boolean;
  canUsePlugins: boolean;
  canReadAbsolute: boolean;
};

type Operation = { kind: "resolve" } | { kind: "file"; mode: "preview" | "full" } | { kind: "plugin"; target: PluginOpenTarget };
type Preview = {
  id: number;
  request: MobileFilePreviewRequest;
  path: string;
  filename: string;
  isWorkspaceFile: boolean;
  fileOptions?: FileReadOptions;
  operation: Operation;
  choices?: PluginOpenTarget[];
  data?: FilePreviewData;
  view?: PluginRenderResult;
  loading: boolean;
  error: string;
  download?: FileDownloadProgress;
  editing?: boolean;
};
type Owner = {
  page: Preview;
  scope: MobilePreviewScope;
  identity: string;
  attempt: number;
  download?: AbortController;
  opener: HTMLElement | null;
};

const occupiedMessage = "请先关闭当前预览";
let nextId = 0;

function windowsPath(path: string) {
  return /^(?:\/?[a-z]:[\\/]|\\\\|\/\/)/i.test(path);
}

function absolutePath(path: string, directory: string, platform?: RemoteWorkspace["platform"]) {
  const windows = platform === "windows" || (!platform && windowsPath(directory || path));
  const absolute = absoluteWorkspacePath(path, directory, windows) ?? path;
  return platform === "windows" ? normalizeRemotePath(absolute, platform) : absolute;
}

function locateFile(request: MobileFilePreviewRequest, scope: MobilePreviewScope) {
  const platform = request.hostAttachment || !scope.remote ? undefined : scope.remote.platform || "posix";
  const directory = request.hostAttachment ? "" : request.directory || scope.workspace;
  const path = absolutePath(request.path, directory, platform);
  const windows = platform === "windows" || (!platform && windowsPath(path));
  const relative = !scope.remote && !request.hostAttachment ? workspaceRelativePath(path, directory, scope.workspace, windows) : null;
  let filename = path;
  let fileOptions: FileReadOptions | undefined;
  if (relative !== null && (request.origin === "chat" || request.supportsWorkspaceFileBase === true)) {
    filename = relative;
    fileOptions = { workspaceRelative: true };
  } else if (!scope.remote && !scope.canReadAbsolute) {
    // Files has already changed the server's browse directory to the folder containing this row.
    filename = request.path;
    if (request.directory) fileOptions = { expectedDirectory: request.directory };
  }
  const identity = JSON.stringify([Boolean(request.hostAttachment), windows ? path.toLowerCase() : path]);
  return { path, filename, isWorkspaceFile: relative !== null, fileOptions, identity };
}

function disposeView(request: MobileFilePreviewRequest, view?: PluginRenderResult) {
  if (view?.mode === "session") {
    void request.client.disposePluginViewSession(request.botAlias, view.pluginId, view.sessionId).catch(() => undefined);
  }
}

function releaseContent(page: Preview) {
  page.data?.htmlPreview?.dispose();
  disposeView(page.request, page.view);
}

export function useMobileFilePreview(scope: MobilePreviewScope, showTab: (tab: MobileFilePreviewRequest["origin"]) => void) {
  const owner = useRef<Owner | null>(null);
  const latestScope = useRef(scope);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [notice, setNotice] = useState("");

  function update(slot: Owner, patch: Partial<Preview>) {
    if (owner.current !== slot) return;
    slot.page = { ...slot.page, ...patch };
    setPreview(slot.page);
  }

  const release = useCallback(() => {
    const slot = owner.current;
    if (!slot) return;
    owner.current = null;
    slot.download?.abort();
    releaseContent(slot.page);
    setPreview(null);
    setNotice("");
    if (slot.opener) requestAnimationFrame(() => {
      if (!owner.current && slot.opener?.isConnected && !slot.opener.closest("[inert]")) slot.opener.focus({ preventScroll: true });
    });
  }, []);

  const { open: pushHistory, close: backToOrigin } = useMobilePreviewHistory(release);
  const close = useCallback(() => {
    const slot = owner.current;
    if (!slot) return;
    release();
    backToOrigin(slot.page.id);
  }, [release, backToOrigin]);

  // A cached chat may still hold a click callback from a previous workspace.
  const identity = useMemo(() => ({}), [
    scope.client, scope.accountId, scope.botAlias, scope.workspace, scope.remote?.connectionId,
    scope.remote?.root, scope.remote?.platform, scope.remote?.hostKeyFingerprint,
  ]);
  const liveIdentity = useRef<object | null>(null);
  useLayoutEffect(() => {
    liveIdentity.current = identity;
    return () => { liveIdentity.current = null; close(); };
  }, [identity, close]);

  useLayoutEffect(() => {
    latestScope.current = scope;
    const slot = owner.current;
    if (!slot) return;
    const { fileOptions, choices, operation } = slot.page;
    const usesPlugin = operation.kind === "plugin" || Boolean(choices)
      || (operation.kind === "resolve" && slot.page.isWorkspaceFile && slot.scope.canUsePlugins);
    const usesAbsoluteAccess = !slot.scope.remote && !fileOptions && slot.scope.canReadAbsolute;
    if (!scope.canRead || (usesPlugin && !scope.canUsePlugins) || (usesAbsoluteAccess && !scope.canReadAbsolute)) close();
  }, [scope, close]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 4800);
    return () => window.clearTimeout(timer);
  }, [notice]);

  async function load(slot: Owner, operation: Operation): Promise<void> {
    if (owner.current !== slot) return;
    const attempt = ++slot.attempt;
    const current = () => owner.current === slot && slot.attempt === attempt;
    const { request, path, filename, fileOptions } = slot.page;
    const { client, botAlias } = request;
    releaseContent(slot.page);
    update(slot, { operation, data: undefined, view: undefined, choices: undefined, error: "", loading: true });
    try {
      if (operation.kind === "resolve") {
        if (slot.page.isWorkspaceFile && slot.scope.canUsePlugins) {
          // Plugin input is resolved against the server's browse directory; pin it to this file.
          const target = await client.resolveFileOpenTarget(botAlias, path);
          if (!current()) return;
          if (target.kind === "plugin_view") {
            if (!isHtmlPreviewPath(path)) return await load(slot, { kind: "plugin", target });
            update(slot, { choices: [target], loading: false });
            return;
          }
          if (target.pluginTargets?.length) {
            update(slot, { choices: target.pluginTargets, loading: false });
            return;
          }
        }
        return await load(slot, { kind: "file", mode: "preview" });
      }
      if (operation.kind === "plugin") {
        const { pluginId, viewId, input } = operation.target;
        const view = await client.openPluginView(botAlias, pluginId, viewId, input, { isolatedSession: true });
        if (!current()) { disposeView(request, view); return; }
        update(slot, { view, loading: false });
      } else {
        const data = await loadFilePreview(client, botAlias, filename, {
          mode: operation.mode, agentId: request.agentId, remote: Boolean(slot.scope.remote), fileOptions, isCurrent: current,
        });
        if (!current()) { data.htmlPreview?.dispose(); return; }
        update(slot, { data, loading: false });
      }
    } catch (error) {
      if (current()) update(slot, { loading: false, error: error instanceof Error ? error.message : "预览文件失败" });
    }
  }

  function open(request: MobileFilePreviewRequest) {
    if (liveIdentity.current !== identity) return false;
    const context = latestScope.current;
    if (request.botAlias !== context.botAlias || !context.canRead) {
      setNotice("无文件读取权限");
      return false;
    }
    const { identity: fileIdentity, ...location } = locateFile(request, context);
    const active = owner.current;
    if (active) {
      if (active.identity === fileIdentity) {
        setNotice("");
        showTab(active.page.request.origin);
        return true;
      }
      setNotice(occupiedMessage);
      return false;
    }
    const page: Preview = {
      ...location, id: ++nextId, request, operation: { kind: "resolve" }, loading: true, error: "",
    };
    const slot: Owner = {
      page, scope: context, identity: fileIdentity, attempt: 0,
      opener: document.activeElement instanceof HTMLElement ? document.activeElement : null,
    };
    owner.current = slot;
    setPreview(page);
    setNotice("");
    pushHistory(page.id);
    showTab(request.origin);
    void load(slot, page.operation);
    return true;
  }

  // All callbacks handed to a viewer belong to that opening and that version of its content.
  const slot = owner.current;
  const attempt = slot?.attempt;
  const displayed = () => slot && owner.current === slot && slot.attempt === attempt ? slot : null;
  function loadCurrent(operation: Operation) {
    const active = displayed();
    if (active) void load(active, operation);
  }

  function requestLink(href: string) {
    const active = displayed();
    if (!active) return;
    const { path, request } = active.page;
    const platform = scope.remote && !request.hostAttachment ? scope.remote.platform || "posix" : undefined;
    const linkPlatform = platform ?? (path.startsWith("/") && !windowsPath(path) ? "posix" : undefined);
    const linked = resolvePreviewFilePath(href, "", linkPlatform);
    if (linked) open({ ...request, path: linked, directory: path.slice(0, path.lastIndexOf("/") + 1) });
  }

  function samePluginTarget(current: PluginOpenTarget, requested: PluginOpenTarget) {
    const identity = (target: PluginOpenTarget) => {
      if (typeof target.input.path !== "string") return pluginViewTabPath(target);
      const path = absolutePath(target.input.path, scope.workspace);
      return pluginViewTabPath({ ...target, input: { ...target.input, path: windowsPath(path) ? path.toLowerCase() : path } });
    };
    return identity(current) === identity(requested);
  }

  function reopenPlugin(target: PluginOpenTarget) {
    const active = displayed();
    if (!active || active.page.operation.kind !== "plugin") return;
    if (samePluginTarget(active.page.operation.target, target)) loadCurrent(active.page.operation);
    else setNotice(occupiedMessage);
  }

  async function applyHostEffects(effects: HostEffect[]): Promise<void | false> {
    let blocked = false;
    for (const effect of effects) {
      const active = displayed();
      if (!active?.page.view) return false;
      const { request, view, operation } = active.page;
      if (effect.type === "open_file" || effect.type === "reveal_in_files") {
        if (!open({ ...request, directory: scope.workspace, path: effect.path })) blocked = true;
      } else if (effect.type === "open_plugin_view") {
        const target = operation.kind === "plugin" ? operation.target : undefined;
        if (target && samePluginTarget(target, effect)) showTab(request.origin);
        else {
          setNotice(occupiedMessage);
          blocked = true;
        }
      } else {
        try {
          await applyPluginUtilityEffect(effect, request.client, request.botAlias, view.pluginId);
        } catch (error) {
          if (displayed()) setNotice(error instanceof Error ? error.message : "插件操作失败");
          return false;
        }
      }
    }
    if (blocked) return false;
  }

  async function download() {
    const active = displayed();
    if (!active || active.download) return;
    const { request, filename, fileOptions } = active.page;
    const controller = new AbortController();
    active.download = controller;
    const isCurrent = () => owner.current === active && active.download === controller && !controller.signal.aborted;
    update(active, { download: { downloadedBytes: 0 } });
    try {
      await request.client.downloadFile(request.botAlias, filename, progress => {
        if (isCurrent()) update(active, { download: progress });
      }, controller.signal, fileOptions);
    } catch (error) {
      if (isCurrent()) setNotice(error instanceof Error ? error.message : "下载文件失败");
    } finally {
      if (active.download === controller) {
        active.download = undefined;
        update(active, { download: undefined });
      }
    }
  }

  async function edit(isForeground: () => boolean) {
    const active = displayed();
    if (!active?.page.request.onEdit || !latestScope.current.canWrite || active.page.editing) return;
    const isCurrent = () => displayed() === active && isForeground();
    update(active, { editing: true });
    try {
      const opened = await active.page.request.onEdit(active.page.filename, isCurrent, active.page.fileOptions);
      if (isCurrent()) {
        if (opened) close();
        else setNotice("无法打开编辑器，请返回文件页查看详情");
      }
    } catch (error) {
      if (isCurrent()) setNotice(error instanceof Error ? error.message : "打开编辑器失败");
    } finally {
      update(active, { editing: false });
    }
  }

  return {
    preview, open, notice, close: () => close(), edit, download, requestLink, applyHostEffects, reopenPlugin,
    cancelDownload() {
      if (!slot?.download || owner.current !== slot) return;
      slot.download.abort();
      slot.download = undefined;
      update(slot, { download: undefined });
    },
    retry() { if (preview) loadCurrent(preview.operation); },
    readFile(mode: "preview" | "full") { loadCurrent({ kind: "file", mode }); },
    choosePlugin(target: PluginOpenTarget) {
      const active = displayed();
      if (active?.page.choices?.includes(target) && latestScope.current.canUsePlugins) loadCurrent({ kind: "plugin", target });
    },
    closePlugin() { if (displayed()) close(); },
    pluginNotice(message: string) { if (displayed()) setNotice(message); },
  };
}

export type MobileFilePreviewController = ReturnType<typeof useMobileFilePreview>;
