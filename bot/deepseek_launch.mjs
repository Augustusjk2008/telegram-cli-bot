import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [mode, electronPath, entry, hostEntry, selectionJson, ...args] = process.argv.slice(2);
if (mode !== "desktop" || !electronPath || !entry || !selectionJson) {
  throw new Error("DeepSeek Harness 桌面启动器参数无效");
}

const selection = JSON.parse(selectionJson);
let patchDirectory;

// The Desktop application keeps the user's model route in its managed
// profile, while the non-UI JSONL runner uses the headless profile. Bridge
// only the model/provider entries needed by the headless process. This keeps
// the Desktop profile's credential mapping (for example opencode-go) without
// importing its UI-only plugins or changing the user's files.
const DESKTOP_RUNTIME_ENTRY_IDS = new Set([
  "credentials",
  "agent-default-model",
  "llm-pi-ai",
  "llm-deepseek",
]);

function findModelEntry(entries) {
  for (const row of entries) {
    if (row.name === "@deepseek-ai/dsh-agent-default-model" && row.disabled !== true) return row;
    if (row.group && Array.isArray(row.config)) {
      const found = findModelEntry(row.config);
      if (found) return found;
    }
  }
}

function patchPathsFromArgs(argv) {
  const patches = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--patch") {
      if (index + 1 < argv.length) patches.push(argv[++index]);
    } else if (typeof arg === "string" && arg.startsWith("--patch=")) {
      patches.push(arg.slice("--patch=".length));
    }
  }
  return patches;
}

function ensurePatchDirectory() {
  if (patchDirectory) return patchDirectory;
  patchDirectory = mkdtempSync(join(tmpdir(), "orbit-dsh-"));
  process.once("exit", () => {
    try {
      rmSync(patchDirectory, { recursive: true, force: true });
    } catch { /* cleanup must preserve the CLI's exit status */ }
  });
  return patchDirectory;
}

function insertPatchBeforeProjectOverlays(patchPath) {
  const firstPatchIndex = args.findIndex((arg) => arg === "--patch" || (typeof arg === "string" && arg.startsWith("--patch=")));
  const protocolIndex = args.indexOf("--json");
  const insertAt = firstPatchIndex >= 0 ? firstPatchIndex : (protocolIndex < 0 ? args.length : protocolIndex);
  args.splice(insertAt, 0, "--patch", patchPath);
}

function addDesktopRuntimePatch(entries) {
  const selected = (Array.isArray(entries) ? entries : []).filter((entry) => DESKTOP_RUNTIME_ENTRY_IDS.has(entry?.id));
  if (!selected.length) return null;
  // Headless deliberately disables the local credential service. Re-enable
  // the existing entry so the shared DSH_HOME/.credentials.yaml can satisfy
  // the Desktop profile's apiKeyEnv references without exporting secrets.
  if (!selected.some((entry) => entry?.id === "credentials")) {
    selected.unshift({ id: "credentials", disabled: false });
  }
  const patchPath = join(ensurePatchDirectory(), "desktop-model.json");
  writeFileSync(patchPath, JSON.stringify(selected), "utf8");
  insertPatchBeforeProjectOverlays(patchPath);
  return selected;
}

const dshEntry = resolve(entry);
const desktopElectron = resolve(electronPath);
const dshPackageRoot = resolve(dirname(dirname(dshEntry)));
const dshRoot = resolve(dirname(dirname(dirname(dshPackageRoot))));
const installAnchor = join(dshRoot, "package.json");
const appArchive = dirname(dshRoot);
const supportDir = join(dirname(appArchive), "runtime");

async function loadModelEntry() {
  const require = createRequire(pathToFileURL(dshEntry));
  const boot = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-app-boot")));
  const { resolveDshHome } = await import(pathToFileURL(require.resolve("@deepseek-ai/dsh-home-paths")));
  const overlays = [];
  for (const patchPath of patchPathsFromArgs(args)) {
    overlays.push(...boot.loadOverlayPatches("dsh", resolve(patchPath)));
  }
  const profile = boot.loadProfile("dsh", "headless", installAnchor);
  const headlessPatches = boot.readProfilePatches("dsh", {
    dir: profile.dir,
    patchPath: profile.patchPath,
    installAnchor,
    home: resolveDshHome(),
    overlays: [],
    telemetryDisabledEnv: process.env.DSH_TELEMETRY_DISABLED,
  }, profile);
  let desktopPatches = [];
  try {
    const desktopProfile = boot.loadProfile("dsh", "desktop", installAnchor);
    desktopPatches = boot.readProfilePatches("dsh", {
      dir: desktopProfile.dir,
      patchPath: desktopProfile.patchPath,
      installAnchor,
      home: resolveDshHome(),
      overlays: [],
      telemetryDisabledEnv: process.env.DSH_TELEMETRY_DISABLED,
    }, desktopProfile);
  } catch (error) {
    if (process.env.TCB_DSH_LAUNCHER_DEBUG === "1") {
      process.stderr.write(`DeepSeek Harness desktop profile bridge skipped: ${error.message}\n`);
    }
  }
  const desktopRuntimePatches = addDesktopRuntimePatch(desktopPatches);
  const composedLayers = [headlessPatches];
  if (desktopRuntimePatches?.length) composedLayers.push(desktopRuntimePatches);
  if (overlays.length) composedLayers.push(overlays);
  return findModelEntry(boot.composeEntries([composedLayers.flat()]));
}

function addSelectionPatch(modelEntry) {
  if (!modelEntry?.id || !modelEntry.config || modelEntry.config.__jsExpr) {
    throw new Error("DeepSeek Harness 无法读取默认模型配置，请检查 headless 的 agent-default-model 配置");
  }
  // Harness patches replace the whole config. Retain provider and every
  // inherited field, changing only the two values selected for this turn.
  const patch = [{
    id: modelEntry.id,
    name: modelEntry.name,
    config: { ...modelEntry.config, ...selection },
  }];
  const patchPath = join(ensurePatchDirectory(), "model.json");
  writeFileSync(patchPath, JSON.stringify(patch), "utf8");
  const protocolIndex = args.indexOf("--json");
  args.splice(protocolIndex < 0 ? args.length : protocolIndex, 0, "--patch", patchPath);
  return patchPath;
}

async function runDesktopCli() {
  process.argv = [process.execPath, dshEntry, ...args];

  // The host module installs the Desktop ASAR/native resolution hooks and
  // supplies the bundled pnpm runtime. A small fallback keeps the launcher
  // testable with a minimal bundled dsh package.
  let host;
  if (hostEntry) {
    try {
      host = await import(pathToFileURL(resolve(hostEntry)));
    } catch (error) {
      if (process.env.TCB_DSH_LAUNCHER_DEBUG === "1") {
        process.stderr.write(`DeepSeek Harness Desktop host fallback: ${error.message}\n`);
      }
    }
  }
  if (typeof host?.runDesktopCli === "function") {
    await host.runDesktopCli(dshRoot, supportDir);
    return;
  }

  const cli = await import(pathToFileURL(dshEntry));
  if (typeof cli.runCli !== "function") throw new Error("DeepSeek Harness 缺少 runCli 入口，请更新桌面版");
  await cli.runCli({
    manageDesktopProfile: true,
    packageManager: {
      command: desktopElectron,
      args: ["--expose-internals", join(supportDir, "primary-runtime", "dependencies", "pnpm", "bin", "pnpm.mjs")],
      env: {
        ELECTRON_RUN_AS_NODE: "1",
        DSH_DESKTOP_NODE_EXECUTABLE: desktopElectron,
        PATH: `${join(supportDir, "bin")}${process.platform === "win32" ? ";" : ":"}${process.env.PATH ?? ""}`,
      },
    },
  });
}

try {
  let modelEntry;
  try {
    modelEntry = await loadModelEntry();
  } catch (error) {
    // Optional price metadata must not block an otherwise valid default launch.
    if (Object.keys(selection).length) throw error;
  }
  if (Object.keys(selection).length) {
    addSelectionPatch(modelEntry);
  }
  const model = selection.model ?? modelEntry?.config?.model;
  if (args.includes("--json") && typeof model === "string" && model.trim()) {
    process.stdout.write(`${JSON.stringify({ type: "orbit_model", model: model.trim() })}\n`);
  }
  await runDesktopCli();
} catch (error) {
  process.stderr.write(`DeepSeek Harness 启动失败：${error.message}\n`);
  process.exitCode = 1;
}
