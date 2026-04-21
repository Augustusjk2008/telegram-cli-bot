import { useEffect, useRef, useState } from "react";
import { createDebugSession, type DebugSessionEvent, type DebugSessionHandle } from "../services/debugSession";
import type {
  DebugBreakpoint,
  DebugFrame,
  DebugProfile,
  DebugScope,
  DebugState,
  DebugVariable,
} from "../services/types";
import type { WebBotClient } from "../services/webBotClient";
import type { DebugWorkbenchStatus } from "./workbenchTypes";

const EMPTY_STATE: DebugState = {
  phase: "idle",
  message: "",
  breakpoints: [],
  frames: [],
  currentFrameId: "",
  scopes: [],
  variables: {},
};

const EMPTY_LAUNCH_FORM = {
  prepareCommand: "",
  remoteHost: "",
  remoteUser: "",
  remoteDir: "",
  remotePort: "",
  password: "",
  stopAtEntry: true,
};

type DebugLaunchForm = typeof EMPTY_LAUNCH_FORM;

type RevealLocation = {
  sourcePath: string;
  line?: number | null;
};

type Props = {
  authToken?: string;
  botAlias: string;
  client: WebBotClient;
  enabled?: boolean;
  onRevealLocation?: (location: RevealLocation) => void;
};

function normalizePath(path: string) {
  return path.replace(/\\/g, "/").replace(/\/+/g, "/").replace(/\/$/, "").toLowerCase();
}

function pathsMatch(left: string, right: string) {
  const normalizedLeft = normalizePath(left);
  const normalizedRight = normalizePath(right);
  if (!normalizedLeft || !normalizedRight) {
    return false;
  }
  return normalizedLeft === normalizedRight
    || normalizedLeft.endsWith(`/${normalizedRight}`)
    || normalizedRight.endsWith(`/${normalizedLeft}`);
}

function mapDebugVariable(raw: Record<string, unknown>): DebugVariable {
  return {
    name: String(raw.name || ""),
    value: String(raw.value || ""),
    ...(raw.type ? { type: String(raw.type) } : {}),
    ...(raw.variablesReference || raw.variables_reference
      ? { variablesReference: String(raw.variablesReference || raw.variables_reference || "") }
      : {}),
  };
}

function mapDebugState(raw: Record<string, unknown>): DebugState {
  return {
    phase: raw.phase as DebugState["phase"],
    message: String(raw.message || ""),
    breakpoints: Array.isArray(raw.breakpoints)
      ? raw.breakpoints
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
        .map((item) => ({
          source: String(item.source || ""),
          line: Number(item.line || 0),
          verified: Boolean(item.verified),
          status: String(item.status || (item.verified ? "verified" : "pending")) as DebugBreakpoint["status"],
          type: String(item.type || "line") as DebugBreakpoint["type"],
          function: String(item.function || ""),
          condition: String(item.condition || ""),
          hitCondition: String(item.hitCondition || item.hit_condition || ""),
          logMessage: String(item.logMessage || item.log_message || ""),
          message: String(item.message || ""),
        } satisfies DebugBreakpoint))
      : [],
    frames: Array.isArray(raw.frames)
      ? raw.frames
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
        .map((item) => ({
          id: String(item.id || ""),
          name: String(item.name || ""),
          source: String(item.source || ""),
          line: Number(item.line || 0),
          sourceResolved: Boolean(item.sourceResolved ?? item.source_resolved ?? true),
          sourceReason: String(item.sourceReason || item.source_reason || ""),
          originalSource: String(item.originalSource || item.original_source || ""),
        } satisfies DebugFrame))
      : [],
    currentFrameId: String(raw.current_frame_id || raw.currentFrameId || ""),
    scopes: Array.isArray(raw.scopes)
      ? raw.scopes
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
        .map((item) => ({
          name: String(item.name || ""),
          variablesReference: String(item.variablesReference || item.variables_reference || ""),
        } satisfies DebugScope))
      : [],
    variables: Object.fromEntries(
      Object.entries(raw.variables && typeof raw.variables === "object" ? raw.variables as Record<string, unknown> : {})
        .map(([key, value]) => [
          key,
          Array.isArray(value)
            ? value
              .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
              .map(mapDebugVariable)
            : [],
        ]),
    ) as Record<string, DebugVariable[]>,
  };
}

function statusText(phase: DebugState["phase"]) {
  if (phase === "preparing") {
    return "调试准备中";
  }
  if (phase === "deploying" || phase === "starting_gdb" || phase === "connecting_remote") {
    return "调试连接中";
  }
  if (phase === "paused") {
    return "调试已暂停";
  }
  if (phase === "running") {
    return "调试运行中";
  }
  if (phase === "terminating") {
    return "调试停止中";
  }
  if (phase === "error") {
    return "调试错误";
  }
  return "调试未启动";
}

function currentFrame(state: DebugState) {
  return state.frames.find((item) => item.id === state.currentFrameId) || state.frames[0] || null;
}

export function useDebugSession({
  authToken = "",
  botAlias,
  client,
  enabled = false,
  onRevealLocation,
}: Props) {
  const [activated, setActivated] = useState(enabled);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profile, setProfile] = useState<DebugProfile | null>(null);
  const [state, setState] = useState<DebugState>(EMPTY_STATE);
  const [prepareLogs, setPrepareLogs] = useState<string[]>([]);
  const [launchForm, setLaunchForm] = useState<DebugLaunchForm>(EMPTY_LAUNCH_FORM);
  const sessionRef = useRef<DebugSessionHandle | null>(null);
  const defaultsAppliedRef = useRef("");
  const revealLocationRef = useRef(onRevealLocation);
  const eventHandlerRef = useRef<(event: DebugSessionEvent) => void>(() => undefined);

  revealLocationRef.current = onRevealLocation;

  function revealLocation(sourcePath: string, line?: number | null) {
    if (!sourcePath) {
      return;
    }
    revealLocationRef.current?.({
      sourcePath,
      ...(typeof line === "number" && line > 0 ? { line } : {}),
    });
  }

  eventHandlerRef.current = (event) => {
    const payload = event.payload && typeof event.payload === "object" ? event.payload : {};
    if (event.type === "state") {
      setState(mapDebugState(payload));
      return;
    }
    if (event.type === "prepareLog") {
      const line = String(payload.line || "");
      if (line) {
        setPrepareLogs((current) => [...current, line]);
      }
      return;
    }
    if (event.type === "breakpoints") {
      const items = Array.isArray(payload.items) ? payload.items : [];
      setState((current) => ({
        ...current,
        breakpoints: items
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
          .map((item) => ({
            source: String(item.source || ""),
            line: Number(item.line || 0),
            verified: Boolean(item.verified),
            status: String(item.status || (item.verified ? "verified" : "pending")) as DebugBreakpoint["status"],
            type: String(item.type || "line") as DebugBreakpoint["type"],
            function: String(item.function || ""),
            condition: String(item.condition || ""),
            hitCondition: String(item.hitCondition || item.hit_condition || ""),
            logMessage: String(item.logMessage || item.log_message || ""),
            message: String(item.message || ""),
          })),
      }));
      return;
    }
    if (event.type === "stackTrace") {
      const frames = Array.isArray(payload.frames) ? payload.frames : [];
      setState((current) => ({
        ...current,
        frames: frames
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
          .map((item) => ({
            id: String(item.id || ""),
            name: String(item.name || ""),
            source: String(item.source || ""),
            line: Number(item.line || 0),
            sourceResolved: Boolean(item.sourceResolved ?? item.source_resolved ?? true),
            sourceReason: String(item.sourceReason || item.source_reason || ""),
            originalSource: String(item.originalSource || item.original_source || ""),
          })),
      }));
      return;
    }
    if (event.type === "scopes") {
      const scopes = Array.isArray(payload.scopes) ? payload.scopes : [];
      const frameId = String(payload.frameId || "");
      setState((current) => ({
        ...current,
        currentFrameId: frameId || current.currentFrameId,
        scopes: scopes
          .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
          .map((item) => ({
            name: String(item.name || ""),
            variablesReference: String(item.variablesReference || item.variables_reference || ""),
          })),
      }));
      return;
    }
    if (event.type === "variables") {
      const reference = String(payload.variablesReference || payload.variables_reference || "");
      const items = Array.isArray(payload.variables) ? payload.variables : [];
      if (!reference) {
        return;
      }
      setState((current) => ({
        ...current,
        variables: {
          ...current.variables,
          [reference]: items
            .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
            .map(mapDebugVariable),
        },
      }));
      return;
    }
    if (event.type === "stopped") {
      if (payload.sourceResolved !== false) {
        revealLocation(String(payload.source || ""), Number(payload.line || 0));
      }
      return;
    }
    if (event.type === "error") {
      setState((current) => ({
        ...current,
        phase: "error",
        message: String(payload.message || "调试失败"),
      }));
    }
  };

  async function ensureSession() {
    setActivated(true);
    if (!sessionRef.current) {
      sessionRef.current = createDebugSession({
        token: authToken,
        botAlias,
        onEvent: (event) => eventHandlerRef.current(event),
        onError: (message) => {
          setState((current) => ({
            ...current,
            phase: "error",
            message,
          }));
        },
      });
    }
    await sessionRef.current.connect();
    return sessionRef.current;
  }

  async function sendCommand(type: string, payload?: Record<string, unknown>) {
    const session = await ensureSession();
    const sent = session.send(payload ? { type, payload } : { type });
    if (!sent) {
      setState((current) => ({
        ...current,
        phase: "error",
        message: "调试连接不可用",
      }));
    }
  }

  useEffect(() => () => {
    sessionRef.current?.dispose();
    sessionRef.current = null;
  }, []);

  useEffect(() => {
    sessionRef.current?.dispose();
    sessionRef.current = null;
    defaultsAppliedRef.current = "";
    setActivated(enabled);
    setProfileLoading(false);
    setProfile(null);
    setState(EMPTY_STATE);
    setPrepareLogs([]);
    setLaunchForm(EMPTY_LAUNCH_FORM);
  }, [authToken, botAlias, client]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    setActivated(true);
    void ensureSession();
  }, [enabled]);

  useEffect(() => {
    if (!activated) {
      return;
    }
    let cancelled = false;
    setProfileLoading(true);
    void Promise.all([
      client.getDebugProfile(botAlias),
      client.getDebugState(botAlias),
    ])
      .then(([nextProfile, nextState]) => {
        if (cancelled) {
          return;
        }
        setProfile(nextProfile);
        setState(nextState);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setProfile(null);
        setState({
          ...EMPTY_STATE,
          phase: "error",
          message: error instanceof Error ? error.message : "读取调试状态失败",
        });
      })
      .finally(() => {
        if (!cancelled) {
          setProfileLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activated, botAlias, client]);

  useEffect(() => {
    if (!profile) {
      return;
    }
    const nextKey = [
      botAlias,
      profile.program,
      profile.prepareCommand,
      profile.remoteHost,
      profile.remoteUser,
      profile.remoteDir,
      profile.remotePort,
      profile.stopAtEntry,
    ].join("|");
    if (defaultsAppliedRef.current === nextKey) {
      return;
    }
    defaultsAppliedRef.current = nextKey;
    setLaunchForm({
      prepareCommand: profile.prepareCommand,
      remoteHost: profile.remoteHost,
      remoteUser: profile.remoteUser,
      remoteDir: profile.remoteDir,
      remotePort: profile.remotePort ? String(profile.remotePort) : "",
      password: "",
      stopAtEntry: profile.stopAtEntry,
    });
  }, [botAlias, profile]);

  const activeFrame = currentFrame(state);
  const targetHost = launchForm.remoteHost.trim() || profile?.remoteHost || "";
  const targetPort = launchForm.remotePort.trim() || (profile?.remotePort ? String(profile.remotePort) : "");

  const statusBar: DebugWorkbenchStatus = {
    phase: state.phase,
    connectionText: statusText(state.phase),
    ...(targetHost && targetPort ? { targetText: `${targetHost}:${targetPort}` } : {}),
    ...(activeFrame?.source ? { currentSourcePath: activeFrame.source } : {}),
    ...(activeFrame?.line ? { currentLine: activeFrame.line } : {}),
  };

  return {
    profile,
    profileLoading,
    state,
    prepareLogs,
    launchForm,
    launch: async () => {
      if (!profile) {
        return;
      }
      setPrepareLogs([]);
      setState((current) => ({
        ...current,
        phase: "preparing",
        message: "准备调试环境",
      }));
      const parsedPort = Number.parseInt(launchForm.remotePort.trim(), 10);
      await sendCommand("launch", {
        configName: profile.configName,
        remoteHost: launchForm.remoteHost.trim() || profile.remoteHost,
        remoteUser: launchForm.remoteUser.trim() || profile.remoteUser,
        remoteDir: launchForm.remoteDir.trim() || profile.remoteDir,
        remotePort: Number.isFinite(parsedPort) ? parsedPort : profile.remotePort,
        prepareCommand: launchForm.prepareCommand.trim() || profile.prepareCommand,
        password: launchForm.password,
        stopAtEntry: launchForm.stopAtEntry,
      });
    },
    stop: async () => {
      await sendCommand("terminate");
    },
    continueExecution: async () => {
      await sendCommand("continue");
    },
    pauseExecution: async () => {
      await sendCommand("pause");
    },
    next: async () => {
      await sendCommand("next");
    },
    stepIn: async () => {
      await sendCommand("stepIn");
    },
    stepOut: async () => {
      await sendCommand("stepOut");
    },
    selectFrame: async (frameId: string) => {
      const frame = state.frames.find((item) => item.id === frameId);
      if (frame?.sourceResolved !== false && frame.source && frame.source !== "??") {
        revealLocation(frame.source, frame.line);
      }
      await sendCommand("selectFrame", { frameId });
    },
    requestVariables: async (variablesReference: string) => {
      await sendCommand("variables", { variablesReference });
    },
    toggleBreakpoint: async (sourcePath: string, line: number) => {
      const canonicalSource = activeFrame && pathsMatch(activeFrame.source, sourcePath)
        ? activeFrame.source
        : state.breakpoints.find((item) => pathsMatch(item.source, sourcePath))?.source || sourcePath;
      const currentLines = Array.from(new Set(
        state.breakpoints
          .filter((item) => pathsMatch(item.source, sourcePath))
          .map((item) => item.line)
          .filter((item) => item > 0),
      )).sort((left, right) => left - right);
      const nextLines = currentLines.includes(line)
        ? currentLines.filter((item) => item !== line)
        : [...currentLines, line].sort((left, right) => left - right);
      await sendCommand("setBreakpoints", {
        source: canonicalSource,
        lines: nextLines,
      });
    },
    updateLaunchForm: (patch: Partial<DebugLaunchForm>) => {
      setLaunchForm((current) => ({
        ...current,
        ...patch,
      }));
    },
    breakpointLinesForPath: (path: string) => Array.from(new Set(
      state.breakpoints
        .filter((item) => pathsMatch(item.source, path))
        .map((item) => item.line)
        .filter((item) => item > 0),
    )).sort((left, right) => left - right),
    currentLineForPath: (path: string) => {
      const frame = currentFrame(state);
      if (!frame || frame.sourceResolved === false || !pathsMatch(frame.source, path)) {
        return null;
      }
      return frame.line || null;
    },
    statusBar,
  };
}
