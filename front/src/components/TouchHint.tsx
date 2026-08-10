import {
  cloneElement,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

type TriggerProps = {
  "aria-describedby"?: string;
  "aria-controls"?: string;
  "aria-expanded"?: boolean;
};

type Props = {
  content: ReactNode;
  children: ReactElement<TriggerProps>;
  block?: boolean;
};

function hintPosition(anchor: HTMLElement | null): CSSProperties {
  if (!anchor || typeof window === "undefined") {
    return { left: 8, top: 8 };
  }
  const rect = anchor.getBoundingClientRect();
  const viewportWidth = window.innerWidth || 1024;
  const viewportHeight = window.innerHeight || 768;
  const maxWidth = Math.min(352, Math.max(160, viewportWidth - 16));
  const left = Math.min(
    Math.max(8, rect.left),
    Math.max(8, viewportWidth - maxWidth - 8),
  );
  const above = rect.top > viewportHeight / 2;
  if (above) {
    return {
      left,
      bottom: Math.max(8, viewportHeight - rect.top + 8),
    };
  }
  return {
    left,
    top: Math.min(Math.max(8, rect.bottom + 8), Math.max(8, viewportHeight - 120)),
  };
}

export function TouchHint({ content, children, block = false }: Props) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const rootRef = useRef<HTMLSpanElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const hintId = `touch-hint-${useId().replace(/:/g, "")}`;

  const close = useCallback(() => {
    setOpen(false);
    setPinned(false);
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    const closeOnPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (rootRef.current?.contains(target) || panelRef.current?.contains(target)) {
        return;
      }
      close();
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
      }
    };
    const closeOnScroll = (event: Event) => {
      if (panelRef.current?.contains(event.target as Node)) {
        return;
      }
      close();
    };
    window.addEventListener("pointerdown", closeOnPointerDown, true);
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("scroll", closeOnScroll, true);
    window.addEventListener("resize", closeOnScroll);
    return () => {
      window.removeEventListener("pointerdown", closeOnPointerDown, true);
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("scroll", closeOnScroll, true);
      window.removeEventListener("resize", closeOnScroll);
    };
  }, [close, open]);

  const childProps = children.props || {};
  const describedBy = [childProps["aria-describedby"], open ? hintId : ""]
    .filter(Boolean)
    .join(" ") || undefined;
  const trigger = cloneElement(children, {
    "aria-describedby": describedBy,
    "aria-controls": open ? hintId : undefined,
    "aria-expanded": open,
  });

  return (
    <span
      ref={rootRef}
      className={block ? "relative block min-w-0" : "relative inline-flex min-w-0 max-w-full"}
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse" || !event.pointerType) {
          setOpen(true);
        }
      }}
      onPointerLeave={() => {
        if (!pinned) {
          setOpen(false);
        }
      }}
      onFocusCapture={() => setOpen(true)}
      onBlurCapture={(event) => {
        const nextTarget = event.relatedTarget as Node | null;
        if (nextTarget && rootRef.current?.contains(nextTarget)) {
          return;
        }
        close();
      }}
      onClickCapture={() => {
        setPinned((current) => {
          const next = !current;
          setOpen(next);
          return next;
        });
      }}
    >
      {trigger}
      {open && typeof document !== "undefined"
        ? createPortal(
          <div
            ref={panelRef}
            id={hintId}
            role="tooltip"
            className="pointer-events-auto fixed z-[100] max-h-[min(50vh,18rem)] max-w-[min(22rem,calc(100vw-1rem))] overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-[var(--workbench-hairline)] bg-[var(--surface-overlay)] px-2.5 py-2 text-xs leading-relaxed text-[var(--text)] shadow-[var(--shadow-card)]"
            style={hintPosition(rootRef.current)}
          >
            {content}
          </div>,
          document.body,
        )
        : null}
    </span>
  );
}
