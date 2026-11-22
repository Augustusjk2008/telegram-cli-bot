import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { LoaderCircle, Pause, Square, Volume2 } from "lucide-react";
import { readAloudText } from "../utils/readAloudText";
import {
  pauseReadAloud, resumeReadAloud, startReadAloud, stopReadAloud, supportsReadAloud, type ReadAloudState,
} from "../services/browserReadAloud";

export const ReadAloudContext = createContext({ scope: "", enabled: true });

const buttonClass = "inline-flex h-6 w-6 items-center justify-center rounded-md border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-bg)] text-[var(--muted)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)] disabled:cursor-not-allowed disabled:opacity-50";

export function ChatReadAloudButton({ text }: { text: string }) {
  const { scope, enabled } = useContext(ReadAloudContext);
  const owner = useRef(Symbol("answer-read-aloud"));
  const [state, setState] = useState<ReadAloudState>({ status: "idle" });
  const speechText = useMemo(() => readAloudText(text), [text]);
  const supported = supportsReadAloud();

  useEffect(() => {
    setState({ status: "idle" });
    const id = owner.current;
    return () => stopReadAloud(id);
  }, [text, scope, enabled]);

  if (!speechText) return null;
  const active = ["loading", "playing", "paused"].includes(state.status);
  const label = !supported ? "当前浏览器不支持朗读"
    : !enabled ? "当前无法朗读"
      : state.status === "loading" ? "正在准备朗读"
        : state.status === "playing" ? "暂停朗读"
          : state.status === "paused" ? "继续朗读" : "朗读回答";

  return (
    <>
      <button
        type="button"
        aria-label={label}
        title={label}
        disabled={!supported || !enabled || state.status === "loading"}
        className={buttonClass}
        onClick={() => {
          if (state.status === "playing") pauseReadAloud(owner.current);
          else if (state.status === "paused") resumeReadAloud(owner.current);
          else startReadAloud(owner.current, speechText, setState);
        }}
      >
        {state.status === "loading" ? <LoaderCircle aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
          : state.status === "playing" ? <Pause aria-hidden="true" className="h-3.5 w-3.5" />
            : <Volume2 aria-hidden="true" className="h-3.5 w-3.5" />}
      </button>
      {active ? (
        <button type="button" aria-label="停止朗读" title="停止朗读" className={buttonClass} onClick={() => stopReadAloud(owner.current)}>
          <Square aria-hidden="true" className="h-3.5 w-3.5" />
        </button>
      ) : null}
      {state.error ? <span role="alert" className="basis-full text-right text-xs text-[var(--feedback-error-text-deep)]">{state.error}</span> : null}
    </>
  );
}
