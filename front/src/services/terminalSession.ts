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
import {
  decodeTerminalV2Frame,
  TerminalConnectionGeneration,
  TERMINAL_PROTOCOL_VERSION,
  TerminalRecoveryTracker,
  type TerminalRecoverySnapshot,
} from "../terminal/terminalRecovery";
import { TerminalSseParser } from "./terminalSseParser";

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
  onRecoveryState?: (state: TerminalRecoverySnapshot) => void;
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
  getRecoveryState: () => TerminalRecoverySnapshot;
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
  if ((event.code === 1000 || event.code === 1005) && attached) {
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

type TerminalWsProbeData = {
  path?: string;
  configured_base_path?: string;
  auth_status?: string;
  auth_error?: string;
  origin_allowed?: boolean;
  host?: string;
  forwarded_host?: string;
  forwarded_proto?: string;
};

function formatProbeDiagnostics(data: TerminalWsProbeData, diagnostics: PublicBaseDiagnostics): string {
  const authStatus = String(data.auth_status || "");
  const authError = String(data.auth_error || "");
  const configuredBase = String(data.configured_base_path || "");
  const selectedBase = diagnostics.selectedBasePath || "";
  const baseText = `后端 base ${configuredBase || "/"}`;
  if (selectedBase && configuredBase && selectedBase !== configuredBase) {
    return `诊断：HTTP 探针已到达后端，但页面 base 是 ${selectedBase}，${baseText}，请检查运行时 base path 配置。`;
  }
  if (authStatus && authStatus !== "ok") {
    return `诊断：HTTP 探针已到达后端，但鉴权状态为 ${authStatus}${authError ? `（${authError}）` : ""}，请重新登录后再试。`;
  }
  if (data.origin_allowed === false) {
    const forwarded = data.forwarded_host ? `，代理 Host ${data.forwarded_host}${data.forwarded_proto ? `/${data.forwarded_proto}` : ""}` : "";
    return `诊断：HTTP 探针已到达后端且 token 有效，${baseText}，但 Origin/代理头不匹配${forwarded}；若仍失败，重点检查反向代理的 WebSocket Upgrade 转发。`;
  }
  return `诊断：HTTP 探针已到达后端且鉴权通过，${baseText}；WebSocket 仍失败时，通常是反向代理没有转发 Upgrade/Connection 头。`;
}

async function fetchWsProbe(token: string, ownerId: string, diagnostics: PublicBaseDiagnostics): Promise<string> {
  const probeUrl = buildApiUrl("/terminal/ws-probe", {
    owner_id: ownerId,
  });
  const response = await fetch(probeUrl, {
    cache: "no-store",
    credentials: "same-origin",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    const detail = text.trim().slice(0, 160);
    return `诊断：HTTP 探针返回 HTTP ${response.status}${detail ? `（${detail}）` : ""}，说明 base path 或代理转发也需要检查。`;
  }
  const payload = await response.json().catch(() => null) as { data?: TerminalWsProbeData } | null;
  if (!payload?.data || typeof payload.data !== "object") {
    return "诊断：HTTP 探针已返回，但内容无法解析，请查看后端日志中的终端 WebSocket 探针记录。";
  }
  return formatProbeDiagnostics(payload.data, diagnostics);
}

function authHeaders(token: string): Record<string, string> {
  const trimmed = token.trim();
  return trimmed ? { Authorization: `Bearer ${trimmed}` } : {};
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
  let v2MessageListener: ((event: MessageEvent) => void) | null = null;
  let fallbackAbortController: AbortController | null = null;
  let fallbackActive = false;
  let fallbackStarted = false;
  let ignoreSocketEvents = false;
  let isAttached = false;
  let receivedInitialMessage = false;
  let reportedSocketError = false;
  let probeStarted = false;
  let protocolVersion = 1;
  let disposed = false;
  let reconnectTimer: number | null = null;
  let reconnectAttempt = 0;
  let v2MessageChain = Promise.resolve();
  const connectionGenerations = new TerminalConnectionGeneration();
  const recovery = new TerminalRecoveryTracker(options.fromSeq ?? 0);
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
    if (socket && v2MessageListener) {
      socket.removeEventListener("message", v2MessageListener);
    }
    initialMessageListener = null;
    v2MessageListener = null;
  }

  function notifyRecoveryState() {
    options.onRecoveryState?.(recovery.getSnapshot());
  }

  function resetTerminalOutput(message?: string) {
    term.reset();
    term.clear();
    if (message) {
      options.onError?.(message);
    }
  }

  function applyV2Output(sequence: number, payload: Uint8Array) {
    const accepted = recovery.accept(sequence);
    if (accepted.duplicate) {
      return;
    }
    if (accepted.gap) {
      resetTerminalOutput(`终端输出序列不连续（${accepted.previous + 1}-${sequence - 1}），正在请求重放`);
      notifyRecoveryState();
      if (fallbackActive) {
        cleanupFallback();
        fallbackStarted = false;
        window.setTimeout(() => startHttpFallback("终端输出缺口"), 0);
      } else {
        socket?.close(1012, "sequence gap");
      }
      return;
    }
    term.write(payload);
    notifyRecoveryState();
  }

  function handleV2Control(payload: Record<string, unknown>) {
    const streamId = String(payload.stream_id || payload.streamId || "");
    const stream = recovery.beginStream(streamId);
    if (stream.changed) {
      resetTerminalOutput("终端进程已重建，已切换到新的输出流");
    }
    const type = String(payload.type || payload.kind || "");
    if (type === "gap" || type === "reset" || payload.snapshot_required === true) {
      const gapTo = Number(payload.gap_to || payload.sequence || 0);
      recovery.applyGap(streamId, Number.isFinite(gapTo) ? gapTo : 0);
      resetTerminalOutput("终端输出存在缺口，已清屏并恢复可用尾部");
    }
    notifyRecoveryState();
  }

  async function handleV2Message(event: MessageEvent, generation: number) {
    if (!connectionGenerations.isCurrent(generation)) return;
    if (typeof event.data === "string") {
      try {
        handleV2Control(JSON.parse(event.data) as Record<string, unknown>);
      } catch {
        // v2 text frames are control envelopes; malformed frames are ignored.
      }
      return;
    }
    const buffer = event.data instanceof ArrayBuffer
      ? event.data
      : event.data instanceof Blob ? await event.data.arrayBuffer() : null;
    if (!buffer || !connectionGenerations.isCurrent(generation)) {
      return;
    }
    const frame = decodeTerminalV2Frame(buffer);
    if (!frame) {
      handleTerminalError("终端 v2 输出帧格式无效");
      return;
    }
    if ((frame.flags & 1) !== 0) {
      recovery.applyGap(recovery.getSnapshot().streamId, frame.sequence);
      resetTerminalOutput("终端输出存在缺口，已清屏并恢复可用尾部");
      notifyRecoveryState();
      return;
    }
    applyV2Output(frame.sequence, frame.payload);
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

  function attachV2Socket(generation: number) {
    if (!socket || isAttached) {
      return;
    }
    isAttached = true;
    v2MessageListener = (event) => {
      v2MessageChain = v2MessageChain.then(() => handleV2Message(event, generation));
    };
    socket.addEventListener("message", v2MessageListener);
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
        credentials: "same-origin",
        headers: {
          ...authHeaders(options.token),
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
      if (Number(payload.protocol_version || 1) >= TERMINAL_PROTOCOL_VERSION) {
        protocolVersion = TERMINAL_PROTOCOL_VERSION;
        handleV2Control(payload);
      }
      if (typeof payload.pty_mode === "boolean") {
        options.onPtyMode?.(payload.pty_mode);
      }
      attachFallback();
      return;
    }
    if (eventType === "gap" || eventType === "reset") {
      handleV2Control({ ...payload, type: eventType });
      return;
    }
    if (eventType === "output" && typeof payload.data === "string") {
      const bytes = decodeBase64Bytes(payload.data);
      const sequence = Number(payload.sequence || 0);
      if (protocolVersion >= TERMINAL_PROTOCOL_VERSION && sequence > 0) {
        applyV2Output(sequence, bytes);
      } else {
        term.write(bytes);
      }
      attachFallback();
    }
  }

  async function readFallbackStream(response: Response) {
    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error("浏览器不支持终端 HTTP 流");
    }
    const parser = new TerminalSseParser(({ event, id, data }) => {
      try {
        const payload = JSON.parse(data) as Record<string, unknown>;
        if (id && payload.sequence === undefined) payload.sequence = Number(id) || 0;
        handleFallbackEvent(event, payload);
      } catch {
        // Ignore malformed SSE frames without losing the following frame.
      }
    });
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      parser.push(value);
    }
    parser.finish();
  }

  function startHttpFallback(reason: string) {
    if (fallbackStarted || fallbackActive) {
      return;
    }
    fallbackStarted = true;
    connectionGenerations.next();
    ignoreSocketEvents = true;
    cleanupSocket();
    socket?.close();
    socket = null;
    attachAddon?.dispose();
    attachAddon = null;
    fallbackAbortController = new AbortController();
    const streamUrl = buildApiUrl("/api/terminal/session/stream", {
      owner_id: options.ownerId,
      protocol: TERMINAL_PROTOCOL_VERSION,
      version: TERMINAL_PROTOCOL_VERSION,
      from_seq: recovery.getSnapshot().lastAppliedSequence,
      after_sequence: recovery.getSnapshot().lastAppliedSequence,
    });
    const controller = fallbackAbortController;
    fallbackActive = true;
    options.onError?.(`${reason}，已切换到 HTTP 终端流`);
    void fetch(streamUrl, {
      cache: "no-store",
      credentials: "same-origin",
      headers: authHeaders(options.token),
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
        fallbackStarted = false;
        fallbackAbortController = null;
        options.onClose?.();
        if (!disposed) {
          window.setTimeout(() => startHttpFallback("终端 HTTP 流已结束，正在恢复"), 250);
        }
      });
    if (!probeStarted) {
      probeStarted = true;
      const diagnostics = publicApiBaseDiagnostics();
      void fetchWsProbe(options.token, options.ownerId, diagnostics)
        .then((probeMessage) => {
          if (probeMessage) {
            options.onError?.(`${reason}，已切换到 HTTP 终端流。${probeMessage}`);
          }
        })
        .catch((err: unknown) => {
          const detail = err instanceof Error && err.message ? `：${err.message}` : "";
          options.onError?.(`${reason}，已切换到 HTTP 终端流。诊断：HTTP 探针无法完成${detail}`);
        });
    }
  }

  function scheduleReconnect() {
    if (disposed || fallbackActive || reconnectTimer !== null) {
      return;
    }
    const delay = Math.min(5_000, 250 * (2 ** reconnectAttempt));
    reconnectAttempt += 1;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  function connect() {
    if (disposed) {
      return;
    }
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const params = new URLSearchParams({
      owner_id: options.ownerId,
    });
    const wsDiagnostics = publicApiBaseDiagnostics();
    const socketUrl = buildWsUrl("/terminal/ws", params);
    currentSocketUrl = socketUrl;
    socket = new WebSocket(socketUrl);
    const connectionSocket = socket;
    const connectionGeneration = connectionGenerations.next();
    socket.binaryType = "arraybuffer";
    isAttached = false;
    receivedInitialMessage = false;
    reportedSocketError = false;
    ignoreSocketEvents = false;

    socket.addEventListener("open", () => {
      if (!connectionGenerations.isCurrent(connectionGeneration)) return;
      reconnectAttempt = 0;
      const geometry = getGeometry();
      const afterSequence = recovery.getSnapshot().lastAppliedSequence;
      sendJson({
        owner_id: options.ownerId,
        protocol_version: TERMINAL_PROTOCOL_VERSION,
        version: TERMINAL_PROTOCOL_VERSION,
        from_seq: afterSequence,
        after_sequence: afterSequence,
        ...(geometry ? { cols: geometry.cols, rows: geometry.rows } : {}),
      });
    });

    initialMessageListener = (event: MessageEvent) => {
      if (!connectionGenerations.isCurrent(connectionGeneration)) return;
      receivedInitialMessage = true;
      cleanupSocket();

      if (typeof event.data === "string") {
        try {
          const payload = JSON.parse(event.data) as {
            error?: string;
            pty_mode?: boolean | null;
            protocol_version?: number;
            stream_id?: string;
          };
          if (payload.error) {
            handleTerminalError(`终端 WebSocket 连接被后端拒绝：${payload.error}`);
            return;
          }
          if (Number(payload.protocol_version || 1) >= TERMINAL_PROTOCOL_VERSION) {
            protocolVersion = TERMINAL_PROTOCOL_VERSION;
            handleV2Control(payload as Record<string, unknown>);
            if (typeof payload.pty_mode === "boolean") {
              options.onPtyMode?.(payload.pty_mode);
            }
            attachV2Socket(connectionGeneration);
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
        void event.data.arrayBuffer().then((buffer) => {
          if (connectionGenerations.isCurrent(connectionGeneration) && socket === connectionSocket) {
            term.write(new Uint8Array(buffer));
          }
        });
      }
      attachToSocket();
    };

    socket.addEventListener("message", initialMessageListener);
    socket.addEventListener("close", (event) => {
      if (!connectionGenerations.isCurrent(connectionGeneration)) return;
      if (ignoreSocketEvents) {
        return;
      }
      cleanupSocket();
      socket = null;
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
      if (protocolVersion >= TERMINAL_PROTOCOL_VERSION && event.code !== 1000) {
        scheduleReconnect();
      }
    });
    socket.addEventListener("error", () => {
      if (!connectionGenerations.isCurrent(connectionGeneration)) return;
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
      disposed = true;
      connectionGenerations.next();
      ignoreSocketEvents = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      cleanupSocket();
      cleanupFallback();
      fallbackInputDisposable.dispose();
      attachAddon?.dispose();
      attachAddon = null;
      socket?.close(1000);
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
    getRecoveryState: () => recovery.getSnapshot(),
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
