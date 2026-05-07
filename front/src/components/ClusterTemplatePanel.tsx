import { useEffect, useState } from "react";
import type {
  ClusterBundlePreviewResult,
  ClusterBundleSchemaResult,
  ClusterTemplateSummary,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type Props = {
  botAlias: string;
  client: WebBotClient;
  canManage?: boolean;
  onApplied: () => void;
};

function defaultJsonText() {
  return JSON.stringify(
    {
      id: "custom_review",
      name: "自定义集群",
      description: "",
      cluster: {
        enabled: true,
        writePolicy: "main_only",
        conflictPolicy: "snapshot_diff",
        maxParallelAgents: 1,
        defaultTimeoutSeconds: 600,
        modelTiers: { low: "", medium: "", high: "" },
      },
      agents: [
        {
          id: "tester",
          name: "测试",
          systemPrompt: "",
          enabled: true,
          cluster: {
            allowCluster: true,
            allowWrite: false,
            sessionPolicy: "ephemeral",
            timeoutSeconds: 600,
          },
        },
      ],
    },
    null,
    2,
  );
}

function DiffSection({
  label,
  items,
}: {
  label: string;
  items: string[];
}) {
  return (
    <div>
      <div className="text-sm font-medium text-[var(--text)]">{label}</div>
      {items.length > 0 ? (
        <div className="mt-1 flex flex-wrap gap-1">
          {items.map((item) => (
            <span key={`${label}:${item}`} className="rounded border border-[var(--border)] px-2 py-1 text-xs text-[var(--muted)]">
              {item}
            </span>
          ))}
        </div>
      ) : (
        <div className="mt-1 text-xs text-[var(--muted)]">无</div>
      )}
    </div>
  );
}

function PreviewPanel({
  preview,
}: {
  preview: ClusterBundlePreviewResult;
}) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text)]">{preview.bundle.name}</h3>
          <p className="mt-1 text-xs text-[var(--muted)]">{preview.bundle.description || "无描述"}</p>
        </div>
      </div>
      <div className="mt-3 grid gap-3">
        <DiffSection label="将删除" items={preview.diff.deleteAgents} />
        <DiffSection label="将新增" items={preview.diff.createAgents} />
        <DiffSection label="将修改" items={preview.diff.updateAgents} />
        <div>
          <div className="text-sm font-medium text-[var(--text)]">集群配置变化</div>
          {Object.keys(preview.diff.clusterChanges).length > 0 ? (
            <div className="mt-1 grid gap-1 text-xs text-[var(--muted)]">
              {Object.entries(preview.diff.clusterChanges).map(([key, value]) => (
                <div key={key}>{key}: {String(value.before)} {"->"} {String(value.after)}</div>
              ))}
            </div>
          ) : (
            <div className="mt-1 text-xs text-[var(--muted)]">无</div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ClusterTemplatePanel({ botAlias, client, canManage = true, onApplied }: Props) {
  const [tab, setTab] = useState<"templates" | "json">("templates");
  const [templates, setTemplates] = useState<ClusterTemplateSummary[]>([]);
  const [schema, setSchema] = useState<ClusterBundleSchemaResult | null>(null);
  const [preview, setPreview] = useState<ClusterBundlePreviewResult | null>(null);
  const [previewTemplateId, setPreviewTemplateId] = useState("");
  const [jsonText, setJsonText] = useState(defaultJsonText);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setPreview(null);
    setPreviewTemplateId("");
    void Promise.all([
      client.getClusterTemplates(botAlias),
      client.getClusterBundleSchema(botAlias),
    ])
      .then(([templatesResult, schemaResult]) => {
        if (cancelled) return;
        setTemplates(templatesResult.templates);
        setSchema(schemaResult);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "加载集群模板失败");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [botAlias, client]);

  async function previewTemplate(templateId: string) {
    setLoading(true);
    setError("");
    try {
      setPreview(await client.previewClusterTemplate(botAlias, templateId));
      setPreviewTemplateId(templateId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "预览模板失败");
    } finally {
      setLoading(false);
    }
  }

  async function applyTemplate(templateId: string) {
    if (!window.confirm("应用后会覆盖当前 Bot 的子 agent 配置。确定继续吗？")) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      await client.applyClusterTemplate(botAlias, templateId, true);
      onApplied();
    } catch (err) {
      setError(err instanceof Error ? err.message : "应用模板失败");
    } finally {
      setLoading(false);
    }
  }

  async function previewJson() {
    setLoading(true);
    setError("");
    try {
      setPreview(await client.previewClusterConfigBundle(botAlias, JSON.parse(jsonText)));
      setPreviewTemplateId("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "预览 JSON 配置失败");
    } finally {
      setLoading(false);
    }
  }

  async function applyJson() {
    if (!window.confirm("应用后会覆盖当前 Bot 的子 agent 配置。确定继续吗？")) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      await client.applyClusterConfigBundle(botAlias, JSON.parse(jsonText), true);
      onApplied();
    } catch (err) {
      setError(err instanceof Error ? err.message : "应用 JSON 配置失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-[var(--text)]">集群模板</h2>
          <p className="mt-1 text-sm text-[var(--muted)]">模板会覆盖当前 Bot 子 agent 配置。</p>
        </div>
        <div className="inline-flex rounded-md border border-[var(--border)] bg-[var(--surface-strong)] p-0.5">
          <button
            type="button"
            aria-pressed={tab === "templates"}
            onClick={() => setTab("templates")}
            className={tab === "templates" ? "rounded px-2 py-1 text-xs bg-[var(--accent)] text-white" : "rounded px-2 py-1 text-xs text-[var(--muted)]"}
          >
            模板
          </button>
          <button
            type="button"
            aria-pressed={tab === "json"}
            onClick={() => setTab("json")}
            className={tab === "json" ? "rounded px-2 py-1 text-xs bg-[var(--accent)] text-white" : "rounded px-2 py-1 text-xs text-[var(--muted)]"}
          >
            JSON 配置
          </button>
        </div>
      </div>
      {schema?.instructions ? <div className="mt-3 text-xs text-[var(--muted)]">{schema.instructions}</div> : null}
      {error ? <div className="mt-3 text-sm text-red-700">{error}</div> : null}
      {loading ? <div className="mt-3 text-sm text-[var(--muted)]">处理中</div> : null}
      {tab === "templates" ? (
        <div className="mt-4 grid gap-3">
          {templates.map((template) => (
            <div key={template.id} className="rounded-md border border-[var(--border)] p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-[var(--text)]">{template.name}</div>
                  <div className="mt-1 text-xs text-[var(--muted)]">{template.description}</div>
                  <div className="mt-2 text-xs text-[var(--muted)]">
                    {template.agentCount} agent，{template.maxParallelAgents} 并发，可写 {template.writeAgentCount}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void previewTemplate(template.id)}
                    className="rounded-md border border-[var(--border)] px-3 py-2 text-sm"
                  >
                    {`预览 ${template.name}`}
                  </button>
                  {previewTemplateId === template.id && preview ? (
                    <button
                      type="button"
                      onClick={() => void applyTemplate(template.id)}
                      disabled={!canManage}
                      className="rounded-md bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-60"
                    >
                      {`覆盖应用 ${preview.bundle.name}`}
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <label className="grid gap-1 text-sm">
            <span className="text-[var(--text)]">集群 JSON 配置</span>
            <textarea
              aria-label="集群 JSON 配置"
              value={jsonText}
              onChange={(event) => setJsonText(event.target.value)}
              className="min-h-[220px] rounded-md border border-[var(--border)] bg-[var(--bg)] p-3 font-mono text-xs"
            />
          </label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void previewJson()}
              className="rounded-md border border-[var(--border)] px-3 py-2 text-sm"
            >
              预览 JSON 配置
            </button>
            <button
              type="button"
              onClick={() => void applyJson()}
              disabled={!canManage}
              className="rounded-md bg-[var(--accent)] px-3 py-2 text-sm text-white disabled:opacity-60"
            >
              覆盖应用 JSON 配置
            </button>
          </div>
        </div>
      )}
      {preview ? (
        <div className="mt-4">
          <PreviewPanel preview={preview} />
        </div>
      ) : null}
    </section>
  );
}
