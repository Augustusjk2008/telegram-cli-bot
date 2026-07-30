import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { getTerminalTheme, type UiThemeName } from "../theme";

const FUTURE_THEMES = [
  { name: "lunar-ceramic", logoVariant: "classic", focusRing: "#817ba0" },
  { name: "copper-night", logoVariant: "copper", focusRing: "#d88955" },
  { name: "eclipse-film", logoVariant: "eclipsedark", focusRing: "#9bcbdd" },
] as const;

const OVERLAY_TIERS = [10, 20, 30, 35, 40, 45, 50] as const;

const OVERLAY_SOURCE_PATHS = [
  "../components/AnnouncementDialog.tsx",
  "../components/BotSwitcherSheet.tsx",
  "../components/ChatComposer.tsx",
  "../components/ConversationHistoryPanel.tsx",
  "../components/DesktopBotSwitcherPopover.tsx",
  "../components/DirectoryPickerDialog.tsx",
  "../components/FileNameDialog.tsx",
  "../components/FilePreviewDialog.tsx",
  "../screens/BotListScreen.tsx",
  "../screens/ChatScreen.tsx",
  "../screens/DesktopBotManagerScreen.tsx",
  "../screens/FilesScreen.tsx",
  "../screens/PluginsScreen.tsx",
  "../screens/SettingsScreen.tsx",
  "../terminal/TerminalActionsConfigDialog.tsx",
  "../workbench/CommandPalette.tsx",
  "../workbench/DesktopWorkbench.tsx",
  "../workbench/SoloSessionChangesTab.tsx",
] as const;

const REQUIRED_THEME_TOKENS = [
  "--bg",
  "--surface",
  "--accent",
  "--accent-strong",
  "--editor-bg",
  "--terminal-bg",
] as const;

const DECORATION_TOKENS = [
  "--hero-grid",
  "--hero-ring",
  "--hero-glow",
  "--editor-empty-art-opacity",
] as const;

const RESTRAINED_THEME_MOTION = [
  { name: "lunar-ceramic", statusSweep: "none", streamingSweep: "none" },
  {
    name: "copper-night",
    statusSweep: "workbenchStatusSweep 1.45s linear 1 both",
    streamingSweep: "workbenchStatusSweep 1.45s linear 1 both",
  },
  { name: "eclipse-film", statusSweep: "none", streamingSweep: "none" },
] as const;

function readSource(relativePath: string) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

function getThemeBlock(source: string, themeName: string) {
  return source.match(new RegExp(
    String.raw`:root\s*\[\s*data-theme\s*=\s*["']${themeName}["']\s*\]\s*\{([\s\S]*?)\n\}`,
    "m",
  ));
}

function getHexToken(block: string, token: string) {
  return block.match(new RegExp(String.raw`${token}\s*:\s*(#[0-9a-f]{6})\s*;`, "i"))?.[1] || "";
}

function relativeLuminance(hexColor: string) {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hexColor.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((channel) => channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrastRatio(left: string, right: string) {
  const [lighter, darker] = [relativeLuminance(left), relativeLuminance(right)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
}

function getCssRule(source: string, selector: string) {
  return source
    .split("}")
    .find((rule) => rule.includes(selector));
}

function getLogoImage(source: string, variant: string) {
  return (source.match(/<img[\s\S]*?\/>/g) || [])
    .find((image) => image.includes(`app-logo-image--${variant}`));
}

function expectLogoRule(source: string, themeName: string, variant: string, display: "block" | "none") {
  const selector = `:root[data-theme="${themeName}"] .app-logo-image--${variant}`;
  const rule = getCssRule(source, selector);

  expect(rule, `${themeName} must explicitly map the ${variant} logo variant`).toBeDefined();
  if (!rule) return;
  expect(rule).toMatch(new RegExp(String.raw`display\s*:\s*${display}\s*;`));
}

describe("future theme visual contract", () => {
  it.each(FUTURE_THEMES)("gives $name its complete palette inside its own selector", ({ name }) => {
    const tokens = readSource("../styles/tokens.css");
    const match = getThemeBlock(tokens, name);

    expect(match, `tokens.css must define :root[data-theme="${name}"]`).toBeTruthy();
    if (!match) return;

    for (const token of REQUIRED_THEME_TOKENS) {
      expect(match[1], `${name} must declare ${token}`).toMatch(new RegExp(String.raw`${token}\s*:`));
    }
  });

  it("maps every new theme to an explicit ThemeDropdown icon", () => {
    const dropdown = readSource("../components/ThemeDropdown.tsx");
    const mappingStart = dropdown.indexOf("const THEME_ICONS");
    const mappingEnd = dropdown.indexOf("};", mappingStart);
    const iconMappings = dropdown.slice(mappingStart, mappingEnd);

    expect(dropdown).toMatch(/const\s+THEME_ICONS\s*:\s*Record<\s*UiThemeName\s*,\s*ThemeIconComponent\s*>\s*=/);
    for (const { name } of FUTURE_THEMES) {
      expect(iconMappings, `${name} must not fall back to the generic theme icon`).toMatch(
        new RegExp(String.raw`["']${name}["']\s*:\s*[A-Za-z][A-Za-z0-9_]*\s*,?`),
      );
    }
  });

  it("uses the light lunar logo and separate copper and eclipsedark brand variants", () => {
    const globalStyles = readSource("../styles/global.css");
    const appLogo = readSource("../components/AppLogo.tsx");

    const lunarImage = getLogoImage(appLogo, "classic");
    expect(lunarImage).toContain("APP_LOGO_CLASSIC_SRC");
    expectLogoRule(globalStyles, "lunar-ceramic", "classic", "block");
    expectLogoRule(globalStyles, "lunar-ceramic", "deep", "none");

    for (const { name, logoVariant } of FUTURE_THEMES.slice(1)) {
      const variantImage = getLogoImage(appLogo, logoVariant);
      expect(variantImage, `AppLogo must render a ${logoVariant} image`).toBeDefined();
      if (!variantImage) return;

      expect(variantImage).toMatch(/src=\{[^}]+\}/);
      expect(variantImage).not.toContain("APP_LOGO_CLASSIC_SRC");
      expectLogoRule(globalStyles, name, logoVariant, "block");
      expectLogoRule(globalStyles, name, "deep", "none");
    }

    expect(appLogo.match(/<img[\s\S]*?\/>/g)).toHaveLength(4);
    expect(globalStyles).toMatch(/\.app-logo-image\s*\{[^}]*display\s*:\s*none\s*;/s);
    expect(globalStyles).toMatch(/\.app-logo-image--deep\s*\{[^}]*display\s*:\s*block\s*;/s);
    for (const { name } of FUTURE_THEMES) {
      const rules = globalStyles
        .split("}")
        .filter((rule) => rule.includes(`:root[data-theme="${name}"]`));
      expect(
        rules.filter((rule) => /display\s*:\s*block\s*;/.test(rule)),
        `${name} must enable exactly one non-default logo variant`,
      ).toHaveLength(1);
    }
  });

  it("marks the document favicon as theme-controlled", () => {
    const indexHtml = readSource("../../index.html");

    expect(indexHtml).toMatch(/<link\s+[^>]*data-theme-favicon[^>]*rel=["']icon["'][^>]*>/);
  });

  it.each(FUTURE_THEMES)("keeps $name focus indicators solid and above 3:1", ({ name, focusRing }) => {
    const tokens = readSource("../styles/tokens.css");
    const globalStyles = readSource("../styles/global.css");
    const commandPalette = readSource("../workbench/CommandPalette.tsx");
    const searchPane = readSource("../workbench/SearchPane.tsx");
    const match = getThemeBlock(tokens, name);

    expect(match).toBeTruthy();
    if (!match) return;

    const surface = getHexToken(match[1], "--surface");
    const terminalBackground = getHexToken(match[1], "--terminal-bg");
    expect(getHexToken(match[1], "--focus-ring").toLowerCase()).toBe(focusRing);
    expect(contrastRatio(focusRing, surface)).toBeGreaterThanOrEqual(3);
    expect(contrastRatio(focusRing, terminalBackground)).toBeGreaterThanOrEqual(3);
    expect(match[1]).toContain("--workbench-focus-ring: var(--focus-ring);");
    expect(globalStyles).toContain("outline: 2px solid var(--focus-ring);");
    expect(commandPalette).toContain("focus-within:outline-[var(--focus-ring)]");
    expect(searchPane).toContain("focus-within:outline-[var(--focus-ring)]");
  });

  it("preserves the legacy focus strength outside the three new themes", () => {
    const tokens = readSource("../styles/tokens.css");
    const rootBlock = tokens.match(/:root\s*\{([\s\S]*?)\n\}/m)?.[1] || "";

    expect(rootBlock).toContain("--focus-ring: var(--accent-outline);");
  });

  it("preserves all seven backdrop strengths while allowing new-theme tinting", () => {
    const tokens = readSource("../styles/tokens.css");
    const rootBlock = tokens.match(/:root\s*\{([\s\S]*?)\n\}/m)?.[1] || "";

    for (const tier of OVERLAY_TIERS) {
      const opacity = String(tier / 100);
      expect(rootBlock).toContain(`--overlay-backdrop-${tier}: rgba(0, 0, 0, ${opacity});`);
      for (const { name } of FUTURE_THEMES) {
        const match = getThemeBlock(tokens, name);
        expect(match?.[1], `${name} must provide overlay tier ${tier}`).toMatch(
          new RegExp(String.raw`--overlay-backdrop-${tier}\s*:`),
        );
      }
    }

    const announcement = readSource("../components/AnnouncementDialog.tsx");
    const switcher = readSource("../components/BotSwitcherSheet.tsx");
    const history = readSource("../components/ConversationHistoryPanel.tsx");
    const picker = readSource("../components/DirectoryPickerDialog.tsx");
    const preview = readSource("../components/FilePreviewDialog.tsx");
    expect(announcement).toContain("bg-[var(--overlay-backdrop-45)]");
    expect(switcher).toContain("bg-[var(--overlay-backdrop-40)]");
    expect(history).toContain("bg-[var(--overlay-backdrop-20)] sm:items-stretch sm:bg-[var(--overlay-backdrop-10)]");
    expect(history).toContain("bg-[var(--overlay-backdrop-30)]");
    expect(picker).toContain("bg-[var(--overlay-backdrop-50)]");
    expect(preview).toContain("bg-[var(--overlay-backdrop-35)]");

    const overlaySources = OVERLAY_SOURCE_PATHS.map(readSource).join("\n");
    expect(overlaySources).not.toMatch(/var\(--overlay-backdrop(?:-soft)?\)/);
  });

  it.each(FUTURE_THEMES)("keeps $name decorations token-driven and theme-scoped", ({ name }) => {
    const tokens = readSource("../styles/tokens.css");
    const globalStyles = readSource("../styles/global.css");
    const workbenchStyles = readSource("../styles/workbench.css");
    const match = getThemeBlock(tokens, name);

    expect(match, `${name} decorations must live in its theme selector`).toBeTruthy();
    if (!match) return;

    for (const token of DECORATION_TOKENS) {
      expect(match[1], `${name} must override ${token} instead of styling decorations globally`).toMatch(
        new RegExp(String.raw`${token}\s*:`),
      );
    }

    expect(workbenchStyles).toContain("var(--editor-empty-art-opacity)");
    expect(workbenchStyles).toContain("var(--accent-strong)");

    for (const [fileName, source] of [["global.css", globalStyles], ["workbench.css", workbenchStyles]] as const) {
      for (const rule of source.split("}").filter((candidate) => candidate.includes(name))) {
        expect(
          rule.slice(0, rule.indexOf("{")),
          `${fileName} must scope ${name} decorations with its data-theme selector`,
        ).toContain(`:root[data-theme="${name}"]`);
      }
    }
  });

  it.each(RESTRAINED_THEME_MOTION)("keeps $name matte and its motion restrained", ({ name, statusSweep, streamingSweep }) => {
    const tokens = readSource("../styles/tokens.css");
    const match = getThemeBlock(tokens, name);

    expect(match).toBeTruthy();
    if (!match) return;

    expect(match[1]).toContain("--workbench-shell-bg: var(--bg);");
    expect(match[1]).toContain("--composer-pulse-animation: none;");
    expect(match[1]).toContain(`--status-sweep-animation: ${statusSweep};`);
    expect(match[1]).toContain(`--streaming-sweep-animation: ${streamingSweep};`);
    expect(match[1]).toContain("--runtime-sheen-animation: none;");
  });

  it("routes status and streaming sweeps through their dedicated motion tokens", () => {
    const workbenchStyles = readSource("../styles/workbench.css");
    const statusRule = getCssRule(
      workbenchStyles,
      '.desktop-workbench-statusbar [data-workbench-status="active"]::after',
    );
    const streamingRule = getCssRule(
      workbenchStyles,
      '.chat-message-bubble-delight[data-streaming="true"]::after',
    );

    expect(statusRule).toContain("animation: var(--status-sweep-animation);");
    expect(streamingRule).toContain("animation: var(--streaming-sweep-animation);");
  });

  it.each(FUTURE_THEMES)("keeps $name key text and status colors at AA contrast", ({ name }) => {
    const tokens = readSource("../styles/tokens.css");
    const match = getThemeBlock(tokens, name);

    expect(match).toBeTruthy();
    if (!match) return;

    const surface = getHexToken(match[1], "--surface");
    for (const token of [
      "--text",
      "--muted",
      "--accent",
      "--status-success",
      "--status-warning",
      "--status-info",
      "--status-danger",
    ]) {
      const color = getHexToken(match[1], token);
      expect.soft(color, `${name} must expose ${token} as a solid hex color`).toMatch(/^#[0-9a-f]{6}$/i);
      expect.soft(contrastRatio(color, surface), `${name} ${token} must remain readable on --surface`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(FUTURE_THEMES)("keeps $name CSS terminal shell aligned with xterm", ({ name }) => {
    const tokens = readSource("../styles/tokens.css");
    const match = getThemeBlock(tokens, name);
    const terminalTheme = getTerminalTheme(name as UiThemeName);

    expect(match).toBeTruthy();
    if (!match) return;

    expect(getHexToken(match[1], "--terminal-bg").toLowerCase()).toBe(terminalTheme.background);
    expect(getHexToken(match[1], "--terminal-text").toLowerCase()).toBe(terminalTheme.foreground);
  });

  it("keeps the lunar terminal light in the shared mobile and desktop path", () => {
    const tokens = readSource("../styles/tokens.css");
    const terminalTabs = readSource("../screens/TerminalTabsScreen.tsx");
    const terminalScreen = readSource("../screens/TerminalScreen.tsx");
    const match = getThemeBlock(tokens, "lunar-ceramic");
    const terminalTheme = getTerminalTheme("lunar-ceramic");

    expect(match).toBeTruthy();
    if (!match) return;

    const background = getHexToken(match[1], "--terminal-bg");
    const foreground = getHexToken(match[1], "--terminal-text");
    const muted = getHexToken(match[1], "--terminal-muted");
    expect(relativeLuminance(background)).toBeGreaterThanOrEqual(0.7);
    expect(contrastRatio(foreground, background)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(muted, background)).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(terminalTheme.cursor, background)).toBeGreaterThanOrEqual(3);
    for (const colorName of [
      "foreground",
      "black",
      "red",
      "green",
      "yellow",
      "blue",
      "magenta",
      "cyan",
      "white",
      "brightBlack",
      "brightRed",
      "brightGreen",
      "brightYellow",
      "brightBlue",
      "brightMagenta",
      "brightCyan",
      "brightWhite",
    ] as const) {
      expect.soft(
        contrastRatio(terminalTheme[colorName], background),
        `lunar terminal ${colorName} must remain readable without xterm correction`,
      ).toBeGreaterThanOrEqual(4.5);
    }
    expect(terminalTabs).toContain("themeName={themeName}");
    expect(terminalScreen).toContain('bg-[var(--terminal-bg)]');
  });

  it("keeps FileTree semantic colors theme-token driven", () => {
    const fileTree = readSource("../workbench/FileTreePane.tsx");

    expect(fileTree).not.toMatch(
      /(?:text|bg|border)-(?:amber|cyan|emerald|fuchsia|indigo|lime|orange|pink|red|rose|sky|slate|stone|teal|violet|yellow)-\d+/,
    );
    expect(fileTree).toContain('return "text-[var(--status-success)]";');
    expect(fileTree).toContain('return "text-[var(--status-warning)]";');
    expect(fileTree).toContain('return "text-[var(--accent)]";');
    expect(fileTree).toContain('return "text-[var(--accent-strong)]";');
  });

  it("keeps theme logo glow controlled by CSS instead of baking it into the SVG assets", () => {
    for (const relativePath of [
      "../../public/assets/app-logo-copper.svg",
      "../../public/assets/app-logo-eclipse.svg",
    ]) {
      const logo = readSource(relativePath);
      expect(logo).not.toMatch(/<filter\b|\sfilter=/);
    }

    const globalStyles = readSource("../styles/global.css");
    const eclipseRule = getCssRule(
      globalStyles,
      ':root[data-theme="eclipse-film"] .app-logo-image--eclipsedark',
    );
    expect(eclipseRule).toMatch(/filter\s*:\s*none\s*;/);
  });
});
