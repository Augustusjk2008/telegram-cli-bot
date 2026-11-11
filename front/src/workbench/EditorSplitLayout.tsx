import { useRef, type ReactNode } from "react";
import type { EditorGroupId, EditorGroupsState } from "./workbenchTypes";

type Props = {
  groups: EditorGroupsState;
  onFocusGroup: (groupId: EditorGroupId) => void;
  onResize: (ratio: number) => void;
  renderGroup: (groupId: EditorGroupId) => ReactNode;
};

export function EditorSplitLayout({ groups, onFocusGroup, onResize, renderGroup }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; ratio: number; width: number } | null>(null);
  const split = groups.right.paths.length > 0;
  function group(id: EditorGroupId) {
    return (
      <div
        key={id}
        role="group"
        aria-label={id === "left" ? "左侧编辑组" : "右侧编辑组"}
        data-testid={`editor-group-${id}`}
        data-editor-group={id}
        data-active={groups.activeGroupId === id ? "true" : "false"}
        className="editor-group min-h-0 min-w-0 overflow-hidden"
        onFocusCapture={() => onFocusGroup(id)}
        onPointerDownCapture={() => onFocusGroup(id)}
      >
        {renderGroup(id)}
      </div>
    );
  }
  return (
    <div
      ref={containerRef}
      className="grid h-full min-h-0 min-w-0 overflow-hidden"
      style={{ gridTemplateColumns: split ? `minmax(0, ${groups.splitRatio}fr) 6px minmax(0, ${1 - groups.splitRatio}fr)` : "minmax(0, 1fr)" }}
    >
      {group("left")}
      {split ? (
        <div
          key="divider"
          role="separator"
          aria-label="调整编辑组宽度"
          aria-orientation="vertical"
          aria-valuemin={20}
          aria-valuemax={80}
          aria-valuenow={Math.round(groups.splitRatio * 100)}
          tabIndex={0}
          className="cursor-col-resize touch-none bg-[var(--border)] hover:bg-[var(--accent)] focus-visible:bg-[var(--accent)] focus-visible:outline-none"
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            onResize(groups.splitRatio + (event.key === "ArrowLeft" ? -0.05 : 0.05));
          }}
          onPointerDown={(event) => {
            event.preventDefault();
            dragRef.current = { x: event.clientX, ratio: groups.splitRatio, width: Math.max(1, (containerRef.current?.clientWidth || 1) - 6) };
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            const drag = dragRef.current;
            if (drag) onResize(drag.ratio + (event.clientX - drag.x) / drag.width);
          }}
          onPointerUp={() => { dragRef.current = null; }}
          onPointerCancel={() => { dragRef.current = null; }}
          onLostPointerCapture={() => { dragRef.current = null; }}
          onDoubleClick={() => onResize(0.5)}
        />
      ) : null}
      {split ? group("right") : null}
    </div>
  );
}
