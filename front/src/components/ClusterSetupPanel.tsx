import { useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Wrench } from "lucide-react";
import type { ClusterMcpTargetStatus, ClusterSetupPrepareResult, ClusterStatus } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
  canManage?: boolean;
};

function commandText(command: string[]) {
  return command.map((part) => (/\s/.test(part) ? `"${part}"` : part)).join(" ");
}

const CLI_LABELS: Record<string, string> = {
  claude: "Claude",
  codex: "Codex",
  codex_server: "codex server",
  antigravity: "Antigravity CLI",
  deepseek: "DeepSeek Harness",
  pi: "Pi",
};

function cliLabel(cliType: string) {
  return CLI_LABELS[cliType] || cliType;
}

function targetStatuses(status: ClusterStatus): Array<[string, ClusterMcpTargetStatus]> {
  const targets = status.mcp.targets || status.mcp.byCliType;
  if (targets && Object.keys(targets).length > 0) return Object.entries(targets);
  const legacy: Array<[string, ClusterMcpTargetStatus | undefined]> = [
    ["codex", status.mcp.codex],
    ["codex_server", status.mcp.codexServer],
    ["claude", status.mcp.claude],
    ["deepseek", status.mcp.deepseek],
    ["antigravity", status.mcp.antigravity],
    ["pi", status.mcp.pi],
  ];
  const active = legacy.find(([cliType]) => cliType === status.mcp.activeCliType);
  return (active?.[1] ? [[active[0], active[1]]] : legacy.filter((entry): entry is [string, ClusterMcpTargetStatus] => Boolean(entry[1])));
}

export function ClusterSetupPanel({ botAlias, client, canManage = true }: Props) {
  const [status, setStatus] = useState<ClusterStatus | null>(null);
  const [prepare, setPrepare] = useState<ClusterSetupPrepareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadStatus() {
    setLoading(true);
    setError("");
    try {
      setStatus(await client.getClusterStatus(botAlias));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载集群状态失败");
    } finally {
      setLoading(false);
    }
  }

  async function prepareInstall() {
    setLoading(true);
    setError("");
    try {
      setPrepare(await client.prepareClusterSetup(botAlias));
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成安装命令失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStatus();
  }, [botAlias]);

  return (
    <section className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2.5 py-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xs font-semibold text-[var(--text)]">集群 MCP</h2>
          <p className="font-mono text-[11px] text-[var(--muted)]">{status?.mcp.serverName || "tcb-cluster"}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <button
            type="button"
            onClick={() => void loadStatus()}
            className="inline-flex h-7 items-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] px-2 text-xs transition-colors hover:bg-[var(--workbench-hover-bg)]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新状态
          </button>
          <button
            type="button"
            onClick={() => void prepareInstall()}
            disabled={!canManage}
            className="tcb-solid-accent inline-flex h-7 items-center gap-1.5 rounded-[var(--radius-control)] px-2.5 text-xs font-medium hover:opacity-90 disabled:opacity-60"
          >
            <Wrench className="h-3.5 w-3.5" />
            生成安装命令
          </button>
        </div>
      </div>
      {loading ? (
        <p className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-[var(--muted)]">
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
          处理中
        </p>
      ) : null}
      {error ? <p className="mt-2 text-xs text-[var(--feedback-error-text-deep)]">{error}</p> : null}
      {status ? (
        <div className="mt-2 grid gap-1.5">
          {targetStatuses(status).map(([cliType, target]) => (
            <div key={cliType} className="grid gap-0.5 border-b border-[var(--workbench-hairline)] pb-1.5 last:border-0 last:pb-0">
              <div className="text-[var(--text)]">{cliLabel(cliType)}：{target.message || target.state || "未检测"}</div>
              {target.configPath ? <div className="break-all text-xs text-[var(--muted)]">配置：{target.configPath}</div> : null}
              {target.scope ? <div className="text-xs text-[var(--muted)]">范围：{target.scope}</div> : null}
              {target.allowedTools?.length ? <div className="text-xs text-[var(--muted)]">允许工具：{target.allowedTools.join("、")}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
      {prepare ? (
        <div className="mt-2.5 space-y-2.5">
          {prepare.unsupported ? (
            <div className="rounded-md border border-[var(--status-warning-border)] bg-[var(--status-warning-bg)] px-2.5 py-2 text-xs text-[var(--status-warning)]">
              {prepare.message || "当前 CLI 暂不支持集群 MCP"}
            </div>
          ) : null}
          {prepare.mcpSetupSnippet ? (
            <div className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 py-2 text-xs text-[var(--muted)]">
              {prepare.mcpSetupSnippet}
            </div>
          ) : null}
          {prepare.targets && Object.keys(prepare.targets).length > 0 ? (
            <div className="grid gap-2">
              {Object.entries(prepare.targets).map(([cliType, target]) => (
                <div key={cliType} className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 py-2 text-xs">
                  <div className="font-medium text-[var(--text)]">{cliLabel(target.cliType || cliType)}</div>
                  {target.message ? <p className="mt-1 text-xs text-[var(--muted)]">{target.message}</p> : null}
                  {target.installCommand?.length ? <pre className="mt-2 overflow-x-auto rounded-md bg-[var(--surface-strong)] px-2 py-1.5 text-[11px] leading-4">安装：{commandText(target.installCommand)}</pre> : null}
                  {target.verifyCommand?.length ? <pre className="mt-2 overflow-x-auto rounded-md bg-[var(--surface-strong)] px-2 py-1.5 text-[11px] leading-4">验证：{commandText(target.verifyCommand)}</pre> : null}
                  {target.deepseekPatchPath ? <p className="mt-1 break-all text-xs text-[var(--muted)]">DeepSeek patch：{target.deepseekPatchPath}</p> : null}
                  {target.piExtensionPath ? <p className="mt-1 break-all text-xs text-[var(--muted)]">Pi 扩展：{target.piExtensionPath}</p> : null}
                </div>
              ))}
            </div>
          ) : null}
          {prepare.installCommand.length > 0 ? <div>
            <div className="text-xs font-medium text-[var(--text)]">安装命令</div>
            <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] px-2.5 py-2 text-[11px] leading-4">{commandText(prepare.installCommand)}</pre>
          </div> : null}
          {prepare.verifyCommand.length > 0 ? <div>
            <div className="text-xs font-medium text-[var(--text)]">验证命令</div>
            <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] px-2.5 py-2 text-[11px] leading-4">{commandText(prepare.verifyCommand)}</pre>
          </div> : null}
          {prepare.workspaceMcpConfigPath ? (
            <div>
              <div className="text-xs font-medium text-[var(--text)]">Antigravity 工作区 MCP</div>
              <p className="mt-1 break-all text-xs text-[var(--muted)]">{prepare.workspaceMcpConfigPath}</p>
              {prepare.workspaceMcpScope ? <p className="mt-1 text-xs text-[var(--muted)]">范围：{prepare.workspaceMcpScope}</p> : null}
              {prepare.mcpAllowedTools?.length ? (
                <p className="mt-1 text-xs text-[var(--muted)]">允许工具：{prepare.mcpAllowedTools.join("、")}</p>
              ) : null}
              {prepare.statuslineCommand?.length ? (
                <>
                  <p className="mt-2 text-xs text-[var(--muted)]">状态栏遥测命令（配置到 Antigravity settings.json 的 statusLine.command）</p>
                  <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] px-2.5 py-2 text-[11px] leading-4">{commandText(prepare.statuslineCommand)}</pre>
                </>
              ) : null}
            </div>
          ) : null}
          {prepare.piExtensionPath ? (
            <div>
              <div className="text-xs font-medium text-[var(--text)]">Pi 扩展</div>
              <p className="mt-1 break-all text-xs text-[var(--muted)]">{prepare.piExtensionPath}</p>
              <p className="mt-1 text-xs text-[var(--muted)]">{prepare.piExtensionName || "tcb-cluster.ts"}</p>
            </div>
          ) : prepare.piSettingsSnippet ? (
            <div>
              <div className="text-xs font-medium text-[var(--text)]">Pi settings.json</div>
              <p className="mt-1 break-all text-xs text-[var(--muted)]">{prepare.piSettingsPath}</p>
              <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] px-2.5 py-2 text-[11px] leading-4">{prepare.piSettingsSnippet}</pre>
            </div>
          ) : null}
          {prepare.selfTestCommand && prepare.selfTestCommand.length > 0 ? (
            <div>
              <div className="text-xs font-medium text-[var(--text)]">本项目自检</div>
              <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] px-2.5 py-2 text-[11px] leading-4">{commandText(prepare.selfTestCommand)}</pre>
            </div>
          ) : null}
          {prepare.piExtensionPath ? (
            <div className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 py-2 text-[11px] text-[var(--muted)]">
              <div className="font-medium text-[var(--text)]">Pi 验证步骤</div>
              <ol className="mt-2 list-decimal space-y-1 pl-5">
                <li>生成 launcher 和 config</li>
                <li>把 tcb-cluster.ts 放入 Pi 扩展目录</li>
                <li>重启 Pi 原生 agent</li>
                <li>开启集群模式后用当前 run_id 调 cluster_status</li>
              </ol>
              <p className="mt-2">Pi 是主 agent，子 agent 仍由本项目 cluster runtime 托管。</p>
            </div>
          ) : prepare.piSettingsSnippet ? (
            <div className="rounded-md border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 py-2 text-[11px] text-[var(--muted)]">
              <div className="font-medium text-[var(--text)]">Pi 验证步骤</div>
              <ol className="mt-2 list-decimal space-y-1 pl-5">
                <li>生成 launcher 和 config</li>
                <li>把上方 JSON 合入 Pi settings.json</li>
                <li>重启 Pi 原生 agent</li>
                <li>开启集群模式后用当前 run_id 调 cluster_status</li>
              </ol>
              <p className="mt-2">Pi 是主 agent，子 agent 仍由本项目 cluster runtime 托管。</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
