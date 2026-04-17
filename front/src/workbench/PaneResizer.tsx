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
          ? "bg-[var(--border)] transition-colors hover:bg-[var(--accent)] cursor-col-resize"
          : "bg-[var(--border)] transition-colors hover:bg-[var(--accent)] cursor-row-resize"
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
    />
  );
}
