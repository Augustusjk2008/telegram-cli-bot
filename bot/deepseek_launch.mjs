import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const launcherArgs = process.argv.slice(2);
const desktop = launcherArgs[0] === "--desktop";
const entry = desktop ? launcherArgs[1] : launcherArgs[0];
const selectionJson = desktop ? launcherArgs[2] : launcherArgs[1];
const args = launcherArgs.slice(desktop ? 3 : 2);
const selection = normalizeSelection(JSON.parse(selectionJson));
let patchDirectory;

const runtimeBin = dirname(process.execPath);
const pathValue = process.env.PATH || "";
const pathEntries = pathValue.split(delimiter);
if (!pathEntries.some((item) => item.toLowerCase() === runtimeBin.toLowerCase())) {
  process.env.PATH = [runtimeBin, pathValue].filter(Boolean).join(delimiter);
}

const DUMP_CONFIG_MAX_BYTES = 2 * 1024 * 1024;
const CATALOG_MAX_BYTES = 512 * 1024;
const CATALOG_MAX_PROVIDERS = 128;
const CATALOG_MAX_MODELS = 256;
const BRIDGED_ENTRY_IDS = new Set(["agent-default-model", "credentials", "llm-pi-ai", "llm-deepseek"]);

function findModelEntry(entries) {
  for (const row of entries) {
    if (row.name === "@deepseek-ai/dsh-agent-default-model" && row.disabled !== true) return row;
    if (row.group && Array.isArray(row.config)) {
      const found = findModelEntry(row.config);
      if (found) return found;
    }
  }
}

function isDescribeModels() {
  return args.includes("--describe-models");
}

function normalizeSelection(selectionValue) {
  const result = {};
  if (!selectionValue || typeof selectionValue !== "object" || Array.isArray(selectionValue)) return result;
  for (const [source, target] of [["provider", "provider"], ["model", "model"], ["reasoning_effort", "reasoningEffort"], ["reasoningEffort", "reasoningEffort"]]) {
    const value = selectionValue[source];
    if (typeof value === "string" && value.trim() && value.trim().toLowerCase() !== "none") result[target] = value.trim();
  }
  return result;
}

function diagnosticText(error) {
  return String(error?.message || error || "DeepSeek catalog 读取失败")
    .replace(/((?:api[_-]?key|token|secret|password|authorization|credential)[^\s:=]*)\s*[:=]\s*[^\s,;]+/gi, "$1=[redacted]")
    .replace(/\r?\n/g, " ")
    .slice(0, 512);
}

function safeBridgeValue(value, key = "", depth = 0) {
  if (depth > 8) return undefined;
  if (value === null || typeof value === "boolean" || typeof value === "number") return value;
  if (typeof value === "string") {
    if (/^(?:api[_-]?key|token|secret|password|authorization|cookie|value)$/i.test(key)) return undefined;
    if (/api[_-]?key|token|secret|password|authorization|cookie/i.test(key) && key !== "apiKeyEnv") return undefined;
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => safeBridgeValue(item, key, depth + 1)).filter((item) => item !== undefined);
  }
  if (!value || typeof value !== "object") return undefined;
  const result = {};
  for (const [childKey, childValue] of Object.entries(value)) {
    if (/^(?:api[_-]?key|token|secret|password|authorization|cookie|headers?)$/i.test(childKey)) continue;
    const safe = safeBridgeValue(childValue, childKey, depth + 1);
    if (safe !== undefined) result[childKey] = safe;
  }
  return result;
}

function safeBridgeEntry(entry) {
  if (!entry || typeof entry !== "object") return undefined;
  const id = typeof entry.id === "string" ? entry.id : "";
  const name = typeof entry.name === "string" ? entry.name : "";
  if (!id || !name || !BRIDGED_ENTRY_IDS.has(id)) return undefined;
  const result = { id, name };
  if (entry.disabled === true) result.disabled = true;
  if (entry.config && typeof entry.config === "object" && !Array.isArray(entry.config) && !entry.config.__jsExpr) {
    const config = safeBridgeValue(entry.config, "config");
    if (config && typeof config === "object" && Object.keys(config).length) result.config = config;
  }
  return result;
}

async function loadHeadlessProfile({ includeOverlays = true } = {}) {
  const require = createRequire(pathToFileURL(entry));
  const boot = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-app-boot")));
  const { resolveDshHome } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-home-paths")));
  const installAnchor = join(dirname(entry), "..", "package.json");
  const profile = boot.loadProfile("dsh", "headless", installAnchor);
  const overlays = [];
  if (includeOverlays) {
    for (let index = 2; index < args.length && args[index] === "--patch"; index += 2) {
      overlays.push(...boot.loadOverlayPatches("dsh", resolve(args[index + 1])));
    }
  }
  const patches = boot.readProfilePatches("dsh", {
    dir: profile.dir, patchPath: profile.patchPath, installAnchor,
    home: resolveDshHome(), overlays, telemetryDisabledEnv: process.env.DSH_TELEMETRY_DISABLED,
  }, profile);
  return { boot, profile, patches, entries: boot.composeEntries([patches]) };
}

async function loadDesktopProfileEntries() {
  const require = createRequire(pathToFileURL(entry));
  const boot = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-app-boot")));
  const { resolveDshHome } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-home-paths")));
  const installAnchor = join(dirname(entry), "..", "package.json");
  const profileDir = join(resolveDshHome(), "profiles", "desktop");
  let profile;
  if (typeof boot.loadProfileDirectory === "function") {
    profile = boot.loadProfileDirectory("dsh", profileDir, installAnchor);
  } else {
    profile = boot.loadProfile("dsh", "desktop", installAnchor);
  }
  const patches = [
    ...profile.layers.flatMap((layer) => layer.patches || []),
    ...(profile.patches || []),
  ];
  return { boot, profile, entries: boot.composeEntries([patches]) };
}

async function loadModelEntry() {
  const profile = await loadHeadlessProfile();
  return findModelEntry(profile.entries);
}

function normalizeEfforts(value) {
  if (Array.isArray(value)) return [...new Set(value.map((item) => String(item || "").trim()).filter(Boolean))];
  if (value && typeof value === "object") return [...new Set(Object.keys(value).map((item) => item.trim()).filter(Boolean))];
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}

function catalogModelOptions(provider, source) {
  const models = [];
  const add = (raw, fallbackId = "") => {
    if (typeof raw === "string") {
      const id = raw.trim();
      if (id) models.push({ id, label: id });
      return;
    }
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return;
    const id = String(raw.id || fallbackId || "").trim();
    if (!id) return;
    const efforts = normalizeEfforts(raw.reasoningEfforts ?? raw.reasoning_efforts ?? raw.reasoning);
    const defaultReasoningEffort = String(raw.defaultReasoningEffort ?? raw.default_reasoning_effort ?? raw.reasoningEffort ?? "").trim();
    models.push({
      id,
      label: String(raw.label || raw.name || id).trim() || id,
      ...(efforts.length ? { reasoningEfforts: efforts } : {}),
      ...(defaultReasoningEffort ? { defaultReasoningEffort } : {}),
    });
  };
  const configured = source?.models;
  if (Array.isArray(configured)) configured.forEach((item) => add(item));
  else if (configured && typeof configured === "object") Object.entries(configured).forEach(([id, item]) => add(item, id));
  const overrides = source?.modelOverrides;
  if (overrides && typeof overrides === "object" && !Array.isArray(overrides)) {
    Object.entries(overrides).forEach(([id, item]) => add(item, id));
  }
  const seen = new Set();
  return models.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  }).slice(0, CATALOG_MAX_MODELS);
}

function collectModelCatalog(entries) {
  let selectedProvider = "";
  let selectedModel = "";
  const providerMap = new Map();
  const ensureProvider = (id, source = {}) => {
    const providerId = String(id || "").trim();
    if (!providerId) return undefined;
    let current = providerMap.get(providerId);
    if (!current) {
      current = {
        id: providerId,
        label: String(source.displayName || source.label || providerId).trim() || providerId,
        models: [],
        reasoningEfforts: normalizeEfforts(source.reasoningEfforts ?? source.reasoning_efforts ?? source.reasoning),
        defaultModel: String(source.defaultModel || source.default_model || source.model || "").trim(),
        defaultReasoningEffort: String(source.defaultReasoningEffort || source.default_reasoning_effort || source.reasoningEffort || "").trim(),
      };
      providerMap.set(providerId, current);
    } else {
      current.label = String(source.displayName || source.label || current.label).trim() || current.label;
      current.reasoningEfforts = [...new Set([...current.reasoningEfforts, ...normalizeEfforts(source.reasoningEfforts ?? source.reasoning_efforts ?? source.reasoning)])];
      current.defaultModel ||= String(source.defaultModel || source.default_model || source.model || "").trim();
      current.defaultReasoningEffort ||= String(source.defaultReasoningEffort || source.default_reasoning_effort || source.reasoningEffort || "").trim();
    }
    const modelOptions = catalogModelOptions(providerId, source);
    const seen = new Set(current.models.map((item) => item.id));
    for (const item of modelOptions) if (!seen.has(item.id)) current.models.push(item);
    if (!current.defaultModel && current.models[0]) current.defaultModel = current.models[0].id;
    if (!current.defaultReasoningEffort && current.models[0]?.defaultReasoningEffort) current.defaultReasoningEffort = current.models[0].defaultReasoningEffort;
    return current;
  };

  for (const row of Array.isArray(entries) ? entries : []) {
    if (!row || typeof row !== "object") continue;
    if (row.id === "agent-default-model" || row.name === "@deepseek-ai/dsh-agent-default-model") {
      const config = row.config && typeof row.config === "object" ? row.config : {};
      selectedProvider = String(config.provider || "").trim();
      selectedModel = String(config.model || "").trim();
    }
    const config = row.config && typeof row.config === "object" && !Array.isArray(row.config) ? row.config : {};
    if (config.providers && typeof config.providers === "object" && !Array.isArray(config.providers)) {
      for (const [provider, source] of Object.entries(config.providers)) ensureProvider(provider, source || {});
    }
    if (row.id === "llm-deepseek" || row.id === "llm-deepseek-account") {
      const provider = String(config.provider || config.id || selectedProvider || "").trim();
      if (provider) ensureProvider(provider, config);
    }
  }

  if (selectedProvider) {
    const selectedRow = ensureProvider(selectedProvider, { models: selectedModel ? [selectedModel] : [] });
    if (selectedRow && selectedModel && !selectedRow.models.some((model) => model.id === selectedModel)) {
      selectedRow.models.unshift({ id: selectedModel, label: selectedModel });
    }
  }
  const providers = [...providerMap.values()].slice(0, CATALOG_MAX_PROVIDERS).map((provider) => {
    const models = provider.models.slice(0, CATALOG_MAX_MODELS);
    const reasoningEfforts = [...new Set([
      ...provider.reasoningEfforts,
      ...models.flatMap((model) => model.reasoningEfforts || []),
    ])];
    return {
      id: provider.id,
      label: provider.label,
      ...(provider.defaultModel ? { defaultModel: provider.defaultModel } : {}),
      ...(provider.defaultReasoningEffort ? { defaultReasoningEffort: provider.defaultReasoningEffort } : {}),
      ...(models.length ? { modelOptions: models } : {}),
      ...(reasoningEfforts.length ? { reasoningEfforts } : {}),
    };
  });
  const selected = selectedProvider || providers[0]?.id || "";
  const selectedProviderRow = providers.find((provider) => provider.id === selected);
  let selectedOptions = selectedProviderRow?.modelOptions || [];
  if (selectedModel && !selectedOptions.some((model) => model.id === selectedModel)) {
    selectedOptions = [{ id: selectedModel, label: selectedModel }, ...selectedOptions];
  }
  const modelOptionsByProvider = Object.fromEntries(providers.map((provider) => [provider.id, provider.modelOptions || []]));
  const modelOptions = selectedOptions.map((model) => model.id);
  const reasoningEfforts = [...new Set([
    ...(selectedProviderRow?.reasoningEfforts || []),
    ...selectedOptions.flatMap((model) => model.reasoningEfforts || []),
  ])];
  return {
    providers,
    selectedProvider: selected,
    selectedModel: selectedModel || selectedProviderRow?.defaultModel || selectedOptions[0]?.id || "",
    modelOptions,
    modelOptionsByProvider,
    reasoningEfforts,
    status: providers.length ? "ready" : "fallback",
    diagnostic: providers.length ? "" : "未发现可枚举的 DeepSeek provider，保留当前模型和静态候选",
  };
}

async function loadDesktopBridgeEntries() {
  try {
    const profile = await loadDesktopProfileEntries();
    return profile.entries.map(safeBridgeEntry).filter(Boolean);
  } catch {
    return [];
  }
}

async function describeModels() {
  try {
    let entries = [];
    if (desktop) {
      try {
        const headless = await loadHeadlessProfile({ includeOverlays: false });
        const bridge = await loadDesktopBridgeEntries();
        entries = bridge.length ? headless.boot.composeEntries([headless.patches, bridge]) : headless.entries;
      } catch {
        entries = [];
      }
      if (!entries.length) {
        try {
          const modelEntry = await loadDesktopModelEntry(entry);
          entries = modelEntry ? [modelEntry] : [];
        } catch {
          entries = [];
        }
      }
    } else {
      entries = (await loadHeadlessProfile({ includeOverlays: false })).entries;
    }
    return collectModelCatalog(entries);
  } catch (error) {
    return {
      providers: [], selectedProvider: "", selectedModel: "", modelOptions: [], modelOptionsByProvider: {},
      reasoningEfforts: [], status: "error", diagnostic: diagnosticText(error),
    };
  }
}

function parseYamlScalar(value) {
  const text = value.trim();
  if (!text) return undefined;
  if (text === "null" || text === "~") return null;
  if (text === "true") return true;
  if (text === "false") return false;
  if (/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(text)) return Number(text);
  if (text.startsWith('"') && text.endsWith('"')) {
    try { return JSON.parse(text); } catch { return text.slice(1, -1); }
  }
  if (text.startsWith("'") && text.endsWith("'")) return text.slice(1, -1).replaceAll("''", "'");
  if (text.startsWith("[") || text.startsWith("{")) {
    try { return JSON.parse(text); } catch { /* Use the scalar below for YAML-only syntax. */ }
  }
  return text;
}

function yamlKeyValue(text) {
  const match = text.match(/^([^:]+):(?:\s+(.*))?$/);
  if (!match) return null;
  return [parseYamlScalar(match[1]), match[2] ?? ""];
}

function yamlLines(text) {
  const lines = [];
  for (const source of text.replace(/^\uFEFF/, "").split(/\r?\n/)) {
    if (!source.trim() || source.trimStart().startsWith("#")) continue;
    const content = source.trimStart();
    if (content === "---" || content === "...") continue;
    lines.push({ indent: source.length - content.length, text: content });
  }
  return lines;
}

function parseYamlBlock(lines, start, indent) {
  if (start >= lines.length || lines[start].indent < indent) return [null, start];
  const sequence = lines[start].indent === indent && lines[start].text.startsWith("-");
  if (sequence) {
    const result = [];
    let index = start;
    while (index < lines.length && lines[index].indent === indent && lines[index].text.startsWith("-")) {
      const rest = lines[index].text.slice(1).trim();
      index += 1;
      if (!rest) {
        if (index < lines.length && lines[index].indent > indent) {
          const [child, next] = parseYamlBlock(lines, index, lines[index].indent);
          result.push(child);
          index = next;
        } else {
          result.push(null);
        }
        continue;
      }
      const first = yamlKeyValue(rest);
      if (!first) {
        result.push(parseYamlScalar(rest));
        continue;
      }
      const object = {};
      const [key, rawValue] = first;
      if (rawValue) {
        object[key] = parseYamlScalar(rawValue);
      } else if (index < lines.length && lines[index].indent > indent) {
        const [child, next] = parseYamlBlock(lines, index, lines[index].indent);
        object[key] = child;
        index = next;
      } else {
        object[key] = {};
      }
      if (index < lines.length && lines[index].indent > indent) {
        const [extra, next] = parseYamlBlock(lines, index, lines[index].indent);
        if (extra && typeof extra === "object" && !Array.isArray(extra)) Object.assign(object, extra);
        index = next;
      }
      result.push(object);
    }
    return [result, index];
  }

  const result = {};
  let index = start;
  while (index < lines.length && lines[index].indent === indent && !lines[index].text.startsWith("-")) {
    const pair = yamlKeyValue(lines[index].text);
    if (!pair) {
      index += 1;
      continue;
    }
    const [key, rawValue] = pair;
    index += 1;
    if (rawValue) {
      result[key] = parseYamlScalar(rawValue);
    } else if (index < lines.length && lines[index].indent > indent) {
      const [child, next] = parseYamlBlock(lines, index, lines[index].indent);
      result[key] = child;
      index = next;
    } else {
      result[key] = {};
    }
  }
  return [result, index];
}

function findDesktopModelEntry(value) {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findDesktopModelEntry(item);
      if (found) return found;
    }
    return undefined;
  }
  if (!value || typeof value !== "object") return undefined;
  if (
    (value.id === "agent-default-model" || value.name === "@deepseek-ai/dsh-agent-default-model")
    && value.disabled !== true
    && value.config && typeof value.config === "object" && !Array.isArray(value.config)
  ) return value;
  for (const child of Object.values(value)) {
    const found = findDesktopModelEntry(child);
    if (found) return found;
  }
  return undefined;
}

function desktopPatchArgs() {
  const patches = [];
  for (let index = 0; index < args.length; index += 1) {
    if (args[index] === "--patch" && index + 1 < args.length) {
      patches.push("--patch", args[index + 1]);
      index += 1;
    } else if (args[index].startsWith("--patch=")) {
      patches.push(args[index]);
    }
  }
  return patches;
}

function desktopPatchRequiresClusterMcp() {
  for (let index = 0; index < args.length; index += 1) {
    let patchPath = "";
    if (args[index] === "--patch" && index + 1 < args.length) {
      patchPath = args[index + 1];
      index += 1;
    } else if (args[index].startsWith("--patch=")) {
      patchPath = args[index].slice("--patch=".length);
    }
    if (!patchPath) continue;
    try {
      const text = readFileSync(resolve(patchPath), "utf8").slice(0, 262144);
      if (text.includes("@deepseek-ai/dsh-mcp-client") || text.includes("orbit-tcb-cluster-mcp")) return true;
    } catch { /* The Desktop CLI will report an invalid user patch. */ }
  }
  return false;
}

function spawnTarget(target, targetArgs, options) {
  if (process.platform === "win32" && /\.(?:cmd|bat)$/i.test(target)) {
    return spawn(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", "@", target, ...targetArgs], options);
  }
  return spawn(target, targetArgs, options);
}

function captureDesktopConfig(target) {
  return new Promise((resolveOutput, reject) => {
    const child = spawnTarget(
      target,
      ["--profile", "headless", ...desktopPatchArgs(), "--dump-config"],
      { stdio: ["ignore", "pipe", "pipe"], windowsHide: true },
    );
    const stdout = [];
    const stderr = [];
    let stdoutBytes = 0;
    let settled = false;
    const take = (chunks, chunk, limit) => {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      if (chunks === stdout) {
        stdoutBytes += buffer.length;
        if (stdoutBytes > limit) return false;
      }
      chunks.push(buffer);
      return true;
    };
    child.stdout.on("data", (chunk) => {
      if (!take(stdout, chunk, DUMP_CONFIG_MAX_BYTES) && !settled) {
        settled = true;
        child.kill();
        reject(new Error("DeepSeek Harness --dump-config 输出过大"));
      }
    });
    child.stderr.on("data", (chunk) => { take(stderr, chunk, 4096); });
    child.once("error", (error) => {
      if (!settled) {
        settled = true;
        reject(error);
      }
    });
    child.once("close", (code) => {
      if (settled) return;
      settled = true;
      if (code !== 0) {
        const detail = Buffer.concat(stderr).toString("utf8").trim().slice(0, 512);
        reject(new Error(detail || `Desktop --dump-config 退出码 ${code}`));
        return;
      }
      resolveOutput({
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8"),
      });
    });
  });
}

async function loadDesktopModelEntry(target) {
  const dump = await captureDesktopConfig(target);
  if (
    desktopPatchRequiresClusterMcp()
    && /(?:dsh-mcp-client|orbit-tcb-cluster-mcp).*not found/i.test(dump.stderr)
  ) {
    throw new Error("DeepSeek Harness Desktop runtime 不包含 @deepseek-ai/dsh-mcp-client，无法加载 tcb-cluster MCP；请更新 Desktop 版本");
  }
  const lines = yamlLines(dump.stdout);
  const [document] = lines.length ? parseYamlBlock(lines, 0, lines[0].indent) : [null];
  const modelEntry = findDesktopModelEntry(document);
  if (
    !modelEntry?.id || !modelEntry.name || !modelEntry.config
    || Array.isArray(modelEntry.config) || modelEntry.config.__jsExpr
  ) {
    throw new Error("DeepSeek Harness 无法读取默认模型配置，请检查 Desktop 的 headless 配置");
  }
  return modelEntry;
}

function cleanupPatch() {
  if (!patchDirectory) return;
  try { rmSync(patchDirectory, { recursive: true, force: true }); } catch { /* Preserve the CLI result. */ }
  patchDirectory = undefined;
}

function runDesktop(target, targetArgs) {
  return new Promise((resolveCode, reject) => {
    const child = spawnTarget(target, targetArgs, { stdio: "inherit", windowsHide: true });
    child.once("error", reject);
    child.once("close", (code) => resolveCode(code ?? 1));
  });
}

if (isDescribeModels()) {
  const catalog = await describeModels();
  let output = JSON.stringify(catalog);
  if (Buffer.byteLength(output, "utf8") > CATALOG_MAX_BYTES) {
    output = JSON.stringify({
      providers: [], selectedProvider: catalog.selectedProvider || "", selectedModel: catalog.selectedModel || "",
      modelOptions: [], modelOptionsByProvider: {}, reasoningEfforts: [], status: "error", diagnostic: "DeepSeek catalog 输出过大",
    });
  }
  process.stdout.write(`${output}\n`);
  process.exit(0);
}

try {
  let modelEntry;
  let desktopBridgeEntries = [];
  if (desktop) {
    modelEntry = await loadDesktopModelEntry(entry);
    if (Object.keys(selection).length) desktopBridgeEntries = await loadDesktopBridgeEntries();
  } else {
    try {
      modelEntry = await loadModelEntry();
    } catch (error) {
      // Optional price metadata must not block an otherwise valid default launch.
      if (Object.keys(selection).length) throw error;
    }
  }
  if (Object.keys(selection).length) {
    if (!modelEntry?.id || !modelEntry.config || modelEntry.config.__jsExpr) {
      throw new Error("DeepSeek Harness 无法读取默认模型配置，请检查 headless 的 agent-default-model 配置");
    }
    // Harness patches replace the whole config. Retain its provider and any inherited fields.
    const patch = [{ id: modelEntry.id, name: modelEntry.name, config: { ...modelEntry.config, ...selection } }];
    patchDirectory = mkdtempSync(join(tmpdir(), "orbit-dsh-"));
    const patchPath = join(patchDirectory, "model.json");
    process.once("exit", () => {
      cleanupPatch();
    });
    process.once("SIGINT", () => {
      cleanupPatch();
      process.exit(130);
    });
    process.once("SIGTERM", () => {
      cleanupPatch();
      process.exit(143);
    });
    if (desktopBridgeEntries.length) {
      const bridgePath = join(patchDirectory, "desktop-bridge.json");
      writeFileSync(bridgePath, JSON.stringify(desktopBridgeEntries), "utf8");
      const profileEnd = args[0] === "--profile" ? 2 : 0;
      args.splice(profileEnd, 0, "--patch", bridgePath);
    }
    writeFileSync(patchPath, JSON.stringify(patch), "utf8");
    const protocolIndex = args.indexOf("--json");
    args.splice(protocolIndex < 0 ? args.length : protocolIndex, 0, "--patch", patchPath);
  }
  const model = selection.model ?? modelEntry?.config?.model;
  const provider = selection.provider ?? modelEntry?.config?.provider;
  if (args.includes("--json") && typeof model === "string" && model.trim()) {
    const metadata = { type: "orbit_model", model: model.trim() };
    if (typeof provider === "string" && provider.trim()) metadata.provider = provider.trim();
    process.stdout.write(`${JSON.stringify(metadata)}\n`);
  }
  if (desktop) {
    try {
      const code = await runDesktop(entry, args);
      process.exitCode = code;
    } finally {
      cleanupPatch();
    }
  } else {
    process.argv = [process.execPath, entry, ...args];
    // Call the exported entry explicitly: Node 22.17 has no import.meta.main.
    const cli = await import(pathToFileURL(entry));
    if (typeof cli.runCli !== "function") throw new Error("DeepSeek Harness 缺少 runCli 入口，请更新 dsh");
    await cli.runCli();
  }
} catch (error) {
  process.stderr.write(`DeepSeek Harness 启动失败：${error.message}\n`);
  process.exitCode = 1;
}
