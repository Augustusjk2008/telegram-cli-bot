import { useRef, useState } from "react";
import type { DragEvent, PointerEvent, RefObject } from "react";
import { clsx } from "clsx";
import { Hand, MousePointer2 } from "lucide-react";
import "./viewerTools.css";

export type ViewerTool = "select" | "hand";

const TOOL_OPTIONS = [
  { value: "select", label: "选择", Icon: MousePointer2 },
  { value: "hand", label: "抓手", Icon: Hand },
] as const;

// Controls inside the pannable area keep their normal click behaviour.
const INTERACTIVE_SELECTOR = "button, a[href], input, select, textarea, label, summary, [contenteditable='true']";

type PanState = {
  pointerId: number;
  clientX: number;
  clientY: number;
  x?: { element: HTMLElement; start: number };
  y?: { element: HTMLElement; start: number };
};

function scrollsOn(element: HTMLElement, axis: "x" | "y") {
  const style = getComputedStyle(element);
  const overflow = axis === "x" ? style.overflowX : style.overflowY;
  if (overflow !== "auto" && overflow !== "scroll") return false;
  return axis === "x"
    ? element.scrollWidth > element.clientWidth
    : element.scrollHeight > element.clientHeight;
}

/** Drag-to-scroll for the hand tool. Each axis pans the nearest scrollable ancestor up to `boundaryRef`. */
export function useViewerPan(tool: ViewerTool, boundaryRef: RefObject<HTMLElement | null>) {
  const [panning, setPanning] = useState(false);
  const pan = useRef<PanState | null>(null);
  const active = tool === "hand";

  function onPointerDown(event: PointerEvent<HTMLElement>) {
    // Touch already scrolls natively; only mouse/pen need emulated panning.
    if (!active || event.button !== 0 || event.pointerType === "touch") return;
    const target = event.target instanceof Element ? event.target : null;
    if (!target || target.closest(INTERACTIVE_SELECTOR)) return;
    const state: PanState = { pointerId: event.pointerId, clientX: event.clientX, clientY: event.clientY };
    const boundary = boundaryRef.current;
    for (let node: Element | null = target; node; node = node.parentElement) {
      if (node instanceof HTMLElement) {
        if (!state.x && scrollsOn(node, "x")) state.x = { element: node, start: node.scrollLeft };
        if (!state.y && scrollsOn(node, "y")) state.y = { element: node, start: node.scrollTop };
      }
      if (node === boundary || (state.x && state.y)) break;
    }
    event.preventDefault();
    if (!state.x && !state.y) return;
    pan.current = state;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setPanning(true);
  }

  function onPointerMove(event: PointerEvent<HTMLElement>) {
    const state = pan.current;
    if (!state || state.pointerId !== event.pointerId) return;
    if (state.x) state.x.element.scrollLeft = state.x.start - (event.clientX - state.clientX);
    if (state.y) state.y.element.scrollTop = state.y.start - (event.clientY - state.clientY);
  }

  function endPan(event: PointerEvent<HTMLElement>) {
    if (pan.current?.pointerId !== event.pointerId) return;
    pan.current = null;
    setPanning(false);
  }

  function onDragStart(event: DragEvent<HTMLElement>) {
    if (active) event.preventDefault();
  }

  return {
    className: clsx(active && "viewer-hand-tool", panning && "is-panning"),
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: endPan,
      onPointerCancel: endPan,
      onLostPointerCapture: endPan,
      onDragStart,
    },
  };
}

export function ViewerToolToggle({ tool, onChange, disabled = false }: {
  tool: ViewerTool;
  onChange: (tool: ViewerTool) => void;
  disabled?: boolean;
}) {
  return (
    <div role="group" aria-label="指针工具" className="inline-flex overflow-hidden rounded border border-[var(--border)]">
      {TOOL_OPTIONS.map(({ value, label, Icon }) => {
        const selected = tool === value;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={selected}
            disabled={disabled}
            title={value === "hand" ? "抓手：拖动画面平移" : "选择：选取和复制文字"}
            onClick={() => {
              if (value === "hand") window.getSelection()?.removeAllRanges();
              onChange(value);
            }}
            className={clsx(
              "inline-flex items-center gap-1 px-2 py-1 disabled:opacity-40",
              selected
                ? "bg-[var(--accent)]/10 text-[var(--accent)]"
                : "text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]",
            )}
          >
            <Icon size={14} aria-hidden="true" />
            <span>{label}</span>
          </button>
        );
      })}
    </div>
  );
}
