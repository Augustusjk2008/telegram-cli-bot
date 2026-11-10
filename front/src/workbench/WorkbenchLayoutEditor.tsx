import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  PANE_LABELS,
  WORKBENCH_PANE_IDS,
  type ResolvedPanePlacement,
  type ResolvedWorkbenchLayout,
  type WorkbenchPaneId,
} from "./workbenchLayout";
import { WORKBENCH_PANE_ICONS } from "./workbenchPaneIcons";

const DRAG_THRESHOLD_PX = 4;

type Props = {
  /** The editing geometry: every slot takes space and nothing is a rail. */
  resolved: ResolvedWorkbenchLayout;
  available: Readonly<Record<WorkbenchPaneId, boolean>>;
  collapsed: Readonly<Record<WorkbenchPaneId, boolean>>;
  onSwap: (a: WorkbenchPaneId, b: WorkbenchPaneId) => void;
  onReset: () => void;
  onDone: () => void;
};

type DragState = {
  pointerId: number;
  source: WorkbenchPaneId;
  startX: number;
  startY: number;
  active: boolean;
  /** Overlay rects cached at drag start; overlays do not move while dragging. */
  rects: Array<{ pane: WorkbenchPaneId; rect: DOMRect }>;
};

function hitTest(rects: DragState["rects"], x: number, y: number): WorkbenchPaneId | null {
  return rects.find(({ rect }) => x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom)?.pane ?? null;
}

function paneNote(pane: WorkbenchPaneId, placement: ResolvedPanePlacement, available: Props["available"], collapsed: Props["collapsed"]) {
  if (!available[pane]) return "当前不可用";
  if (collapsed[pane]) return placement.displayed ? "已折叠" : "已隐藏";
  return "";
}

/**
 * Rearrange-mode overlays, rendered as grid items on top of the pane sections. Swapping only
 * edits the layout state; the pane sections underneath never move in the DOM.
 */
export function WorkbenchLayoutEditor({ resolved, available, collapsed, onSwap, onReset, onDone }: Props) {
  const overlayRefs = useRef<Partial<Record<WorkbenchPaneId, HTMLDivElement | null>>>({});
  const dragRef = useRef<DragState | null>(null);
  const doneButtonRef = useRef<HTMLButtonElement | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;
  const [dragSource, setDragSource] = useState<WorkbenchPaneId | null>(null);
  const [dropTarget, setDropTarget] = useState<WorkbenchPaneId | null>(null);

  function cancelDrag() {
    dragRef.current = null;
    setDragSource(null);
    setDropTarget(null);
  }

  useEffect(() => {
    doneButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) {
        return;
      }
      event.preventDefault();
      // The first Escape cancels a drag in progress; otherwise Escape leaves rearrange mode.
      if (dragRef.current) {
        cancelDrag();
        return;
      }
      onDoneRef.current();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  function handlePointerDown(pane: WorkbenchPaneId, event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || (event.target as Element).closest("button")) {
      return;
    }
    dragRef.current = {
      pointerId: event.pointerId,
      source: pane,
      startX: event.clientX,
      startY: event.clientY,
      active: false,
      rects: [],
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    if (!drag.active) {
      if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < DRAG_THRESHOLD_PX) {
        return;
      }
      drag.active = true;
      drag.rects = WORKBENCH_PANE_IDS.flatMap((pane) => {
        const node = overlayRefs.current[pane];
        return node ? [{ pane, rect: node.getBoundingClientRect() }] : [];
      });
      setDragSource(drag.source);
    }
    const target = hitTest(drag.rects, event.clientX, event.clientY);
    setDropTarget(target && target !== drag.source ? target : null);
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) {
      return;
    }
    const target = drag.active ? hitTest(drag.rects, event.clientX, event.clientY) : null;
    cancelDrag();
    if (target && target !== drag.source) {
      onSwap(drag.source, target);
    }
  }

  function handlePointerCancel(event: ReactPointerEvent<HTMLDivElement>) {
    if (dragRef.current?.pointerId === event.pointerId) {
      cancelDrag();
    }
  }

  return (
    <>
      <div role="toolbar" aria-label="窗口布局编辑" className="workbench-layout-banner">
        <span className="workbench-layout-banner-text">拖动窗口到另一个窗口上即可交换位置</span>
        <button type="button" className="orbit-btn orbit-btn--ghost orbit-btn--sm text-xs" onClick={onReset}>
          恢复默认
        </button>
        <button ref={doneButtonRef} type="button" className="orbit-btn orbit-btn--primary orbit-btn--sm text-xs" onClick={onDone}>
          完成
        </button>
      </div>
      {WORKBENCH_PANE_IDS.map((pane) => {
        const placement = resolved.panes[pane];
        const label = PANE_LABELS[pane];
        const Icon = WORKBENCH_PANE_ICONS[pane];
        const note = paneNote(pane, placement, available, collapsed);
        return (
          <div
            key={pane}
            ref={(node) => {
              overlayRefs.current[pane] = node;
            }}
            role="group"
            aria-label={`${label}窗口`}
            data-testid={`workbench-layout-slot-${pane}`}
            data-layout-slot={placement.slot}
            data-placeholder={placement.displayed ? undefined : "true"}
            data-drag-source={dragSource === pane ? "true" : undefined}
            data-drop-target={dropTarget === pane ? "true" : undefined}
            className="workbench-layout-slot-overlay"
            style={{ gridColumn: placement.gridColumn, gridRow: placement.gridRow }}
            onPointerDown={(event) => handlePointerDown(pane, event)}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerCancel}
            onLostPointerCapture={handlePointerCancel}
          >
            <div className="workbench-layout-slot-body">
              <span className="workbench-layout-slot-title">
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {label}
              </span>
              {note ? <span className="workbench-layout-slot-note">{note}</span> : null}
              <span className="workbench-layout-slot-hint">拖到其他窗口上交换位置</span>
              <div className="workbench-layout-slot-actions">
                {WORKBENCH_PANE_IDS.filter((other) => other !== pane).map((other) => (
                  <button
                    key={other}
                    type="button"
                    aria-label={`将${label}与${PANE_LABELS[other]}交换位置`}
                    className="orbit-btn orbit-btn--secondary orbit-btn--sm text-xs"
                    onClick={() => onSwap(pane, other)}
                  >
                    ⇄ {PANE_LABELS[other]}
                  </button>
                ))}
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}
