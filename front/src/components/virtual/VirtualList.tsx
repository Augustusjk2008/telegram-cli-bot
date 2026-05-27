import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { clsx } from "clsx";

type Props<T> = {
  items: T[];
  rowHeight: number;
  overscan?: number;
  className?: string;
  dataTestId?: string;
  getKey: (item: T, index: number) => string;
  renderRow: (item: T, index: number) => ReactNode;
};

const FALLBACK_VIEWPORT_HEIGHT = 520;

type VisibleRange = {
  startIndex: number;
  endIndex: number;
};

export function VirtualList<T>({
  items,
  rowHeight,
  overscan = 8,
  className,
  dataTestId,
  getKey,
  renderRow,
}: Props<T>) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [viewportHeight, setViewportHeight] = useState(FALLBACK_VIEWPORT_HEIGHT);
  const scrollTopRef = useRef(0);
  const scrollFrameRef = useRef<number | null>(null);

  const safeRowHeight = Math.max(1, rowHeight);
  const computeVisibleRange = (scrollTop: number, nextViewportHeight: number): VisibleRange => {
    const startIndex = Math.max(0, Math.floor(scrollTop / safeRowHeight) - overscan);
    const visibleCount = Math.ceil(nextViewportHeight / safeRowHeight) + overscan * 2;
    const endIndex = Math.min(items.length, startIndex + visibleCount);
    return { startIndex, endIndex };
  };
  const [visibleRange, setVisibleRange] = useState<VisibleRange>(() => computeVisibleRange(0, FALLBACK_VIEWPORT_HEIGHT));

  useLayoutEffect(() => {
    const element = viewportRef.current;
    if (!element) {
      return;
    }

    const updateHeight = () => {
      const nextHeight = element.getBoundingClientRect().height || element.clientHeight || FALLBACK_VIEWPORT_HEIGHT;
      setViewportHeight(nextHeight);
    };

    updateHeight();
    const ResizeObserverCtor = window.ResizeObserver;
    if (!ResizeObserverCtor) {
      window.addEventListener("resize", updateHeight);
      return () => window.removeEventListener("resize", updateHeight);
    }

    const observer = new ResizeObserverCtor(updateHeight);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setVisibleRange((current) => {
      const next = computeVisibleRange(scrollTopRef.current, viewportHeight);
      return current.startIndex === next.startIndex && current.endIndex === next.endIndex ? current : next;
    });
  }, [items.length, overscan, safeRowHeight, viewportHeight]);

  useEffect(() => () => {
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current);
    }
  }, []);

  const effectiveVisibleRange = useMemo(() => {
    const next = computeVisibleRange(scrollTopRef.current, viewportHeight);
    return visibleRange.startIndex === next.startIndex && visibleRange.endIndex === next.endIndex
      ? visibleRange
      : next;
  }, [items.length, overscan, safeRowHeight, viewportHeight, visibleRange]);

  const visibleItems = useMemo(
    () => items.slice(effectiveVisibleRange.startIndex, effectiveVisibleRange.endIndex),
    [effectiveVisibleRange.endIndex, effectiveVisibleRange.startIndex, items],
  );

  return (
    <div
      ref={viewportRef}
      data-testid={dataTestId}
      className={clsx("min-h-0 overflow-auto", className)}
      onScroll={(event) => {
        scrollTopRef.current = event.currentTarget.scrollTop;
        if (scrollFrameRef.current !== null) {
          return;
        }
        scrollFrameRef.current = window.requestAnimationFrame(() => {
          scrollFrameRef.current = null;
          const next = computeVisibleRange(scrollTopRef.current, viewportHeight);
          setVisibleRange((current) => (
            current.startIndex === next.startIndex && current.endIndex === next.endIndex
              ? current
              : next
          ));
        });
      }}
    >
      <div className="relative" style={{ height: items.length * safeRowHeight }}>
        {visibleItems.map((item, offset) => {
          const index = effectiveVisibleRange.startIndex + offset;
          return (
            <div
              key={getKey(item, index)}
              className="absolute left-0 right-0"
              style={{
                height: safeRowHeight,
                top: index * safeRowHeight,
              }}
            >
              {renderRow(item, index)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
