import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import {
  Check,
  Cloud,
  Info,
  Languages,
  LoaderCircle,
  RefreshCw,
  RotateCcw,
  Save,
  SquareTerminal,
  TriangleAlert,
} from "lucide-react";
import type {
  ChatTranslationCliOption,
  ChatTranslationConfig,
  ChatTranslationConfigInput,
  CliParamField,
  CliType,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import { DEFAULT_CHAT_TRANSLATION_CONFIG } from "../utils/chatTranslation";
import { cliTypeLabel, defaultCliPathForType, isCodexCli } from "../utils/cliType";
import { getErrorMessage } from "../utils/errorMessage";
import "./ChatTranslationSettingsPanel.css";

type Method = ChatTranslationConfig["method"];
type ParamDrafts = Record<string, string | boolean>;
type PromptKey = "userPrompt" | "assistantPrompt";

/** Everything the form edits; compared with the loaded configuration to detect unsaved changes. */
type Draft = {
  method: Method;
  translateUser: boolean;
  translateAssistant: boolean;
  baseUrl: string;
  model: string;
  reasoningEffort: ChatTranslationConfig["reasoning_effort"];
  apiKey: string;
  clearApiKey: boolean;
  timeout: string;
  userPrompt: string;
  assistantPrompt: string;
  cliType: CliType;
  cliPath: string;
  /** Each CLI keeps its own parameters, so switching types never mixes them up. */
  cliParams: Partial<Record<CliType, ParamDrafts>>;
};

const CLI_TYPES: CliType[] = ["codex", "codex_server", "claude", "antigravity", "deepseek"];
const METHODS: Array<{ value: Method; label: string; icon: typeof Cloud; description: string }> = [
  { value: "llm", label: "LLM API", icon: Cloud, description: "直接请求 OpenAI 兼容的 Chat Completions 接口。" },
  { value: "cli", label: "本地 CLI", icon: SquareTerminal, description: "运行本机 CLI 完成翻译，与各 Bot 自己的 CLI 配置相互独立。" },
];
const REASONING_EFFORTS: Array<{ value: Draft["reasoningEffort"]; label: string }> = [
  { value: "none", label: "无 (none)" },
  { value: "low", label: "低 (low)" },
  { value: "medium", label: "中 (medium)" },
  { value: "high", label: "高 (high)" },
];
const PROMPTS: Array<{ key: PromptKey; label: string }> = [
  { key: "userPrompt", label: "用户消息翻译提示词" },
  { key: "assistantPrompt", label: "Bot 回答翻译提示词" },
];
/** In option lists "none" stands for the CLI's own default. */
const OPTION_NONE = "none";
const FIELD_CLASS = "w-full border px-3 py-2 text-sm";
const SPIN = " animate-spin motion-reduce:animate-none";

function paramDrafts(option: ChatTranslationCliOption): ParamDrafts {
  const drafts: ParamDrafts = {};
  for (const [key, field] of Object.entries(option.schema)) {
    const value = option.params[key];
    if (field.type === "boolean") {
      drafts[key] = Boolean(value);
    } else if (field.type === "string_list") {
      drafts[key] = Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
    } else if (value == null || value === "") {
      drafts[key] = field.enum?.includes(OPTION_NONE) ? OPTION_NONE : "";
    } else {
      drafts[key] = String(value);
    }
  }
  return drafts;
}

function paramRequestValue(field: CliParamField, value: string | boolean): unknown {
  if (field.type === "boolean") {
    return Boolean(value);
  }
  const text = String(value);
  if (field.type === "string_list") {
    return text.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  }
  if (field.type === "number") {
    return text.trim() ? Number(text) : null;
  }
  // The backend stores "no choice" as null; a literal "none" would reach the CLI as a model name.
  return field.nullable && (!text.trim() || text === OPTION_NONE) ? null : text;
}

function draftFromConfig(config: ChatTranslationConfig): Draft {
  const cliParams: Draft["cliParams"] = {};
  for (const [cliType, option] of Object.entries(config.cli_options)) {
    if (option) {
      cliParams[cliType as CliType] = paramDrafts(option);
    }
  }
  return {
    method: config.method,
    translateUser: config.translate_user_enabled,
    translateAssistant: config.translate_assistant_enabled,
    baseUrl: config.base_url,
    model: config.model,
    reasoningEffort: config.reasoning_effort,
    apiKey: "",
    clearApiKey: false,
    timeout: String(config.request_timeout_seconds || ""),
    userPrompt: config.user_prompt ?? "",
    assistantPrompt: config.assistant_prompt ?? "",
    cliType: config.cli_type,
    cliPath: config.cli_path,
    cliParams,
  };
}

/** Provider, model and effort lead the CLI form in that order; other parameters sit under "高级参数". */
function primaryParamRank(key: string) {
  if (key === "provider") return 0;
  if (key === "model") return 1;
  return key.endsWith("effort") ? 2 : -1;
}

function optionLabel(option: string) {
  return option === OPTION_NONE ? "默认 (none)" : option;
}

type FieldProps = {
  id: string;
  label: string;
  /** A quiet text action shown beside the label. */
  action?: ReactNode;
  children: ReactNode;
};

function Field({ id, label, action, children }: FieldProps) {
  return (
    <div className="translation-field">
      <span className="translation-field-head">
        <label htmlFor={id} className="translation-field-label" title={label}>{label}</label>
        {action}
      </span>
      {children}
    </div>
  );
}

type ParamFieldProps = {
  id: string;
  field: CliParamField;
  label: string;
  value: string;
  onChange: (value: string) => void;
};

function ParamField({ id, field, label, value, onChange }: ParamFieldProps) {
  // A saved value outside the current option list stays selectable instead of silently changing.
  const options = field.enum && value && !field.enum.includes(value) ? [value, ...field.enum] : field.enum;
  return (
    <Field id={id} label={label}>
      {options ? (
        <select id={id} value={value} onChange={(event) => onChange(event.target.value)} className={FIELD_CLASS}>
          {options.map((option) => <option key={option} value={option}>{optionLabel(option)}</option>)}
        </select>
      ) : (
        <input
          id={id}
          type={field.type === "number" ? "number" : "text"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={FIELD_CLASS}
        />
      )}
    </Field>
  );
}

type Props = {
  client: WebBotClient;
  onSaved?: () => void;
};

/** Admin Center → 翻译: the global chat translation switches, engine and prompts. */
export function ChatTranslationSettingsPanel({ client, onSaved }: Props) {
  const [config, setConfig] = useState<ChatTranslationConfig | null>(null);
  const [draft, setDraft] = useState<Draft>(() => draftFromConfig(DEFAULT_CHAT_TRANSLATION_CONFIG));
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const uid = useId();

  useEffect(() => {
    let active = true;
    setLoadError("");
    void client.getChatTranslationConfig().then((next) => {
      if (active) {
        setConfig(next);
        setDraft(draftFromConfig(next));
      }
    }).catch((error: unknown) => {
      if (active) setLoadError(getErrorMessage(error, "加载聊天翻译配置失败"));
    });
    return () => { active = false; };
  }, [client, reloadKey]);

  const base = useMemo(() => draftFromConfig(config ?? DEFAULT_CHAT_TRANSLATION_CONFIG), [config]);
  const dirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(base), [base, draft]);

  const update = (patch: Partial<Draft>) => {
    setDraft((previous) => ({ ...previous, ...patch }));
    setSaveError("");
  };

  const cliOption = config?.cli_options[draft.cliType];
  const cliEntries = Object.entries(cliOption?.schema ?? {});
  const cliDrafts = draft.cliParams[draft.cliType] ?? {};
  const baseCliDrafts = base.cliParams[draft.cliType] ?? {};
  const updateParam = (key: string, value: string | boolean) => {
    update({ cliParams: { ...draft.cliParams, [draft.cliType]: { ...cliDrafts, [key]: value } } });
  };
  const changeCliType = (next: CliType) => {
    // codex and codex server run the same executable; any other switch starts from that CLI's command.
    const keepPath = isCodexCli(draft.cliType) && isCodexCli(next);
    update({
      cliType: next,
      cliPath: keepPath ? draft.cliPath : next === base.cliType ? base.cliPath : defaultCliPathForType(next),
    });
  };

  const enabled = draft.translateUser || draft.translateAssistant;
  const timeoutSeconds = Number(draft.timeout);

  const save = async () => {
    if (!config) return;
    if (enabled && draft.method === "llm" && (!draft.baseUrl.trim() || !draft.model.trim()
      || !(draft.apiKey.trim() || (config.api_key_configured && !draft.clearApiKey)))) {
      setSaveError("启用翻译时，请填写服务地址、模型和 API 密钥。");
      return;
    }
    if (enabled && draft.method === "cli" && !draft.cliPath.trim()) {
      setSaveError("启用翻译时，请填写 CLI 路径。");
      return;
    }
    if (!draft.timeout.trim() || !Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0) {
      setSaveError("超时秒数必须大于 0。");
      return;
    }
    const changedParams: Record<string, unknown> = {};
    for (const [key, field] of cliEntries) {
      if (key in cliDrafts && cliDrafts[key] !== baseCliDrafts[key]) {
        changedParams[key] = paramRequestValue(field, cliDrafts[key]);
      }
    }
    const cliChanged = draft.cliType !== base.cliType || draft.cliPath !== base.cliPath || Object.keys(changedParams).length > 0;
    const input: ChatTranslationConfigInput = {
      method: draft.method,
      user_prompt: draft.userPrompt,
      assistant_prompt: draft.assistantPrompt,
      translate_user_enabled: draft.translateUser,
      translate_assistant_enabled: draft.translateAssistant,
      base_url: draft.baseUrl.trim(),
      model: draft.model.trim(),
      reasoning_effort: draft.reasoningEffort,
      request_timeout_seconds: timeoutSeconds,
      api_key: draft.clearApiKey ? "" : draft.apiKey.trim(),
      ...(draft.clearApiKey ? { clear_api_key: true } : {}),
      // The CLI settings travel with the request whenever the CLI is in use or was edited.
      ...(draft.method === "cli" || cliChanged
        ? { cli_type: draft.cliType, cli_path: draft.cliPath.trim(), cli_params: changedParams }
        : {}),
    };
    setSaving(true);
    setSaveError("");
    try {
      const next = await client.updateChatTranslationConfig(input);
      setConfig(next);
      setDraft(draftFromConfig(next));
      setSaved(true);
      onSaved?.();
    } catch (error) {
      setSaveError(getErrorMessage(error, "保存聊天翻译配置失败"));
    } finally {
      setSaving(false);
    }
  };

  const savedEnabled = Boolean(config && (config.translate_user_enabled || config.translate_assistant_enabled));
  const method = METHODS.find((item) => item.value === draft.method) ?? METHODS[0];
  const valueEntries = cliEntries.filter(([, field]) => field.type !== "boolean" && field.type !== "string_list");
  const primaryEntries = valueEntries
    .filter(([key]) => primaryParamRank(key) >= 0)
    .sort(([left], [right]) => primaryParamRank(left) - primaryParamRank(right));
  const otherEntries = valueEntries.filter(([key]) => primaryParamRank(key) < 0);
  const switchEntries = cliEntries.filter(([, field]) => field.type === "boolean");
  const listEntries = cliEntries.filter(([, field]) => field.type === "string_list");
  const hasAdvanced = otherEntries.length + switchEntries.length + listEntries.length > 0;
  const paramId = (key: string) => `${uid}-cli-${draft.cliType}-${key}`;
  const paramLabel = (key: string, field: CliParamField) => field.description || key;

  return (
    <section
      aria-labelledby={`${uid}-title`}
      data-tone={savedEnabled ? "accent" : undefined}
      className="admin-island orbit-island orbit-island--reading translation-island"
    >
      <header className="translation-head">
        <span className="translation-head-icon" aria-hidden="true"><Languages className="h-4 w-4" /></span>
        <div className="translation-head-copy">
          <h2 id={`${uid}-title`}>聊天翻译</h2>
          {config || loadError ? (
            <p>对所有 Bot 生效；每个 Bot 可在历史会话面板单独关闭。</p>
          ) : (
            <p role="status">正在加载聊天翻译配置...</p>
          )}
        </div>
        {config ? (
          <span role="status" className="orbit-chip" data-tone={savedEnabled ? "success" : undefined}>
            <span className="translation-dot" aria-hidden="true" />
            <span className="sr-only">当前状态: </span>
            {savedEnabled ? `已启用 · ${config.method === "cli" ? "本地 CLI" : "LLM API"}` : "未启用"}
          </span>
        ) : null}
      </header>

      {loadError ? (
        <div role="alert" className="admin-callout translation-callout" data-tone="danger">
          <TriangleAlert className="h-4 w-4 flex-none" aria-hidden="true" />
          <span className="translation-callout-body">{loadError}</span>
          <button type="button" className="orbit-btn orbit-btn--secondary orbit-btn--sm" onClick={() => setReloadKey((key) => key + 1)}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            重新加载
          </button>
        </div>
      ) : null}

      {config ? (
        <fieldset disabled={saving} className="translation-form">
          <div className="translation-toggles">
            {([
              ["translateUser", "翻译提问", "发送前翻译，Agent 收到的是译文；翻译失败时发送原文。"],
              ["translateAssistant", "翻译最终回答", "回答完成后在后台翻译，可在消息上切换原文与译文。"],
            ] as const).map(([key, label, hint]) => (
              <div key={key} className="translation-toggle" data-on={draft[key] || undefined}>
                <label className="translation-toggle-row">
                  {label}
                  <input
                    type="checkbox"
                    checked={draft[key]}
                    aria-describedby={`${uid}-${key}-hint`}
                    onChange={(event) => update({ [key]: event.target.checked })}
                  />
                </label>
                <p id={`${uid}-${key}-hint`} className="translation-toggle-hint">{hint}</p>
              </div>
            ))}
          </div>

          <section aria-labelledby={`${uid}-engine`} className="translation-section">
            <div className="translation-section-head">
              <div className="translation-section-copy">
                <h3 id={`${uid}-engine`}>翻译引擎</h3>
                <p>{method.description}</p>
              </div>
              <div role="group" aria-label="翻译实现方式" className="orbit-segmented orbit-segmented--accent translation-segmented">
                {METHODS.map(({ value, label, icon: Icon }) => (
                  <button key={value} type="button" aria-pressed={draft.method === value} onClick={() => update({ method: value })}>
                    <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="translation-engine">
              {draft.method === "llm" ? (
                <>
                  <div className="translation-grid">
                    <Field id={`${uid}-base-url`} label="翻译服务地址">
                      <input
                        id={`${uid}-base-url`}
                        className={FIELD_CLASS}
                        value={draft.baseUrl}
                        placeholder="https://api.example.com/v1"
                        onChange={(event) => update({ baseUrl: event.target.value })}
                      />
                    </Field>
                    <Field id={`${uid}-model`} label="翻译模型">
                      <input
                        id={`${uid}-model`}
                        className={FIELD_CLASS}
                        value={draft.model}
                        onChange={(event) => update({ model: event.target.value })}
                      />
                    </Field>
                    <Field
                      id={`${uid}-api-key`}
                      label="翻译 API 密钥"
                      action={config.api_key_configured ? (
                        <button
                          type="button"
                          aria-pressed={draft.clearApiKey}
                          className="translation-field-action"
                          onClick={() => update({ clearApiKey: !draft.clearApiKey, apiKey: "" })}
                        >
                          {draft.clearApiKey ? "撤销清除" : "清除已保存的密钥"}
                        </button>
                      ) : null}
                    >
                      <input
                        id={`${uid}-api-key`}
                        className={FIELD_CLASS}
                        type="password"
                        autoComplete="new-password"
                        value={draft.apiKey}
                        disabled={draft.clearApiKey}
                        placeholder={draft.clearApiKey ? "保存后清除" : config.api_key_configured ? "已保存，留空保留" : "尚未配置"}
                        onChange={(event) => update({ apiKey: event.target.value })}
                      />
                    </Field>
                    <Field id={`${uid}-reasoning`} label="翻译推理深度">
                      <select
                        id={`${uid}-reasoning`}
                        className={FIELD_CLASS}
                        value={draft.reasoningEffort}
                        onChange={(event) => update({ reasoningEffort: event.target.value as Draft["reasoningEffort"] })}
                      >
                        {REASONING_EFFORTS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </Field>
                  </div>
                  <p className="translation-note">
                    <Info className="h-3.5 w-3.5" aria-hidden="true" />
                    Git 提交说明选择 LLM API 时，也使用这里的服务地址、模型和密钥。
                  </p>
                </>
              ) : (
                <>
                  <div className="translation-grid">
                    <Field id={`${uid}-cli-type`} label="CLI 类型">
                      <select
                        id={`${uid}-cli-type`}
                        className={FIELD_CLASS}
                        value={draft.cliType}
                        onChange={(event) => changeCliType(event.target.value as CliType)}
                      >
                        {CLI_TYPES.map((cliType) => <option key={cliType} value={cliType}>{cliTypeLabel(cliType)}</option>)}
                      </select>
                    </Field>
                    <Field id={`${uid}-cli-path`} label="CLI 路径">
                      <input
                        id={`${uid}-cli-path`}
                        className={`${FIELD_CLASS} translation-mono`}
                        value={draft.cliPath}
                        placeholder={defaultCliPathForType(draft.cliType)}
                        onChange={(event) => update({ cliPath: event.target.value })}
                      />
                    </Field>
                    {primaryEntries.map(([key, field]) => (
                      <ParamField
                        key={key}
                        id={paramId(key)}
                        field={field}
                        label={paramLabel(key, field)}
                        value={String(cliDrafts[key] ?? "")}
                        onChange={(value) => updateParam(key, value)}
                      />
                    ))}
                  </div>

                  {hasAdvanced ? (
                    <div className="translation-advanced">
                      <span className="translation-caption">高级参数</span>
                      {otherEntries.length > 0 ? (
                        <div className="translation-grid">
                          {otherEntries.map(([key, field]) => (
                            <ParamField
                              key={key}
                              id={paramId(key)}
                              field={field}
                              label={paramLabel(key, field)}
                              value={String(cliDrafts[key] ?? "")}
                              onChange={(value) => updateParam(key, value)}
                            />
                          ))}
                        </div>
                      ) : null}
                      {switchEntries.length > 0 ? (
                        <div className="translation-switches">
                          {switchEntries.map(([key, field]) => (
                            <label key={key} className="admin-toggle">
                              <input
                                type="checkbox"
                                checked={Boolean(cliDrafts[key])}
                                onChange={(event) => updateParam(key, event.target.checked)}
                              />
                              <span className="admin-toggle-label" title={paramLabel(key, field)}>{paramLabel(key, field)}</span>
                            </label>
                          ))}
                        </div>
                      ) : null}
                      {listEntries.map(([key, field]) => (
                        <Field key={key} id={paramId(key)} label={paramLabel(key, field)}>
                          <textarea
                            id={paramId(key)}
                            rows={2}
                            value={String(cliDrafts[key] ?? "")}
                            placeholder="每行一个参数"
                            onChange={(event) => updateParam(key, event.target.value)}
                            className={`${FIELD_CLASS} translation-mono translation-args`}
                          />
                        </Field>
                      ))}
                    </div>
                  ) : null}
                </>
              )}

              <div className="translation-timeout">
                <Field id={`${uid}-timeout`} label="翻译超时（秒）">
                  <input
                    id={`${uid}-timeout`}
                    className={FIELD_CLASS}
                    type="number"
                    min="0.1"
                    step="any"
                    value={draft.timeout}
                    aria-describedby={`${uid}-timeout-hint`}
                    onChange={(event) => update({ timeout: event.target.value })}
                  />
                </Field>
                <p id={`${uid}-timeout-hint`} className="translation-field-hint">
                  {draft.method === "cli"
                    ? "单次翻译的最长等待时间。CLI 每次都要启动进程，需要比 API 更长的超时。"
                    : "单次翻译的最长等待时间，超时后保留原文。"}
                </p>
              </div>
            </div>
          </section>

          <section aria-labelledby={`${uid}-prompts`} className="translation-section">
            <div className="translation-section-head">
              <div className="translation-section-copy">
                <h3 id={`${uid}-prompts`}>翻译提示词</h3>
                <p>目标语言和保留规则都由提示词决定，两个方向分别配置。</p>
              </div>
            </div>
            <div className="translation-prompts">
              {PROMPTS.map(({ key, label }) => (
                <Field
                  key={key}
                  id={`${uid}-${key}`}
                  label={label}
                  action={(
                    <button
                      type="button"
                      aria-label={`${label}恢复默认`}
                      className="translation-field-action"
                      disabled={!draft[key]}
                      onClick={() => update({ [key]: "" })}
                    >
                      恢复默认
                    </button>
                  )}
                >
                  <textarea
                    id={`${uid}-${key}`}
                    className={`${FIELD_CLASS} translation-prompt`}
                    rows={10}
                    value={draft[key]}
                    placeholder="留空并保存，即恢复默认提示词"
                    onChange={(event) => update({ [key]: event.target.value })}
                  />
                </Field>
              ))}
            </div>
          </section>

          {saveError ? (
            <div role="alert" className="admin-callout translation-callout" data-tone="danger">
              <TriangleAlert className="h-4 w-4 flex-none" aria-hidden="true" />
              <span className="translation-callout-body">{saveError}</span>
            </div>
          ) : null}

          <footer className="translation-foot">
            <p className="translation-foot-note" data-tone={dirty ? "pending" : saved ? "success" : undefined}>
              {!dirty && saved
                ? <Check className="h-3.5 w-3.5" aria-hidden="true" />
                : <Info className="h-3.5 w-3.5" aria-hidden="true" />}
              {dirty ? "有尚未保存的更改。" : saved ? "已保存，下一条消息开始生效。" : "保存后从下一条消息开始生效，无需重启。"}
            </p>
            <div className="translation-foot-actions">
              <button type="button" className="orbit-btn orbit-btn--ghost" disabled={!dirty} onClick={() => { setDraft(base); setSaveError(""); }}>
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
                放弃更改
              </button>
              <button type="button" className="orbit-btn orbit-btn--primary" disabled={!dirty} onClick={() => void save()}>
                {saving
                  ? <LoaderCircle className={`h-4 w-4${SPIN}`} aria-hidden="true" />
                  : <Save className="h-4 w-4" aria-hidden="true" />}
                {saving ? "保存中..." : "保存聊天翻译配置"}
              </button>
            </div>
          </footer>
        </fieldset>
      ) : null}
    </section>
  );
}
