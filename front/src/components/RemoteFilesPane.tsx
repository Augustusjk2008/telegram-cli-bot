import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, File, Folder } from "lucide-react";
import type { DirectoryListing, FileReadResult, RemoteWorkspace } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { joinRemotePath } from "../services/remoteWorkspace";
import { RemoteReconnectButton, remoteButtonClass, remoteInputClass } from "./RemoteConnectionForm";

export function RemoteFilesPane({ client, botAlias, remote, canWrite = true, canReconnect = true, structureOnly = false, onDirtyChange }: {
  client: WebBotClient; botAlias: string; remote: RemoteWorkspace; canWrite?: boolean; canReconnect?: boolean; structureOnly?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [branches, setBranches] = useState<Record<string, DirectoryListing>>({});
  const [expanded, setExpanded] = useState(new Set([remote.root]));
  const [directory, setDirectory] = useState(remote.root);
  const [path, setPath] = useState("");
  const [document, setDocument] = useState<FileReadResult>();
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const request = useRef(0);
  const dirty = Boolean(document && content !== document.content);
  const editable = Boolean(document && !document.contentBase64 && document.previewKind !== "image" && (document.isFullContent === true || (document.mode === "cat" && document.isFullContent !== false)));

  useEffect(() => { onDirtyChange?.(dirty); return () => onDirtyChange?.(false); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function load(dir: string) {
    const listing = await client.listFiles(botAlias, dir);
    setBranches((prev) => ({ ...prev, [dir]: listing }));
  }
  useEffect(() => {
    let active = true;
    client.listFiles(botAlias, remote.root).then((listing) => {
      if (active) setBranches({ [remote.root]: listing });
    }).catch((err) => { if (active) setError(err instanceof Error ? err.message : "读取远程文件失败"); });
    return () => { active = false; request.current += 1; };
  }, [botAlias, client, remote.root]);

  async function toggle(dir: string) {
    setDirectory(dir); setError("");
    if (expanded.has(dir) && dir !== remote.root) {
      setExpanded((prev) => { const next = new Set(prev); next.delete(dir); return next; });
      return;
    }
    try { await load(dir); setExpanded((prev) => new Set(prev).add(dir)); }
    catch (err) { setError(err instanceof Error ? err.message : "读取目录失败"); }
  }
  async function open(file: string) {
    if (structureOnly || busy || (dirty && !window.confirm("当前文件有未保存修改，放弃修改并打开其他文件？"))) return;
    const id = ++request.current;
    setBusy(true); setError("");
    try {
      const next = await client.readFileFull(botAlias, file);
      if (id !== request.current) return;
      setPath(file); setDocument(next); setContent(next.content);
    } catch (err) { if (id === request.current) setError(err instanceof Error ? err.message : "读取文本失败"); }
    finally { if (id === request.current) setBusy(false); }
  }
  async function save() {
    if (!canWrite || !editable || busy) return;
    setBusy(true); setError("");
    try {
      const saved = await client.writeFile(botAlias, path, content, document?.lastModifiedNs, document?.encoding);
      setDocument((prev) => prev && ({ ...prev, content, lastModifiedNs: saved.lastModifiedNs, encoding: saved.encoding || prev.encoding }));
    } catch (err) { setError(err instanceof Error ? err.message : "保存失败"); }
    finally { setBusy(false); }
  }
  async function create(kind: "file" | "directory") {
    if (!canWrite || structureOnly || busy) return;
    if (!newName || newName.includes("/") || newName === "." || newName === "..") { setError("请输入有效名称，不能包含 /"); return; }
    setBusy(true); setError("");
    try {
      if (kind === "file") await client.createTextFile(botAlias, newName, "", directory);
      else await client.createDirectory(botAlias, newName, directory);
      setNewName(""); await load(directory); setExpanded((prev) => new Set(prev).add(directory));
    } catch (err) { setError(err instanceof Error ? err.message : "创建失败"); }
    finally { setBusy(false); }
  }
  function tree(dir: string, depth = 0) {
    return branches[dir]?.entries.map((entry) => {
      const target = joinRemotePath(dir, entry.name);
      return <div key={entry.name}>
        <button type="button" role="treeitem" aria-expanded={entry.isDir ? expanded.has(target) : undefined} aria-selected={entry.isDir ? directory === target : path === target} disabled={!entry.isDir && (structureOnly || busy)} className="flex w-full min-w-0 items-center gap-1 rounded py-1.5 pr-2 text-left text-sm hover:bg-[var(--surface-strong)] aria-selected:bg-[var(--surface-strong)]" style={{ paddingLeft: 8 + depth * 14 }} onClick={() => void (entry.isDir ? toggle(target) : open(target))}>
          {entry.isDir ? <>{expanded.has(target) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<Folder size={14} /></> : <File size={14} className="ml-3.5 shrink-0" />}<span className="truncate" title={entry.name}>{entry.name}</span>
        </button>
        {entry.isDir && expanded.has(target) && <div role="group">{tree(target, depth + 1)}</div>}
      </div>;
    });
  }
  return <section className="flex h-full min-h-0 flex-col text-[var(--text)]">
    <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] p-2 text-sm">
      <span className="min-w-0 flex-1 break-all">{remote.host}:{remote.root}</span>
      <RemoteReconnectButton client={client} botAlias={botAlias} remote={remote} disabled={!canReconnect} onConnected={() => { setError(""); void load(remote.root).catch((err) => setError(err.message)); }} />
      <button type="button" className={remoteButtonClass} onClick={() => void toggle(remote.root)}>刷新</button>
    </div>
    {error && <p role="alert" className="break-words p-2 text-sm text-[var(--danger)]">{error}</p>}
    <div className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(100px,35%)_1fr] md:grid-cols-[minmax(150px,30%)_1fr] md:grid-rows-1">
      <div className="min-h-0 overflow-auto border-r border-[var(--border)] p-1">
        <button type="button" className="w-full truncate p-2 text-left text-sm" onClick={() => setDirectory(remote.root)} title={remote.root}>📁 {remote.root}</button>
        <div role="tree" aria-label="远程文件树">{tree(remote.root)}</div>
        {canWrite && !structureOnly && <div className="space-y-2 border-t border-[var(--border)] p-2">
          <p className="break-all text-xs text-[var(--muted)]">新建于 {directory}</p>
          <input aria-label="远程新建名称" className={remoteInputClass} value={newName} onChange={(e) => setNewName(e.target.value)} />
          <div className="flex flex-wrap gap-1"><button type="button" className={remoteButtonClass} disabled={busy} onClick={() => void create("file")}>新建文件</button><button type="button" className={remoteButtonClass} disabled={busy} onClick={() => void create("directory")}>新建目录</button></div>
        </div>}
      </div>
      <div className="flex min-h-0 min-w-0 flex-col">
        <div className="flex items-center gap-2 border-b border-[var(--border)] p-2"><span className="min-w-0 flex-1 truncate text-sm" title={path}>{busy ? "处理中…" : path || "选择远程文本文件"}{dirty ? " *" : ""}</span><button type="button" className={remoteButtonClass} disabled={!canWrite || !editable || !dirty || busy} onClick={() => void save()}>保存</button></div>
        {document && !editable && <p className="p-2 text-sm text-[var(--muted)]">仅支持编辑完整文本文件；此文件为只读预览。</p>}
        <textarea aria-label="远程文本编辑器" spellCheck={false} className="min-h-0 w-full flex-1 resize-none bg-[var(--surface)] p-3 font-mono text-sm outline-none" value={content} readOnly={!canWrite || !editable || busy} onChange={(e) => setContent(e.target.value)} />
      </div>
    </div>
  </section>;
}
