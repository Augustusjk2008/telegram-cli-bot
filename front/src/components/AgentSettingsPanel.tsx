import { useEffect, useRef, useState } from "react";
import { Pencil, Plus, Save, Trash2 } from "lucide-react";
import type { AgentInput, AgentSummary } from "../services/types";
import type { WebBotClient } from "../services/webBotClient";

type AgentSettingsPanelProps = {
  botAlias: string;
  client: WebBotClient;
  canManage?: boolean;
  className?: string;
};

type FormState = {
  id: string;
  name: string;
  systemPrompt: string;
  enabled: boolean;
  allowCluster: boolean;
  allowWrite: boolean;
  sessionPolicy: "persistent" | "ephemeral" | "fork";
  timeoutSeconds: number;
};

const EMPTY_FORM: FormState = {
  id: "",
  name: "",
  systemPrompt: "",
  enabled: true,
  allowCluster: true,
  allowWrite: false,
  sessionPolicy: "persistent",
  timeoutSeconds: 600,
};

function slugifyAgentName(name: string) {
  const ascii = name.trim().toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return /^[a-z]/.test(ascii) ? ascii.slice(0, 32) : "";
}

function validateForm(form: FormState, editingId: string) {
  if (!editingId && !/^[a-z][a-z0-9_-]{1,31}$/.test(form.id.trim())) {
    return "Agent ID 仅允许小写字母/数字/_/-，2-32 位，以字母开头";
  }
  if (!form.name.trim()) {
    return "名称不能为空";
  }
  if (form.name.trim().length > 32) {
    return "名称不能超过 32 字符";
  }
  if (form.systemPrompt.length > 12000) {
    return "系统提示词不能超过 12000 字符";
  }
  return "";
}

export function AgentSettingsPanel({
  botAlias,
  client,
  canManage = true,
  className = "",
}: AgentSettingsPanelProps) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [editingId, setEditingId] = useState("");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formOpen, setFormOpen] = useState(false);
  const [idTouched, setIdTouched] = useState(false);
  const nameInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    void client.listAgents(botAlias)
      .then((data) => {
        if (!cancelled) {
          setAgents(data.items.length > 0 ? data.items : [{
            id: "main",
            name: "主 agent",
            systemPrompt: "",
            enabled: true,
            isMain: true,
          }]);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message || "加载 agent 失败");
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

  useEffect(() => {
    if (formOpen) {
      nameInputRef.current?.focus();
    }
  }, [formOpen, editingId]);

  const childAgents = agents.filter((agent) => !agent.isMain);
  const formError = validateForm(form, editingId);

  function openCreate() {
    setEditingId("");
    setForm(EMPTY_FORM);
    setFormOpen(true);
    setIdTouched(false);
    setError("");
    setNotice("");
  }

  function openEdit(agent: AgentSummary) {
    setEditingId(agent.id);
    setFormOpen(true);
    setForm({
      id: agent.id,
      name: agent.name,
      systemPrompt: agent.systemPrompt,
      enabled: agent.enabled,
      allowCluster: agent.cluster?.allowCluster ?? true,
      allowWrite: agent.cluster?.allowWrite ?? false,
      sessionPolicy: agent.cluster?.sessionPolicy ?? "persistent",
      timeoutSeconds: agent.cluster?.timeoutSeconds ?? 600,
    });
    setIdTouched(true);
    setError("");
    setNotice("");
  }

  function closeForm() {
    setEditingId("");
    setForm(EMPTY_FORM);
    setFormOpen(false);
    setIdTouched(false);
  }

  async function saveAgent() {
    if (formError) {
      setError(formError);
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const input: AgentInput = {
        name: form.name.trim(),
        systemPrompt: form.systemPrompt,
        enabled: form.enabled,
      };
      if (
        form.allowCluster !== true
        || form.allowWrite !== false
        || form.sessionPolicy !== "persistent"
        || form.timeoutSeconds !== 600
      ) {
        input.cluster = {
          allowCluster: form.allowCluster,
          allowWrite: form.allowWrite,
          sessionPolicy: form.sessionPolicy,
          timeoutSeconds: form.timeoutSeconds,
        };
      }
      const result = editingId
        ? await client.updateAgent(botAlias, editingId, input)
        : await client.createAgent(botAlias, { ...input, id: form.id.trim() });
      setAgents((prev) => {
        if (editingId) {
          return prev.map((agent) => (agent.id === result.agent.id ? result.agent : agent));
        }
        return [...prev, result.agent];
      });
      setNotice(editingId ? "agent 已更新" : "agent 已新增");
      closeForm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 agent 失败");
    } finally {
      setSaving(false);
    }
  }

  async function deleteAgent(agent: AgentSummary) {
    if (!window.confirm("删除后仅移除配置，历史仍保留在该 agent 下")) {
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await client.deleteAgent(botAlias, agent.id);
      setAgents((prev) => prev.filter((item) => item.id !== agent.id));
      setNotice("agent 已删除");
      if (editingId === agent.id) {
        closeForm();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除 agent 失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className={`rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 ${className}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-[var(--text)]">子 agent</h2>
          <p className="text-sm text-[var(--muted)]">提示词改动对新会话生效</p>
        </div>
        {canManage ? (
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            新增 agent
          </button>
        ) : null}
      </div>

      {error ? <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div> : null}
      {notice ? <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{notice}</div> : null}
      {loading ? <div className="mt-4 text-sm text-[var(--muted)]">加载中...</div> : null}

      <div className="mt-4 space-y-2">
        {agents.map((agent) => (
          <div
            key={agent.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium text-[var(--text)]">{agent.name}</span>
                {agent.isMain ? <span className="rounded-full bg-[var(--surface-strong)] px-2 py-0.5 text-xs text-[var(--muted)]">主 agent</span> : null}
                {!agent.enabled ? <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs text-red-700">停用</span> : null}
              </div>
              <div className="mt-0.5 truncate text-xs text-[var(--muted)]">{agent.id}</div>
            </div>
            {!agent.isMain && canManage ? (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => openEdit(agent)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-sm hover:bg-[var(--surface-strong)]"
                >
                  <Pencil className="h-3.5 w-3.5" />
                  编辑
                </button>
                <button
                  type="button"
                  onClick={() => void deleteAgent(agent)}
                  disabled={saving}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 px-2.5 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  删除
                </button>
              </div>
            ) : null}
          </div>
        ))}
        {!loading && childAgents.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--border)] px-3 py-4 text-sm text-[var(--muted)]">
            暂无子 agent
          </div>
        ) : null}
      </div>

      {formOpen ? (
        <div className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="text-sm font-medium text-[var(--text)]">名称</span>
              <input
                ref={nameInputRef}
                aria-label="名称"
                value={form.name}
                onChange={(event) => {
                  const name = event.target.value;
                  setForm((prev) => ({
                    ...prev,
                    name,
                    id: editingId || idTouched ? prev.id : slugifyAgentName(name),
                  }));
                }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm"
              />
            </label>
            <label className="space-y-1">
              <span className="text-sm font-medium text-[var(--text)]">Agent ID</span>
              <input
                aria-label="Agent ID"
                value={form.id}
                disabled={Boolean(editingId)}
                onChange={(event) => {
                  setIdTouched(true);
                  setForm((prev) => ({ ...prev, id: event.target.value.trim().toLowerCase() }));
                }}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm disabled:opacity-60"
              />
            </label>
          </div>
          <div className="mt-3 grid gap-2 border-t border-[var(--border)] pt-3">
            <label className="inline-flex items-center gap-2 text-sm text-[var(--text)]">
              <input
                type="checkbox"
                checked={form.allowCluster}
                onChange={(event) => setForm((prev) => ({ ...prev, allowCluster: event.target.checked }))}
              />
              允许集群调用
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-[var(--text)]">
              <input
                type="checkbox"
                checked={form.allowWrite}
                onChange={(event) => setForm((prev) => ({ ...prev, allowWrite: event.target.checked }))}
              />
              允许修改文件
            </label>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-sm">
                <span className="font-medium text-[var(--text)]">会话策略</span>
                <select
                  aria-label="会话策略"
                  value={form.sessionPolicy}
                  onChange={(event) => setForm((prev) => ({ ...prev, sessionPolicy: event.target.value as FormState["sessionPolicy"] }))}
                  className="h-9 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                >
                  <option value="persistent">persistent</option>
                  <option value="ephemeral">ephemeral</option>
                  <option value="fork">fork</option>
                </select>
              </label>
              <label className="space-y-1 text-sm">
                <span className="font-medium text-[var(--text)]">超时秒数</span>
                <input
                  aria-label="超时秒数"
                  type="number"
                  min={60}
                  max={3600}
                  value={form.timeoutSeconds}
                  onChange={(event) => setForm((prev) => ({ ...prev, timeoutSeconds: Number(event.target.value || 600) }))}
                  className="h-9 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 text-sm"
                />
              </label>
            </div>
          </div>
          <label className="mt-3 block space-y-1">
            <span className="text-sm font-medium text-[var(--text)]">系统提示词</span>
            <textarea
              aria-label="系统提示词"
              rows={6}
              value={form.systemPrompt}
              onChange={(event) => setForm((prev) => ({ ...prev, systemPrompt: event.target.value }))}
              className="w-full resize-y rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm"
            />
          </label>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-3 text-xs text-[var(--muted)]">
            <label className="inline-flex items-center gap-2 text-sm text-[var(--text)]">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(event) => setForm((prev) => ({ ...prev, enabled: event.target.checked }))}
              />
              启用
            </label>
            <span>{form.systemPrompt.length}/12000 · 提示词改动对新会话生效</span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => void saveAgent()}
              disabled={!canManage || saving || Boolean(formError)}
              className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm tcb-solid-accent hover:opacity-90 disabled:opacity-60"
            >
              <Save className="h-4 w-4" />
              {saving ? "保存中..." : "保存"}
            </button>
            <button
              type="button"
              onClick={closeForm}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--surface-strong)]"
            >
              取消
            </button>
            {formError ? <span className="text-sm text-red-700">{formError}</span> : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
