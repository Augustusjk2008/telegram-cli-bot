export type DebugSessionEvent = {
  type: string;
  payload?: Record<string, unknown>;
};

export type DebugSessionOptions = {
  token?: string;
  botAlias: string;
  onEvent?: (event: DebugSessionEvent) => void;
  onError?: (message: string) => void;
  onOpen?: () => void;
  onClose?: () => void;
};

export type DebugSessionHandle = {
  connect: () => Promise<boolean>;
  send: (message: Record<string, unknown>) => boolean;
  dispose: () => void;
  isOpen: () => boolean;
};

function buildDebugSessionUrl({ token = "", botAlias }: Pick<DebugSessionOptions, "token" | "botAlias">) {
  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
  const url = new URL("/debug/ws", origin);
  if (token.trim()) {
    url.searchParams.set("token", token.trim());
  }
  url.searchParams.set("alias", botAlias);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function createDebugSession({
  token = "",
  botAlias,
  onEvent,
  onError,
  onOpen,
  onClose,
}: DebugSessionOptions): DebugSessionHandle {
  let socket: WebSocket | null = null;
  let disposed = false;
  let pendingResolvers: Array<(connected: boolean) => void> = [];

  const settlePending = (connected: boolean) => {
    const resolvers = pendingResolvers;
    pendingResolvers = [];
    resolvers.forEach((resolve) => resolve(connected));
  };

  const cleanupSocket = (target?: WebSocket | null) => {
    if (!target) {
      return;
    }
    if (socket === target) {
      socket = null;
    }
  };

  return {
    async connect() {
      if (disposed || typeof WebSocket === "undefined") {
        return false;
      }
      if (socket?.readyState === WebSocket.OPEN) {
        return true;
      }
      if (socket?.readyState === WebSocket.CONNECTING) {
        return new Promise<boolean>((resolve) => {
          pendingResolvers.push(resolve);
        });
      }

      const nextSocket = new WebSocket(buildDebugSessionUrl({ token, botAlias }));
      socket = nextSocket;
      return new Promise<boolean>((resolve) => {
        pendingResolvers.push(resolve);

        nextSocket.onopen = () => {
          if (disposed || socket !== nextSocket) {
            settlePending(false);
            return;
          }
          onOpen?.();
          settlePending(true);
        };

        nextSocket.onmessage = (event) => {
          if (typeof event.data !== "string") {
            return;
          }
          try {
            const parsed = JSON.parse(event.data) as DebugSessionEvent;
            if (parsed && typeof parsed === "object" && typeof parsed.type === "string") {
              onEvent?.(parsed);
            }
          } catch {
            onError?.("调试消息解析失败");
          }
        };

        nextSocket.onerror = () => {
          if (disposed) {
            return;
          }
          onError?.("调试连接失败");
          settlePending(false);
        };

        nextSocket.onclose = () => {
          cleanupSocket(nextSocket);
          if (!disposed) {
            onClose?.();
          }
          settlePending(false);
        };
      });
    },

    send(message) {
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        return false;
      }
      socket.send(JSON.stringify(message));
      return true;
    },

    dispose() {
      disposed = true;
      settlePending(false);
      const target = socket;
      cleanupSocket(target);
      if (target && (target.readyState === WebSocket.OPEN || target.readyState === WebSocket.CONNECTING)) {
        target.close();
      }
    },

    isOpen() {
      return Boolean(socket && socket.readyState === WebSocket.OPEN);
    },
  };
}
