import { useEffect, useState } from "react";
import { LoaderCircle, RefreshCw, Wrench } from "lucide-react";
import type { ClusterSetupPrepareResult, ClusterStatus } from "../services/types";
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
  kimi: "Kimi",
  pi: "Pi",
};

function cliLabel(cliType: string) {
  return CLI_LABELS[cliType] || cliType;
}

function targetStatus(status: ClusterStatus) {
  const activeCliType = status.mcp.activeCliType === "pi"
    ? "pi"
    : status.mcp.activeCliType === "kimi"
      ? "kimi"
      : status.mcp.activeCliType === "claude"
        ? "claude"
        : "codex";
  const activeStatus = activeCliType === "pi"
    ? status.mcp.pi
    : activeCliType === "kimi"
      ? status.mcp.kimi
      : activeCliType === "claude"
        ? status.mcp.claude
        : status.mcp.codex;
  return { activeCliType, activeStatus };
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
    <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-[var(--text)]">集群 MCP</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">{status?.mcp.serverName || "tcb-cluster"}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void loadStatus()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
          >
            <RefreshCw className="h-4 w-4" />
            重新检测
          </button>
          <button
            type="button"
            onClick={() => void prepareInstall()}
            disabled={!canManage}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm tcb-solid-accent disabled:opacity-60"
          >
            <Wrench className="h-4 w-4" />
            生成安装命令
          </button>
        </div>
      </div>
      {loading ? (
        <p className="mt-3 inline-flex items-center gap-2 text-sm text-[var(--muted)]">
          <LoaderCircle className="h-4 w-4 animate-spin" />
          处理中
        </p>
      ) : null}
      {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
      {status ? (
        <div className="mt-3 grid gap-2 text-sm">
          {(() => {
            const { activeCliType, activeStatus } = targetStatus(status);
            return <div>{cliLabel(activeCliType)}：{activeStatus?.message || activeStatus?.state || "未检测"}</div>;
          })()}
          {status.mcp.pi ? <div>Pi：{status.mcp.pi.message || status.mcp.pi.state}</div> : null}
        </div>
      ) : null}
      {prepare ? (
        <div className="mt-4 space-y-3">
          {prepare.installCommand.length > 0 ? <div>
            <div className="text-sm font-medium text-[var(--text)]">安装命令</div>
            <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] p-3 text-xs">{commandText(prepare.installCommand)}</pre>
          </div> : null}
          {prepare.verifyCommand.length > 0 ? <div>
            <div className="text-sm font-medium text-[var(--text)]">验证命令</div>
            <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] p-3 text-xs">{commandText(prepare.verifyCommand)}</pre>
          </div> : null}
          {prepare.piSettingsSnippet ? (
            <div>
              <div className="text-sm font-medium text-[var(--text)]">Pi settings.json</div>
              <p className="mt-1 break-all text-xs text-[var(--muted)]">{prepare.piSettingsPath}</p>
              <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] p-3 text-xs">{prepare.piSettingsSnippet}</pre>
            </div>
          ) : null}
          {prepare.selfTestCommand && prepare.selfTestCommand.length > 0 ? (
            <div>
              <div className="text-sm font-medium text-[var(--text)]">本项目自检</div>
              <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] p-3 text-xs">{commandText(prepare.selfTestCommand)}</pre>
            </div>
          ) : null}
          {prepare.piSettingsSnippet ? (
            <div className="rounded-md border border-[var(--border)] bg-[var(--bg)] p-3 text-xs text-[var(--muted)]">
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
