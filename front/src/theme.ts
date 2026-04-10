export type UiThemeName = "deep-space" | "classic";

export const APP_NAME = "🦞Safe Claw";
export const APP_SLOGAN = "【志在空间 威震长空】";
export const APP_YEAR = "2026";
export const UI_THEME_STORAGE_KEY = "web-ui-theme";
export const DEFAULT_UI_THEME: UiThemeName = "deep-space";

export const UI_THEME_OPTIONS: Array<{
  value: UiThemeName;
  label: string;
  description: string;
  preview: {
    accent: string;
    surface: string;
    accentStrong: string;
    border: string;
    text: string;
    muted: string;
  };
}> = [
  {
    value: "deep-space",
    label: "深空轨道",
    description: "冷色深空控制台风格，适合展示安全、自主可控与任务编排。",
    preview: {
      accent: "#61cbff",
      surface: "#0b1931",
      accentStrong: "#7af6d6",
      border: "rgba(142, 189, 255, 0.18)",
      text: "#eaf4ff",
      muted: "#90a9c7",
    },
  },
  {
    value: "classic",
    label: "经典暖色",
    description: "延续现有暖色工作界面，阅读压力更低，适合日常使用。",
    preview: {
      accent: "#0f8c78",
      surface: "#fffaf3",
      accentStrong: "#d98b2b",
      border: "rgba(46, 37, 28, 0.08)",
      text: "#1d1b18",
      muted: "#6d675f",
    },
  },
];

function isUiThemeName(value: string): value is UiThemeName {
  return value === "deep-space" || value === "classic";
}

export function readStoredUiTheme(): UiThemeName {
  if (typeof window === "undefined") {
    return DEFAULT_UI_THEME;
  }
  const raw = window.localStorage.getItem(UI_THEME_STORAGE_KEY)?.trim() || "";
  return isUiThemeName(raw) ? raw : DEFAULT_UI_THEME;
}

export function persistUiTheme(themeName: UiThemeName) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(UI_THEME_STORAGE_KEY, themeName);
}

export function applyUiTheme(themeName: UiThemeName) {
  if (typeof document === "undefined") {
    return;
  }
  document.documentElement.dataset.theme = themeName;
}

export function getTerminalTheme(themeName: UiThemeName) {
  if (themeName === "classic") {
    return {
      background: "#132033",
      foreground: "#eef3f8",
      cursor: "#fffaf3",
      black: "#1b2431",
      red: "#e76f51",
      green: "#3d8f5f",
      yellow: "#d49d2e",
      blue: "#5b8def",
      magenta: "#b07ae5",
      cyan: "#2b8c86",
      white: "#ecf2f8",
      brightBlack: "#5b6572",
      brightRed: "#f08f78",
      brightGreen: "#62b07d",
      brightYellow: "#e4b857",
      brightBlue: "#8db1ff",
      brightMagenta: "#c7a0ef",
      brightCyan: "#57b7af",
      brightWhite: "#ffffff",
    };
  }

  return {
    background: "#07111d",
    foreground: "#dce7f3",
    cursor: "#f8fafc",
    black: "#0f172a",
    red: "#ef4444",
    green: "#22c55e",
    yellow: "#f59e0b",
    blue: "#60a5fa",
    magenta: "#c084fc",
    cyan: "#22d3ee",
    white: "#e2e8f0",
    brightBlack: "#334155",
    brightRed: "#f87171",
    brightGreen: "#4ade80",
    brightYellow: "#fbbf24",
    brightBlue: "#93c5fd",
    brightMagenta: "#d8b4fe",
    brightCyan: "#67e8f9",
    brightWhite: "#f8fafc",
  };
}
