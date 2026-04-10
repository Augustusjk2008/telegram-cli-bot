import { AttachAddon } from "@xterm/addon-attach";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";

export type TerminalSessionOptions = {
  token: string;
  cwd: string;
  shell?: string;
  onOpen?: () => void;
  onClose?: () => void;
  onError?: (message: string) => void;
  onPtyMode?: (enabled: boolean) => void;
};

export type TerminalSession = {
  term: Terminal;
  connect: () => void;
  dispose: () => void;
  fit: () => void;
  focus: () => void;
  sendControl: (sequence: string) => void;
  sendText: (text: string) => void;
};

export function createTerminalSession(container: HTMLElement, options: TerminalSessionOptions): TerminalSession {
  const term = new Terminal({
    cursorBlink: true,
    convertEol: false,
    fontSize: 14,
    fontFamily: '"Cascadia Code", "Consolas", "Courier New", monospace',
    theme: {
      background: "#0b1020",
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
    },
  });
  const fitAddon = new FitAddon();
  let socket: WebSocket | null = null;
  let attachAddon: AttachAddon | null = null;
  let initialMessageListener: ((event: MessageEvent) => void) | null = null;
  let isAttached = false;

  term.loadAddon(fitAddon);
  term.open(container);
  try {
    fitAddon.fit();
  } catch {
    // Hidden containers can report zero size; callers will re-fit after layout settles.
  }

  function cleanupSocket() {
    if (socket && initialMessageListener) {
      socket.removeEventListener("message", initialMessageListener);
    }
    initialMessageListener = null;
  }

  function handleTerminalError(message: string) {
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

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const socketUrl = `${protocol}//${window.location.host}/terminal/ws?token=${encodeURIComponent(options.token)}`;
    socket = new WebSocket(socketUrl);
    socket.binaryType = "arraybuffer";
    isAttached = false;

    socket.addEventListener("open", () => {
      socket?.send(JSON.stringify({
        shell: options.shell || "powershell",
        cwd: options.cwd,
      }));
    });

    initialMessageListener = (event: MessageEvent) => {
      cleanupSocket();

      if (typeof event.data === "string") {
        try {
          const payload = JSON.parse(event.data) as { error?: string; pty_mode?: boolean };
          if (payload.error) {
            handleTerminalError(payload.error);
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
    socket.addEventListener("close", () => {
      cleanupSocket();
      options.onClose?.();
    });
    socket.addEventListener("error", () => {
      handleTerminalError("终端连接失败");
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
      }
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
  };
}
