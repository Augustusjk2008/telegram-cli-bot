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
};

function cliLabel(cliType: string) {
  return CLI_LABELS[cliType] || cliType;
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
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-60"
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
            const activeCliType = status.mcp.activeCliType === "kimi"
              ? "kimi"
              : status.mcp.activeCliType === "claude"
                ? "claude"
                : "codex";
            const activeStatus = activeCliType === "kimi"
              ? status.mcp.kimi
              : activeCliType === "claude"
                ? status.mcp.claude
                : status.mcp.codex;
            return <div>{cliLabel(activeCliType)}：{activeStatus.message || activeStatus.state}</div>;
          })()}
        </div>
      ) : null}
      {prepare ? (
        <div className="mt-4 space-y-3">
          <div>
            <div className="text-sm font-medium text-[var(--text)]">安装命令</div>
            <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] p-3 text-xs">{commandText(prepare.installCommand)}</pre>
          </div>
          <div>
            <div className="text-sm font-medium text-[var(--text)]">验证命令</div>
            <pre className="mt-1 overflow-x-auto rounded-md bg-[var(--surface-strong)] p-3 text-xs">{commandText(prepare.verifyCommand)}</pre>
          </div>
        </div>
      ) : null}
    </section>
  );
}
