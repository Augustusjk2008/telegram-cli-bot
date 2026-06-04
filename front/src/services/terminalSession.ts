import { AttachAddon } from "@xterm/addon-attach";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import {
  DEFAULT_UI_THEME,
  getTerminalMinimumContrastRatio,
  getTerminalTheme,
  type UiThemeName,
} from "../theme";
import { buildApiUrl, buildWsUrl, publicApiBaseDiagnostics, type PublicBaseDiagnostics } from "../utils/publicBase";

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

function formatWsDiagnostics(socketUrl: string, diagnostics: PublicBaseDiagnostics): string {
  const path = displayWsPath(socketUrl);
  const baseSource = diagnostics.envKey ? `${diagnostics.source}:${diagnostics.envKey}` : diagnostics.source;
  const selectedBase = diagnostics.selectedBasePath || "/";
  const configuredBase = diagnostics.configuredBasePath || "/";
  return `路径 ${path}，页面 ${diagnostics.pagePath}，base ${selectedBase}（配置 ${configuredBase}，来源 ${baseSource}）`;
}

function formatWsCloseMessage(
  event: CloseEvent,
  socketUrl: string,
  diagnostics: PublicBaseDiagnostics,
  attached: boolean,
): string {
  const context = formatWsDiagnostics(socketUrl, diagnostics);
  const reason = event.reason ? `，原因：${event.reason}` : "";
  if (event.code === 1000 && attached) {
    return "";
  }
  if (event.code === 1008) {
    return `访问令牌无效或没有终端权限，WebSocket 已关闭（${context}，code ${event.code}${reason}）`;
  }
  if (event.code === 1006) {
    return `终端已启动，但 WebSocket 连接失败（${context}，code ${event.code}）。请检查地址/base path 或反向代理是否转发 WebSocket`;
  }
  return `终端 WebSocket 已关闭（${context}，code ${event.code}${reason}）`;
}

function formatWsErrorMessage(socketUrl: string, diagnostics: PublicBaseDiagnostics) {
  return `终端已启动，但 WebSocket 连接失败（${formatWsDiagnostics(socketUrl, diagnostics)}）。请检查地址/base path、访问令牌或反向代理 WebSocket 转发`;
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
  let fallbackAbortController: AbortController | null = null;
  let fallbackActive = false;
  let fallbackStarted = false;
  let ignoreSocketEvents = false;
  let isAttached = false;
  let receivedInitialMessage = false;
  let reportedSocketError = false;
  const fallbackInputDisposable = term.onData((data) => {
    if (fallbackActive) {
      void postFallbackInput(data);
    }
  });

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
    if (fallbackActive) {
      void postFallbackInput(payload);
      return;
    }
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

  function cleanupFallback() {
    fallbackAbortController?.abort();
    fallbackAbortController = null;
    fallbackActive = false;
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

  function attachFallback() {
    if (isAttached) {
      return;
    }
    isAttached = true;
    options.onOpen?.();
  }

  async function postFallbackInput(payload: string | Record<string, unknown>) {
    if (!fallbackActive) {
      return;
    }
    const body = typeof payload === "string"
      ? { owner_id: options.ownerId, data: payload }
      : { owner_id: options.ownerId, ...payload };
    try {
      await fetch(buildApiUrl("/api/terminal/session/input"), {
        method: "POST",
        cache: "no-store",
        headers: {
          Authorization: `Bearer ${options.token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });
    } catch {
      // The stream side reports connection failures; input POST failures are transient while reconnecting.
    }
  }

  function decodeBase64Bytes(value: string): Uint8Array {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  }

  function handleFallbackEvent(eventType: string, payload: Record<string, unknown>) {
    if (eventType === "ready") {
      if (typeof payload.pty_mode === "boolean") {
        options.onPtyMode?.(payload.pty_mode);
      }
      attachFallback();
      return;
    }
    if (eventType === "output" && typeof payload.data === "string") {
      term.write(decodeBase64Bytes(payload.data));
      attachFallback();
    }
  }

  async function readFallbackStream(response: Response) {
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("浏览器不支持终端 HTTP 流");
    }
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split(/\n\n/);
      buffer = events.pop() ?? "";
      for (const rawEvent of events) {
        const lines = rawEvent.split(/\n/);
        const typeLine = lines.find((line) => line.startsWith("event:"));
        const dataLine = lines.find((line) => line.startsWith("data:"));
        if (!dataLine) {
          continue;
        }
        const eventType = typeLine ? typeLine.slice("event:".length).trim() : "message";
        try {
          const payload = JSON.parse(dataLine.slice("data:".length).trim()) as Record<string, unknown>;
          handleFallbackEvent(eventType, payload);
        } catch {
          // Ignore malformed SSE frames.
        }
      }
    }
  }

  function startHttpFallback(reason: string) {
    if (fallbackStarted || fallbackActive) {
      return;
    }
    fallbackStarted = true;
    ignoreSocketEvents = true;
    cleanupSocket();
    socket?.close();
    socket = null;
    attachAddon?.dispose();
    attachAddon = null;
    fallbackAbortController = new AbortController();
    const streamUrl = buildApiUrl("/api/terminal/session/stream", {
      owner_id: options.ownerId,
      from_seq: options.fromSeq ?? 0,
    });
    const controller = fallbackAbortController;
    fallbackActive = true;
    options.onError?.(`${reason}，已切换到 HTTP 终端流`);
    void fetch(streamUrl, {
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${options.token}`,
      },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          const text = await response.text().catch(() => "");
          throw new Error(text || `HTTP ${response.status}`);
        }
        await readFallbackStream(response);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        handleTerminalError(err instanceof Error ? `终端 HTTP 流连接失败：${err.message}` : "终端 HTTP 流连接失败");
      })
      .finally(() => {
        if (controller.signal.aborted) {
          return;
        }
        fallbackActive = false;
        fallbackAbortController = null;
        options.onClose?.();
      });
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const params = new URLSearchParams({
      token: options.token,
      owner_id: options.ownerId,
    });
    const wsDiagnostics = publicApiBaseDiagnostics();
    const socketUrl = buildWsUrl("/terminal/ws", params);
    currentSocketUrl = socketUrl;
    socket = new WebSocket(socketUrl);
    socket.binaryType = "arraybuffer";
    isAttached = false;
    receivedInitialMessage = false;
    reportedSocketError = false;
    ignoreSocketEvents = false;

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
      if (ignoreSocketEvents) {
        return;
      }
      cleanupSocket();
      const message = formatWsCloseMessage(
        event,
        currentSocketUrl || socketUrl,
        wsDiagnostics,
        isAttached || receivedInitialMessage,
      );
      if (event.code === 1006 && !isAttached && !receivedInitialMessage) {
        startHttpFallback(message || "终端 WebSocket 连接失败");
        return;
      }
      if (message && !reportedSocketError) {
        handleTerminalError(message);
      }
      options.onClose?.();
    });
    socket.addEventListener("error", () => {
      if (ignoreSocketEvents) {
        return;
      }
      if (!isAttached && !receivedInitialMessage) {
        startHttpFallback(formatWsErrorMessage(currentSocketUrl || socketUrl, wsDiagnostics));
        return;
      }
      handleTerminalError(formatWsErrorMessage(currentSocketUrl || socketUrl, wsDiagnostics));
    });
  }

  return {
    term,
    connect,
    dispose: () => {
      cleanupSocket();
      cleanupFallback();
      fallbackInputDisposable.dispose();
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
      if (fallbackActive) {
        void postFallbackInput(sequence);
        return;
      }
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(sequence);
      }
    },
    sendText: (text: string) => {
      if (fallbackActive) {
        void postFallbackInput(text);
        return;
      }
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
