import { AttachAddon } from "@xterm/addon-attach";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import {
  DEFAULT_UI_THEME,
  getTerminalMinimumContrastRatio,
  getTerminalTheme,
  type UiThemeName,
} from "../theme";
import { buildWsUrl } from "../utils/publicBase";

export type TerminalSessionOptions = {
  token: string;
  ownerId: string;
  fromSeq?: number;
  fontSize?: number;
  themeName?: UiThemeName;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (message: string) => void;
  onPtyMode?: (enabled: boolean) => void;
};

export type TerminalGeometry = {
  cols: number;
  rows: number;
};

export type TerminalSession = {
  term: Terminal;
  connect: () => void;
  dispose: () => void;
  fit: () => TerminalGeometry | null;
  focus: () => void;
  sendControl: (sequence: string) => void;
  sendText: (text: string) => void;
  setTheme: (themeName: UiThemeName) => void;
};

function buildTerminalAppearance(themeName: UiThemeName) {
  return {
    minimumContrastRatio: getTerminalMinimumContrastRatio(themeName),
    theme: getTerminalTheme(themeName),
  };
}

function displayWsPath(socketUrl: string): string {
  try {
    const parsed = new URL(socketUrl, typeof window !== "undefined" ? window.location.origin : "http://localhost");
    return `${parsed.pathname}${parsed.search ? "?..." : ""}`;
  } catch {
    return socketUrl;
  }
}

function formatWsCloseMessage(event: CloseEvent, socketUrl: string, attached: boolean): string {
  const path = displayWsPath(socketUrl);
  const reason = event.reason ? `，原因：${event.reason}` : "";
  if (event.code === 1000 && attached) {
    return "";
  }
  if (event.code === 1008) {
    return `访问令牌无效或没有终端权限，WebSocket 已关闭（路径 ${path}，code ${event.code}${reason}）`;
  }
  if (event.code === 1006) {
    return `终端已启动，但 WebSocket 连接失败（路径 ${path}，code ${event.code}）。请检查地址/base path 或反向代理是否转发 WebSocket`;
  }
  return `终端 WebSocket 已关闭（路径 ${path}，code ${event.code}${reason}）`;
}

function formatWsErrorMessage(socketUrl: string) {
  const path = displayWsPath(socketUrl);
  return `终端已启动，但 WebSocket 连接失败（路径 ${path}）。请检查地址/base path、访问令牌或反向代理 WebSocket 转发`;
}

export function createTerminalSession(container: HTMLElement, options: TerminalSessionOptions): TerminalSession {
  const themeName = options.themeName ?? DEFAULT_UI_THEME;
  const term = new Terminal({
    cursorBlink: true,
    convertEol: false,
    fontSize: options.fontSize ?? 13,
    fontFamily: '"Cascadia Code", "Consolas", "Courier New", monospace',
    ...buildTerminalAppearance(themeName),
  });
  const fitAddon = new FitAddon();
  let socket: WebSocket | null = null;
  let currentSocketUrl = "";
  let attachAddon: AttachAddon | null = null;
  let initialMessageListener: ((event: MessageEvent) => void) | null = null;
  let isAttached = false;
  let receivedInitialMessage = false;
  let reportedSocketError = false;

  term.loadAddon(fitAddon);
  term.open(container);
  try {
    fitAddon.fit();
  } catch {
    // Hidden containers can report zero size; callers will re-fit after layout settles.
  }

  function getGeometry(): TerminalGeometry | null {
    if (term.cols < 1 || term.rows < 1) {
      return null;
    }
    return {
      cols: term.cols,
      rows: term.rows,
    };
  }

  function sendJson(payload: Record<string, unknown>) {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    }
  }

  function sendResize() {
    const geometry = getGeometry();
    if (geometry) {
      sendJson({
        type: "resize",
        cols: geometry.cols,
        rows: geometry.rows,
      });
    }
    return geometry;
  }

  function cleanupSocket() {
    if (socket && initialMessageListener) {
      socket.removeEventListener("message", initialMessageListener);
    }
    initialMessageListener = null;
  }

  function handleTerminalError(message: string) {
    if (!message) {
      return;
    }
    reportedSocketError = true;
    options.onError?.(message);
  }

  function attachToSocket() {
    if (!socket || isAttached) {
      return;
    }
    isAttached = true;
    attachAddon = new AttachAddon(socket);
    term.loadAddon(attachAddon);
    options.onOpen?.();
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const params = new URLSearchParams({
      token: options.token,
      owner_id: options.ownerId,
    });
    const socketUrl = buildWsUrl("/terminal/ws", params);
    currentSocketUrl = socketUrl;
    socket = new WebSocket(socketUrl);
    socket.binaryType = "arraybuffer";
    isAttached = false;
    receivedInitialMessage = false;
    reportedSocketError = false;

    socket.addEventListener("open", () => {
      const geometry = getGeometry();
      sendJson({
        owner_id: options.ownerId,
        from_seq: options.fromSeq ?? 0,
        ...(geometry ? { cols: geometry.cols, rows: geometry.rows } : {}),
      });
    });

    initialMessageListener = (event: MessageEvent) => {
      receivedInitialMessage = true;
      cleanupSocket();

      if (typeof event.data === "string") {
        try {
          const payload = JSON.parse(event.data) as { error?: string; pty_mode?: boolean | null };
          if (payload.error) {
            handleTerminalError(`终端 WebSocket 连接被后端拒绝：${payload.error}`);
            return;
          }
          if (typeof payload.pty_mode === "boolean") {
            options.onPtyMode?.(payload.pty_mode);
            attachToSocket();
            return;
          }
        } catch {
          term.write(event.data);
          attachToSocket();
          return;
        }
      }

      if (event.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(event.data));
      } else if (event.data instanceof Blob) {
        void event.data.arrayBuffer().then((buffer) => term.write(new Uint8Array(buffer)));
      }
      attachToSocket();
    };

    socket.addEventListener("message", initialMessageListener);
    socket.addEventListener("close", (event) => {
      cleanupSocket();
      const message = formatWsCloseMessage(event, currentSocketUrl || socketUrl, isAttached || receivedInitialMessage);
      if (message && !reportedSocketError) {
        handleTerminalError(message);
      }
      options.onClose?.();
    });
    socket.addEventListener("error", () => {
      handleTerminalError(formatWsErrorMessage(currentSocketUrl || socketUrl));
    });
  }

  return {
    term,
    connect,
    dispose: () => {
      cleanupSocket();
      attachAddon?.dispose();
      attachAddon = null;
      socket?.close();
      socket = null;
      term.dispose();
    },
    fit: () => {
      try {
        fitAddon.fit();
      } catch {
        // Ignore fit failures while the terminal is hidden or mid-layout.
        return null;
      }
      return sendResize();
    },
    focus: () => {
      term.focus();
      term.textarea?.focus();
    },
    sendControl: (sequence: string) => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(sequence);
      }
    },
    sendText: (text: string) => {
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(text);
      }
    },
    setTheme: (themeName: UiThemeName) => {
      const appearance = buildTerminalAppearance(themeName);
      term.options.minimumContrastRatio = appearance.minimumContrastRatio;
      term.options.theme = appearance.theme;
    },
  };
}
