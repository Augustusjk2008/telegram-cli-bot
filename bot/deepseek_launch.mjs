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
const selection = JSON.parse(selectionJson);
let patchDirectory;

const runtimeBin = dirname(process.execPath);
const pathValue = process.env.PATH || "";
const pathEntries = pathValue.split(delimiter);
if (!pathEntries.some((item) => item.toLowerCase() === runtimeBin.toLowerCase())) {
  process.env.PATH = [runtimeBin, pathValue].filter(Boolean).join(delimiter);
}

const DUMP_CONFIG_MAX_BYTES = 2 * 1024 * 1024;

function findModelEntry(entries) {
  for (const row of entries) {
    if (row.name === "@deepseek-ai/dsh-agent-default-model" && row.disabled !== true) return row;
    if (row.group && Array.isArray(row.config)) {
      const found = findModelEntry(row.config);
      if (found) return found;
    }
  }
}

async function loadModelEntry() {
  const require = createRequire(pathToFileURL(entry));
  const boot = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-app-boot")));
  const { resolveDshHome } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-home-paths")));
  const installAnchor = join(dirname(entry), "..", "package.json");
  const profile = boot.loadProfile("dsh", "headless", installAnchor);
  const overlays = [];
  for (let index = 2; index < args.length && args[index] === "--patch"; index += 2) {
    overlays.push(...boot.loadOverlayPatches("dsh", resolve(args[index + 1])));
  }
  const patches = boot.readProfilePatches("dsh", {
    dir: profile.dir, patchPath: profile.patchPath, installAnchor,
    home: resolveDshHome(), overlays, telemetryDisabledEnv: process.env.DSH_TELEMETRY_DISABLED,
  }, profile);
  return findModelEntry(boot.composeEntries([patches]));
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

try {
  let modelEntry;
  if (desktop) {
    modelEntry = await loadDesktopModelEntry(entry);
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
    writeFileSync(patchPath, JSON.stringify(patch), "utf8");
    const protocolIndex = args.indexOf("--json");
    args.splice(protocolIndex < 0 ? args.length : protocolIndex, 0, "--patch", patchPath);
  }
  const model = selection.model ?? modelEntry?.config?.model;
  if (args.includes("--json") && typeof model === "string" && model.trim()) {
    process.stdout.write(`${JSON.stringify({ type: "orbit_model", model: model.trim() })}\n`);
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
