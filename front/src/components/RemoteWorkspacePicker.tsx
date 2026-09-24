import { useState } from "react";
import type { DirectoryListing, RemoteWorkspace } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { joinRemotePath, normalizeRemotePath, parentRemotePath } from "../services/remoteWorkspace";
import { RemoteConnectionForm, remoteButtonClass, remoteInputClass } from "./RemoteConnectionForm";

export function RemoteWorkspacePicker({ client, initial, onPick }: {
  client: WebBotClient; initial?: RemoteWorkspace; onPick: (remote: RemoteWorkspace) => void;
}) {
  const [remote, setRemote] = useState<RemoteWorkspace>();
  const [listing, setListing] = useState<DirectoryListing>();
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState("");

  async function browse(connection: RemoteWorkspace, nextPath: string) {
    setBusy(true); setError("");
    try {
      const next = await client.listRemoteDirectories(connection.connectionId, normalizeRemotePath(nextPath, connection.platform));
      setListing(next); setPath(next.workingDir);
    } catch (err) { setError(err instanceof Error ? err.message : "读取远程目录失败"); }
    finally { setBusy(false); }
  }
  if (!remote) return <RemoteConnectionForm client={client} initial={initial} onConnected={(next) => { setRemote(next); setPath(next.root); void browse(next, next.root); }} />;
  return <section className="space-y-3 rounded-md border border-[var(--border)] p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="break-all text-sm">SSH 已连接：{remote.username}@{remote.host}:{remote.port}</p>
      {initial && <button type="button" className={remoteButtonClass} onClick={() => { setRemote(undefined); setListing(undefined); setPath(""); setSelected(""); setError(""); }}>更换 SSH 地址</button>}
    </div>
    <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void browse(remote, path); }}>
      <input aria-label="远程目录路径" className={remoteInputClass} value={path} onChange={(e) => setPath(e.target.value)} />
      <button className={remoteButtonClass} disabled={busy}>打开</button>
    </form>
    {remote.platform === "windows" && <p className="text-xs text-[var(--muted)]">可输入 D:\ 等绝对路径切换盘符。</p>}
    <div className="flex flex-wrap gap-2">
      <button type="button" className={remoteButtonClass} disabled={busy || !listing || parentRemotePath(listing.workingDir, remote.platform) === listing.workingDir} onClick={() => void browse(remote, parentRemotePath(listing!.workingDir, remote.platform))}>上级目录</button>
      <button type="button" className={remoteButtonClass} disabled={busy} onClick={() => void browse(remote, remote.root)}>主目录</button>
    </div>
    <div aria-label="远程目录" className="max-h-48 overflow-auto">
      {listing?.entries.filter((entry) => entry.isDir).map((entry) => <button type="button" key={entry.name} className="block w-full rounded px-2 py-2 text-left text-sm hover:bg-[var(--surface-strong)]" disabled={busy} onClick={() => void browse(remote, joinRemotePath(listing.workingDir, entry.name, remote.platform))}>📁 {entry.name}</button>)}
      {busy && <p role="status">正在读取目录…</p>}
    </div>
    {error && <p role="alert" className="text-sm text-[var(--danger)]">{error}</p>}
    <button type="button" className={remoteButtonClass} disabled={busy || !listing || Boolean(error)} onClick={() => { setSelected(listing!.workingDir); onPick({ ...remote, root: listing!.workingDir }); }}>选择此远程工作目录</button>
    {selected && <p className="break-all text-sm">已选择：{selected}</p>}
  </section>;
}
