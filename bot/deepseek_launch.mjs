import { mkdtempSync, rmSync, rmdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [entry, selectionJson, ...args] = process.argv.slice(2);
const selection = JSON.parse(selectionJson);
let patchDirectory;

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

try {
  let modelEntry;
  try {
    modelEntry = await loadModelEntry();
  } catch (error) {
    // Optional price metadata must not block an otherwise valid default launch.
    if (Object.keys(selection).length) throw error;
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
      try {
        rmSync(patchPath, { force: true });
        rmdirSync(patchDirectory);
      } catch { /* Cleanup must preserve the CLI's exit status. */ }
    });
    writeFileSync(patchPath, JSON.stringify(patch), "utf8");
    const protocolIndex = args.indexOf("--json");
    args.splice(protocolIndex < 0 ? args.length : protocolIndex, 0, "--patch", patchPath);
  }
  const model = selection.model ?? modelEntry?.config?.model;
  if (args.includes("--json") && typeof model === "string" && model.trim()) {
    process.stdout.write(`${JSON.stringify({ type: "orbit_model", model: model.trim() })}\n`);
  }
  process.argv = [process.execPath, entry, ...args];
  // Call the exported entry explicitly: Node 22.17 has no import.meta.main.
  const cli = await import(pathToFileURL(entry));
  if (typeof cli.runCli !== "function") throw new Error("DeepSeek Harness 缺少 runCli 入口，请更新 dsh");
  await cli.runCli();
} catch (error) {
  process.stderr.write(`DeepSeek Harness 启动失败：${error.message}\n`);
  process.exitCode = 1;
}
