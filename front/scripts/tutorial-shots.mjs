// Regenerates the usage tutorial screenshots and hotspot data from the mock build.
//
//   npm run tutorial:shots                      build the mock app and capture every scene
//   npm run tutorial:shots -- --only chat       capture selected chapters (comma separated)
//   npm run tutorial:shots -- --dist <dir>      reuse an existing mock build
//
// The browser is fed straight from the build directory, so no server or listening port is involved,
// and `front/dist` is never touched. Scenes live in tutorial-scenes.mjs. Review PNGs are written to
// test-results/tutorial-shots (git-ignored; a Playwright run clears that directory).
//
// Repeated runs give identical files except for one known wobble: the header's search text can land
// one device pixel to the side for a whole page session, which changes the shots of that chapter.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { CAPTURE_THEME_ID, FIXED_TIME, SCENES, TERMINAL_OUTPUTS } from "./tutorial-scenes.mjs";

const frontRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const assetRoot = path.join(frontRoot, "public", "assets", "tutorial");
const reviewRoot = path.join(frontRoot, "test-results", "tutorial-shots");
const generatedPath = path.join(frontRoot, "src", "tutorial", "shots.generated.json");

const ORIGIN = "http://orbit.tutorial";
const VIEWPORT = { width: 1440, height: 900 };
const DEVICE_SCALE_FACTOR = 2;
const HOTSPOT_PADDING = 6;
const FILE_BUDGET = 400 * 1024;
const TOTAL_BUDGET = 10 * 1024 * 1024;
const WEBP_QUALITIES = [0.8, 0.7, 0.6, 0.5, 0.4];

function parseArgs(argv) {
  const options = { dist: "", only: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--dist") {
      options.dist = path.resolve(argv[index += 1] || "");
    } else if (arg === "--only") {
      options.only = String(argv[index += 1] || "").split(",").map((item) => item.trim()).filter(Boolean);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }
  return options;
}

async function buildMockApp(outDir) {
  // Root base keeps asset URLs at "/", so the build does not depend on the local .env.
  process.env.VITE_USE_MOCK = "true";
  process.env.TCB_FRONT_BUILD_ROOT_BASE = "1";
  const { build } = await import("vite");
  await build({ root: frontRoot, logLevel: "warn", build: { outDir, emptyOutDir: true } });
}

function launchOptions() {
  const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (executablePath) {
    return { executablePath };
  }
  // Mirrors playwright.config.ts: Windows uses the installed Chrome.
  return process.platform === "win32" ? { channel: "chrome" } : {};
}

/**
 * Opens the mock app. `user` is the login name (the mock treats "127.0.0.1" as the local administrator);
 * `loggedOut` stops at the login page.
 */
async function openWorkbench(browser, distDir, { user = "demo", loggedOut = false } = {}) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: DEVICE_SCALE_FACTOR,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    reducedMotion: "reduce",
  });
  await context.addInitScript((themeId) => {
    try {
      localStorage.setItem("web-view-mode", "desktop");
      // The tutorial's own first-run hint must not appear on the logo in its screenshots.
      localStorage.setItem("web-tutorial-state", JSON.stringify({ v: 1, seen: true, chapterId: "", stepIndex: 0, completed: [] }));
      // Theme: the mock client reads its stored library selection, the login page its own preview key.
      localStorage.setItem("web-mock-ui-themes:global:v1", JSON.stringify({ selectedThemeId: themeId }));
      localStorage.setItem("web-ui-theme:login:v1:/", themeId);
    } catch {
      // Storage is unavailable before navigation to the fake origin.
    }
  }, CAPTURE_THEME_ID);
  const page = await context.newPage();
  await page.clock.setFixedTime(FIXED_TIME);
  // No socket reaches a real host. The terminal has no mock shell, so its socket is answered here with
  // canned output (legacy protocol: one JSON greeting, then raw terminal data); keystrokes are ignored.
  let terminalCount = 0;
  await page.routeWebSocket("**/*", (socket) => {
    if (!new URL(socket.url()).pathname.endsWith("/terminal/ws")) {
      socket.close();
      return;
    }
    const output = TERMINAL_OUTPUTS[terminalCount % TERMINAL_OUTPUTS.length];
    terminalCount += 1;
    let greeted = false;
    socket.onMessage(() => {
      if (greeted) {
        return;
      }
      greeted = true;
      socket.send(JSON.stringify({ pty_mode: true }));
      socket.send(output);
    });
  });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== ORIGIN) {
      await route.abort();
      return;
    }
    const requested = path.join(distDir, decodeURIComponent(url.pathname));
    const inside = requested.startsWith(distDir + path.sep);
    const file = inside && fs.existsSync(requested) && fs.statSync(requested).isFile()
      ? requested
      : path.join(distDir, "index.html");
    await route.fulfill({ path: file });
  });
  await page.goto(`${ORIGIN}/`);
  if (loggedOut) {
    await page.locator('input[name="username"]').waitFor();
    return { context, page };
  }
  // The mock build accepts any credentials.
  await page.locator('input[name="username"]').fill(user);
  await page.locator('input[name="password"]').fill("demo-password");
  await page.locator("form").getByRole("button", { name: "登录", exact: true }).click();
  await page.getByTestId("desktop-workbench-columns").waitFor();
  return { context, page };
}

const round1 = (value) => Math.round(value * 10) / 10;

async function measureHotspot(page, name, resolve) {
  const viewport = page.viewportSize();
  const resolved = await resolve(page);
  const locators = Array.isArray(resolved) ? resolved : [resolved];
  let left = Infinity;
  let top = Infinity;
  let right = -Infinity;
  let bottom = -Infinity;
  for (const locator of locators) {
    const box = await locator.boundingBox();
    if (!box) {
      throw new Error(`hotspot "${name}" is not visible`);
    }
    left = Math.min(left, box.x);
    top = Math.min(top, box.y);
    right = Math.max(right, box.x + box.width);
    bottom = Math.max(bottom, box.y + box.height);
  }
  left = Math.max(0, left - HOTSPOT_PADDING);
  top = Math.max(0, top - HOTSPOT_PADDING);
  right = Math.min(viewport.width, right + HOTSPOT_PADDING);
  bottom = Math.min(viewport.height, bottom + HOTSPOT_PADDING);
  if (right <= left || bottom <= top) {
    throw new Error(`hotspot "${name}" is outside the viewport`);
  }
  return {
    x: round1((left / viewport.width) * 100),
    y: round1((top / viewport.height) * 100),
    w: round1(((right - left) / viewport.width) * 100),
    h: round1(((bottom - top) / viewport.height) * 100),
  };
}

/** Waits for finite animations and transitions to end, so no shot is taken mid-movement. */
async function settle(page) {
  // Park the pointer in the header's empty corner: no hover styles or tooltips in the shot.
  await page.mouse.move(0, 0);
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const moving = await page.evaluate(() => document.getAnimations().some((animation) => (
      animation.playState === "running" && Number.isFinite(animation.effect?.getComputedTiming().endTime)
    )));
    if (!moving) {
      break;
    }
    await page.waitForTimeout(100);
  }
  await page.waitForTimeout(150);
}

/** PNG to WebP inside a blank page (canvas encoder), so no image dependency is needed. */
async function encodeWebp(encoderPage, png) {
  for (const quality of WEBP_QUALITIES) {
    const base64 = await encoderPage.evaluate(async ({ data, quality: q }) => {
      const blob = await (await fetch(`data:image/png;base64,${data}`)).blob();
      const bitmap = await createImageBitmap(blob);
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      canvas.getContext("2d").drawImage(bitmap, 0, 0);
      const url = canvas.toDataURL("image/webp", q);
      if (!url.startsWith("data:image/webp")) {
        throw new Error("This browser cannot encode WebP");
      }
      return url.slice(url.indexOf(",") + 1);
    }, { data: png.toString("base64"), quality });
    const webp = Buffer.from(base64, "base64");
    // Over budget: lower the quality first; resolution stays.
    if (webp.length <= FILE_BUDGET || quality === WEBP_QUALITIES.at(-1)) {
      return { webp, quality };
    }
  }
  throw new Error("unreachable");
}

function readGenerated() {
  try {
    return JSON.parse(fs.readFileSync(generatedPath, "utf8"));
  } catch {
    return {};
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const chapters = [...new Set(SCENES.map((scene) => scene.chapter))];
  const unknown = options.only.filter((chapter) => !chapters.includes(chapter));
  if (unknown.length > 0) {
    throw new Error(`Unknown chapter in --only: ${unknown.join(", ")}`);
  }
  const selected = options.only.length > 0 ? options.only : chapters;

  let distDir = options.dist;
  let tempDir = "";
  if (!distDir) {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "orbit-tutorial-shots-"));
    distDir = path.join(tempDir, "dist");
    console.log(`Building the mock app into ${distDir}`);
    await buildMockApp(distDir);
  }
  if (!fs.existsSync(path.join(distDir, "index.html"))) {
    throw new Error(`No build found in ${distDir}`);
  }

  // A partial run keeps the other chapters' data; scenes removed from a captured chapter are dropped.
  const generated = Object.fromEntries(
    Object.entries(readGenerated()).filter(([key]) => !selected.includes(key.split("/")[0])),
  );
  const failures = [];
  const rows = [];
  fs.mkdirSync(reviewRoot, { recursive: true });

  const browser = await chromium.launch(launchOptions());
  try {
    const encoderPage = await (await browser.newContext()).newPage();
    for (const chapter of selected) {
      const chapterDir = path.join(assetRoot, chapter);
      fs.rmSync(chapterDir, { recursive: true, force: true });
      fs.rmSync(path.join(reviewRoot, chapter), { recursive: true, force: true });
      fs.mkdirSync(chapterDir, { recursive: true });
      fs.mkdirSync(path.join(reviewRoot, chapter), { recursive: true });

      let session = null;
      for (const scene of SCENES.filter((item) => item.chapter === chapter)) {
        const key = `${scene.chapter}/${scene.shot}`;
        try {
          // One context per chapter; a scene that needs a clean workbench, another account or the
          // login page gets a fresh one.
          const entry = `${scene.user || "demo"}:${scene.loggedOut ? "out" : "in"}`;
          if (!session || scene.fresh || session.entry !== entry) {
            await session?.context.close();
            session = { ...await openWorkbench(browser, distDir, { user: scene.user, loggedOut: scene.loggedOut }), entry };
          }
          const { page } = session;
          await scene.run(page);
          await settle(page);
          const hotspots = {};
          for (const [name, resolve] of Object.entries(scene.hotspots || {})) {
            hotspots[name] = await measureHotspot(page, name, resolve);
          }
          // Spinners and other endless animations are reset, so repeated runs produce identical files.
          const png = await page.screenshot({ type: "png", animations: "disabled" });
          const { webp, quality } = await encodeWebp(encoderPage, png);
          fs.writeFileSync(path.join(reviewRoot, chapter, `${scene.shot}.png`), png);
          fs.writeFileSync(path.join(chapterDir, `${scene.shot}.webp`), webp);
          generated[key] = { hotspots };
          rows.push({ key, bytes: webp.length, quality });
          if (webp.length > FILE_BUDGET) {
            failures.push(`${key}: ${webp.length} bytes exceeds the ${FILE_BUDGET} byte budget`);
          }
        } catch (error) {
          failures.push(`${key}: ${error instanceof Error ? error.message.split("\n")[0] : error}`);
          // Later scenes of the chapter must not inherit a half-driven page.
          await session?.context.close().catch(() => undefined);
          session = null;
        }
      }
      await session?.context.close();
    }
  } finally {
    await browser.close();
    if (tempDir) {
      fs.rmSync(tempDir, { recursive: true, force: true });
    }
  }

  const sorted = Object.fromEntries(Object.keys(generated).sort().map((key) => [key, generated[key]]));
  fs.writeFileSync(generatedPath, `${JSON.stringify(sorted, null, 2)}\n`);

  for (const row of rows) {
    console.log(`${row.key.padEnd(34)} ${(row.bytes / 1024).toFixed(0).padStart(5)} KB  q=${row.quality}`);
  }
  let total = 0;
  if (fs.existsSync(assetRoot)) {
    for (const entry of fs.readdirSync(assetRoot, { recursive: true, withFileTypes: true })) {
      if (entry.isFile()) {
        total += fs.statSync(path.join(entry.parentPath, entry.name)).size;
      }
    }
  }
  console.log(`All tutorial images: ${(total / 1024 / 1024).toFixed(2)} MB (budget ${TOTAL_BUDGET / 1024 / 1024} MB)`);
  console.log(`Review PNGs: ${path.relative(frontRoot, reviewRoot)}`);
  if (total > TOTAL_BUDGET) {
    failures.push(`tutorial images total ${total} bytes exceeds the ${TOTAL_BUDGET} byte budget`);
  }
  if (failures.length > 0) {
    console.error(`\n${failures.length} problem(s):\n- ${failures.join("\n- ")}`);
    process.exitCode = 1;
  }
}

await main();
