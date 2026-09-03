import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import { Maximize2, Minimize2 } from "lucide-react";

const BUTTON_SIZE_PX = 48;
const EDGE_GUTTER_PX = 8;
const DEFAULT_RIGHT_PX = 16;
const DEFAULT_BOTTOM_PX = 320;
const DRAG_CLICK_THRESHOLD_PX = 4;

type FloatingButtonPosition = {
  x: number;
  y: number;
};

type Props = {
  containerRef: RefObject<HTMLElement | null>;
  isImmersive: boolean;
  storageKey: string;
  onToggle: () => void;
};

function readStoredPosition(storageKey: string): FloatingButtonPosition | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<FloatingButtonPosition>;
    if (Number.isFinite(parsed.x) && Number.isFinite(parsed.y)) {
      return { x: Number(parsed.x), y: Number(parsed.y) };
    }
  } catch {
    // Ignore malformed persisted UI state.
  }
  return null;
}

function writeStoredPosition(storageKey: string, position: FloatingButtonPosition) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(storageKey, JSON.stringify({
      x: Math.round(position.x),
      y: Math.round(position.y),
    }));
  } catch {
    // Ignore storage quota/private mode failures.
  }
}

function clampPosition(position: FloatingButtonPosition, container: HTMLElement | null): FloatingButtonPosition {
  const rect = container?.getBoundingClientRect();
  const viewport = typeof window !== "undefined" ? window.visualViewport : null;
  const fallbackWidth = viewport?.width || (typeof window !== "undefined" ? window.innerWidth : 0);
  const fallbackHeight = viewport?.height || (typeof window !== "undefined" ? window.innerHeight : 0);
  const width = Math.max(BUTTON_SIZE_PX + EDGE_GUTTER_PX * 2, rect?.width || fallbackWidth || 0);
  const height = Math.max(BUTTON_SIZE_PX + EDGE_GUTTER_PX * 2, rect?.height || fallbackHeight || 0);
  const minX = EDGE_GUTTER_PX;
  const minY = EDGE_GUTTER_PX;
  const maxX = Math.max(minX, width - BUTTON_SIZE_PX - EDGE_GUTTER_PX);
  const maxY = Math.max(minY, height - BUTTON_SIZE_PX - EDGE_GUTTER_PX);
  return {
    x: Math.min(maxX, Math.max(minX, position.x)),
    y: Math.min(maxY, Math.max(minY, position.y)),
  };
}

function defaultPosition(container: HTMLElement | null): FloatingButtonPosition {
  const rect = container?.getBoundingClientRect();
  const viewport = typeof window !== "undefined" ? window.visualViewport : null;
  const fallbackWidth = viewport?.width || (typeof window !== "undefined" ? window.innerWidth : 0);
  const fallbackHeight = viewport?.height || (typeof window !== "undefined" ? window.innerHeight : 0);
  const width = rect?.width || fallbackWidth || BUTTON_SIZE_PX + DEFAULT_RIGHT_PX * 2;
  const height = rect?.height || fallbackHeight || BUTTON_SIZE_PX + DEFAULT_BOTTOM_PX * 2;
  return clampPosition({
    x: width - BUTTON_SIZE_PX - DEFAULT_RIGHT_PX,
    y: height - BUTTON_SIZE_PX - DEFAULT_BOTTOM_PX,
  }, container);
}

function readInitialPosition(storageKey: string, container: HTMLElement | null) {
  const storedPosition = readStoredPosition(storageKey);
  const initialDefaultPosition = defaultPosition(container);
  if (!storedPosition) {
    return initialDefaultPosition;
  }
  const clampedPosition = clampPosition(storedPosition, container);
  const storedAtObstructiveBottomRight = (
    clampedPosition.x >= initialDefaultPosition.x - EDGE_GUTTER_PX
    && clampedPosition.y > initialDefaultPosition.y + BUTTON_SIZE_PX
  );
  return storedAtObstructiveBottomRight ? initialDefaultPosition : clampedPosition;
}

export function ImmersiveToggleButton({
  containerRef,
  isImmersive,
  storageKey,
  onToggle,
}: Props) {
  const [position, setPosition] = useState<FloatingButtonPosition | null>(null);
  const dragStateRef = useRef<{
    pointerId: number;
    startClientX: number;
    startClientY: number;
    origin: FloatingButtonPosition;
    hasDragged: boolean;
  } | null>(null);
  const ignoreNextClickRef = useRef(false);
  const ignoreNextClickTimerRef = useRef<number | null>(null);

  useLayoutEffect(() => {
    setPosition((current) => {
      const next = clampPosition(
        current || readInitialPosition(storageKey, containerRef.current),
        containerRef.current,
      );
      if (current && (current.x !== next.x || current.y !== next.y)) {
        writeStoredPosition(storageKey, next);
      }
      return next;
    });
  }, [containerRef, isImmersive, storageKey]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const handleResize = () => {
      setPosition((current) => {
        const next = clampPosition(
          current || readInitialPosition(storageKey, containerRef.current),
          containerRef.current,
        );
        if (!current || current.x !== next.x || current.y !== next.y) {
          writeStoredPosition(storageKey, next);
        }
        return next;
      });
    };
    window.addEventListener("resize", handleResize);
    window.visualViewport?.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      window.visualViewport?.removeEventListener("resize", handleResize);
    };
  }, [containerRef, storageKey]);

  useEffect(() => {
    return () => {
      if (ignoreNextClickTimerRef.current !== null && typeof window !== "undefined") {
        window.clearTimeout(ignoreNextClickTimerRef.current);
      }
    };
  }, []);

  function handlePointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.pointerType === "mouse" && event.button !== 0) {
      return;
    }
    const startPosition = position || readInitialPosition(storageKey, containerRef.current);
    dragStateRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      origin: startPosition,
      hasDragged: false,
    };
    setPosition(startPosition);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }
    const deltaX = event.clientX - dragState.startClientX;
    const deltaY = event.clientY - dragState.startClientY;
    if (!dragState.hasDragged && Math.hypot(deltaX, deltaY) >= DRAG_CLICK_THRESHOLD_PX) {
      dragState.hasDragged = true;
    }
    if (!dragState.hasDragged) {
      return;
    }
    event.preventDefault();
    setPosition(clampPosition({
      x: dragState.origin.x + deltaX,
      y: dragState.origin.y + deltaY,
    }, containerRef.current));
  }

  function stopDragging(event: ReactPointerEvent<HTMLButtonElement>) {
    const dragState = dragStateRef.current;
    if (!dragState || dragState.pointerId !== event.pointerId) {
      return;
    }
    dragStateRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    if (!dragState.hasDragged) {
      return;
    }
    const deltaX = event.clientX - dragState.startClientX;
    const deltaY = event.clientY - dragState.startClientY;
    const nextPosition = clampPosition({
      x: dragState.origin.x + deltaX,
      y: dragState.origin.y + deltaY,
    }, containerRef.current);
    ignoreNextClickRef.current = true;
    if (ignoreNextClickTimerRef.current !== null && typeof window !== "undefined") {
      window.clearTimeout(ignoreNextClickTimerRef.current);
    }
    if (typeof window !== "undefined") {
      ignoreNextClickTimerRef.current = window.setTimeout(() => {
        ignoreNextClickRef.current = false;
        ignoreNextClickTimerRef.current = null;
      }, 0);
    }
    setPosition(nextPosition);
    writeStoredPosition(storageKey, nextPosition);
  }

  function handleClick(event: ReactMouseEvent<HTMLButtonElement>) {
    if (ignoreNextClickRef.current) {
      ignoreNextClickRef.current = false;
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    onToggle();
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={stopDragging}
      onPointerCancel={stopDragging}
      aria-label={isImmersive ? "退出沉浸模式" : "进入沉浸模式"}
      title="拖动调整位置"
      className="absolute left-0 top-0 z-20 inline-flex h-12 w-12 touch-none select-none items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] shadow-[var(--shadow-card)] backdrop-blur transition-colors hover:bg-[var(--surface-strong)] active:cursor-grabbing"
      style={{
        transform: position ? `translate3d(${position.x}px, ${position.y}px, 0)` : undefined,
        visibility: position ? "visible" : "hidden",
      }}
    >
      {isImmersive ? <Minimize2 className="h-5 w-5" /> : <Maximize2 className="h-5 w-5" />}
    </button>
  );
}
