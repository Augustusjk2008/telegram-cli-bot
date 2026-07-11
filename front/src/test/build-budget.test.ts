import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const roots: string[] = [];
const script = path.resolve(process.cwd(), "scripts/check-build-budget.mjs");

function fixture(manifest: Record<string, unknown>, assets: Record<string, number>) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tcb-budget-"));
  roots.push(root);
  fs.mkdirSync(path.join(root, "dist/.vite"), { recursive: true });
  fs.writeFileSync(path.join(root, "dist/.vite/manifest.json"), JSON.stringify(manifest));
  fs.writeFileSync(path.join(root, "dist/index.html"), "<div id=\"root\"></div>");
  for (const [file, size] of Object.entries(assets)) {
    const target = path.join(root, "dist", file);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, Buffer.alloc(size));
  }
  return root;
}

function run(root: string) {
  return () => execFileSync(process.execPath, [script], { cwd: root, encoding: "utf8", stdio: "pipe" });
}

afterEach(() => {
  roots.splice(0).forEach((root) => fs.rmSync(root, { recursive: true, force: true }));
});

describe("build budget manifest gate", () => {
  it("fails when a manifest asset is missing", () => {
    const root = fixture({ "index.html": { file: "assets/missing.js", isEntry: true } }, {});
    expect(run(root)).toThrow(/missing\.js.*ä¸å­åœ¨|ä¸å­åœ¨.*missing\.js/i);
  });

  it("aggregates the actual entry load closure instead of each renamed split", () => {
    const root = fixture({
      "index.html": { file: "assets/a-123.js", isEntry: true, imports: ["_shared"] },
      _shared: { file: "assets/b-456.js" },
    }, {
      "assets/a-123.js": 400 * 1024,
      "assets/b-456.js": 300 * 1024,
    });
    expect(run(root)).toThrow(/entry.*716800|716800.*entry/i);
  });

  it("aggregates the Mermaid branch by manifest graph even with neutral asset names", () => {
    const root = fixture({
      "index.html": { file: "assets/entry.js", isEntry: true, dynamicImports: ["src/markdown/mermaidRenderer.ts"] },
      "src/markdown/mermaidRenderer.ts": { file: "assets/x.js", imports: ["_diagram"] },
      _diagram: { file: "assets/y.js" },
    }, {
      "assets/entry.js": 10 * 1024,
      "assets/x.js": 400 * 1024,
      "assets/y.js": 300 * 1024,
    });
    expect(run(root)).toThrow(/Mermaid.*716800|716800.*Mermaid/i);
  });
});
