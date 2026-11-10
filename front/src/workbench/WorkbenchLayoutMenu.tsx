import { clsx } from "clsx";
import { ArrowLeftRight, Check, LayoutTemplate as LayoutTemplateIcon, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type MutableRefObject } from "react";
import { createPortal } from "react-dom";
import {
  getTemplateLayout,
  WORKBENCH_LAYOUT_TEMPLATES,
  type LayoutTemplate,
  type LayoutTemplateId,
  type WorkbenchLayoutState,
  type WorkbenchPaneId,
} from "./workbenchLayout";
import { WORKBENCH_PANE_ICONS } from "./workbenchPaneIcons";

const MENU_WIDTH_PX = 304;

type Props = {
  activeTemplate: LayoutTemplateId;
  /** Used to draw each preset's diagram with its current pane assignment. */
  layout: WorkbenchLayoutState;
  disabled?: boolean;
  /** Lets the workbench return focus to the trigger after rearrange mode ends. */
  triggerRef?: MutableRefObject<HTMLButtonElement | null>;
  onSelectTemplate: (id: LayoutTemplateId) => void;
  onStartRearrange: () => void;
  onResetTemplate: () => void;
};

type MenuPosition = { top: number; left: number; width: number; maxHeight: number };

function LayoutDiagram({ template, slots }: { template: LayoutTemplate; slots: Readonly<Record<string, WorkbenchPaneId>> }) {
  return (
    <span
      aria-hidden="true"
      className="workbench-layout-diagram"
      style={{ gridTemplateColumns: template.diagram.columns, gridTemplateRows: template.diagram.rows }}
    >
      {template.slots.map((slot) => {
        const pane = slots[slot];
        const Icon = WORKBENCH_PANE_ICONS[pane];
        const cell = template.diagram.cells[slot];
        return (
          <span
            key={slot}
            className="workbench-layout-diagram-cell"
            data-diagram-slot={slot}
            data-diagram-pane={pane}
            style={{ gridColumn: cell.column, gridRow: cell.row }}
          >
            <Icon className="h-2.5 w-2.5" />
          </span>
        );
      })}
    </span>
  );
}

export function WorkbenchLayoutMenu({
  activeTemplate,
  layout,
  disabled = false,
  triggerRef: externalTriggerRef,
  onSelectTemplate,
  onStartRearrange,
  onResetTemplate,
}: Props) {
  const [open, setOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<MenuPosition | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const activeOptionRef = useRef<HTMLButtonElement | null>(null);
  const idPrefix = useId();
  const menuPlaced = menuPosition !== null;
  const setTriggerNode = useCallback((node: HTMLButtonElement | null) => {
    triggerRef.current = node;
    if (externalTriggerRef) externalTriggerRef.current = node;
  }, [externalTriggerRef]);

  useEffect(() => {
    if (disabled) {
      setOpen(false);
    }
  }, [disabled]);

  useEffect(() => {
    if (!open) return;
    const closeOnPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnPointerDown);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  useLayoutEffect(() => {
    if (!open) {
      setMenuPosition(null);
      return;
    }
    const updatePosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(MENU_WIDTH_PX, window.innerWidth - 16);
      const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
      const top = Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 168));
      const maxHeight = Math.max(160, window.innerHeight - top - 8);
      setMenuPosition((current) => (
        current && current.top === top && current.left === left && current.width === width && current.maxHeight === maxHeight
          ? current
          : { top, left, width, maxHeight }
      ));
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open]);

  useEffect(() => {
    if (open && menuPlaced) {
      activeOptionRef.current?.focus();
    }
  }, [open, menuPlaced]);

  function choose(action: () => void, returnFocus: boolean) {
    setOpen(false);
    action();
    if (returnFocus) {
      triggerRef.current?.focus();
    }
  }

  const menu = open && menuPosition ? (
    <div
      ref={menuRef}
      role="dialog"
      aria-label="窗口布局"
      data-testid="workbench-layout-menu"
      className="workbench-layout-menu desktop-workbench-popover fixed z-[100] overflow-y-auto rounded-md border border-[var(--border)] bg-[var(--workbench-panel-bg)] p-1.5 text-sm text-[var(--text)] shadow-[var(--shadow-card)]"
      style={{ top: menuPosition.top, left: menuPosition.left, width: menuPosition.width, maxHeight: menuPosition.maxHeight }}
    >
      <p className="px-2 pb-1 pt-0.5 text-xs text-[var(--muted)]">布局预设</p>
      <div className="grid gap-0.5">
        {WORKBENCH_LAYOUT_TEMPLATES.map((template) => {
          const active = template.id === activeTemplate;
          const descriptionId = `${idPrefix}-${template.id}`;
          return (
            <button
              key={template.id}
              ref={active ? activeOptionRef : undefined}
              type="button"
              aria-label={template.name}
              aria-describedby={descriptionId}
              aria-pressed={active}
              data-layout-template-option={template.id}
              onClick={() => choose(() => onSelectTemplate(template.id), true)}
              className={clsx(
                "workbench-layout-option flex w-full items-center gap-3 rounded-md border px-2 py-1.5 text-left transition-colors",
                active ? "tcb-soft-selected" : "border-transparent hover:bg-[var(--workbench-hover-bg)]",
              )}
            >
              <LayoutDiagram template={template} slots={getTemplateLayout(layout, template.id).slots} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">{template.name}</span>
                <span id={descriptionId} className="block truncate text-xs text-[var(--muted)]">{template.description}</span>
              </span>
              {active ? <Check className="h-3.5 w-3.5 shrink-0 text-[var(--accent)]" aria-hidden="true" /> : null}
            </button>
          );
        })}
      </div>
      <div className="my-1.5 h-px bg-[var(--border)]" aria-hidden="true" />
      <button
        type="button"
        onClick={() => choose(onStartRearrange, false)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-[var(--workbench-hover-bg)]"
      >
        <ArrowLeftRight className="h-3.5 w-3.5 shrink-0 text-[var(--muted)]" aria-hidden="true" />
        调整窗口位置…
      </button>
      <button
        type="button"
        onClick={() => choose(onResetTemplate, true)}
        className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-[var(--workbench-hover-bg)]"
      >
        <RotateCcw className="h-3.5 w-3.5 shrink-0 text-[var(--muted)]" aria-hidden="true" />
        恢复默认（当前布局）
      </button>
    </div>
  ) : null;

  return (
    <>
      <div className="workbench-segmented inline-flex">
        <button
          ref={setTriggerNode}
          type="button"
          aria-label="窗口布局"
          title="窗口布局"
          aria-haspopup="dialog"
          aria-expanded={open}
          disabled={disabled}
          onClick={() => setOpen((value) => !value)}
          className={clsx(
            "inline-flex h-7 w-7 items-center justify-center transition-colors disabled:opacity-50",
            open ? "tcb-selected-accent" : "text-[var(--muted)] hover:text-[var(--text)]",
          )}
        >
          <LayoutTemplateIcon className="h-4 w-4" />
        </button>
      </div>
      {menu && typeof document !== "undefined" ? createPortal(menu, document.body) : null}
    </>
  );
}
