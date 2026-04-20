type PaneResizerProps = {
  ariaLabel: string;
  axis: "x" | "y";
  onResizeDelta: (deltaPx: number) => void;
};

export function PaneResizer({ ariaLabel, axis, onResizeDelta }: PaneResizerProps) {
  return (
    <div
      role="separator"
      aria-label={ariaLabel}
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      className={
        axis === "x"
          ? "flex items-center justify-center bg-[var(--workbench-panel-bg)] cursor-col-resize"
          : "flex items-center justify-center bg-[var(--workbench-panel-bg)] cursor-row-resize"
      }
      onPointerDown={(event) => {
        const start = axis === "x" ? event.clientX : event.clientY;

        const handleMove = (moveEvent: PointerEvent) => {
          const current = axis === "x" ? moveEvent.clientX : moveEvent.clientY;
          onResizeDelta(current - start);
        };

        const handleUp = () => {
          window.removeEventListener("pointermove", handleMove);
          window.removeEventListener("pointerup", handleUp);
          window.removeEventListener("pointercancel", handleUp);
        };

        window.addEventListener("pointermove", handleMove);
        window.addEventListener("pointerup", handleUp);
        window.addEventListener("pointercancel", handleUp);
      }}
    >
      <div
        aria-hidden="true"
        className={
          axis === "x"
            ? "h-full w-px bg-[var(--workbench-hairline)] transition-colors hover:bg-[var(--accent)]"
            : "h-px w-full bg-[var(--workbench-hairline)] transition-colors hover:bg-[var(--accent)]"
        }
      />
    </div>
  );
}
