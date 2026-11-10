import type { CSSProperties } from "react";

type PaneResizerProps = {
  ariaLabel: string;
  axis: "x" | "y";
  style?: CSSProperties;
  /** Receives the pointer delta from drag start; the handler from pointerdown stays in use for the whole drag. */
  onResizeDelta: (deltaPx: number) => void;
  onResizeStart?: () => void;
  onResizeEnd?: () => void;
};

export function PaneResizer({ ariaLabel, axis, style, onResizeDelta, onResizeStart, onResizeEnd }: PaneResizerProps) {
  return (
    <div
      role="separator"
      aria-label={ariaLabel}
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      style={style}
      className={
        axis === "x"
          ? "flex items-center justify-center bg-transparent cursor-col-resize"
          : "flex items-center justify-center bg-transparent cursor-row-resize"
      }
      onPointerDown={(event) => {
        const start = axis === "x" ? event.clientX : event.clientY;
        onResizeStart?.();

        const handleMove = (moveEvent: PointerEvent) => {
          const current = axis === "x" ? moveEvent.clientX : moveEvent.clientY;
          onResizeDelta(current - start);
        };

        const handleUp = () => {
          window.removeEventListener("pointermove", handleMove);
          window.removeEventListener("pointerup", handleUp);
          window.removeEventListener("pointercancel", handleUp);
          onResizeEnd?.();
        };

        window.addEventListener("pointermove", handleMove);
        window.addEventListener("pointerup", handleUp);
        window.addEventListener("pointercancel", handleUp);
      }}
    >
      <div
        aria-hidden="true"
        className="h-full w-full"
      />
    </div>
  );
}
