import { type ReactNode, useLayoutEffect, useRef, useState } from "react";
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
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(FALLBACK_VIEWPORT_HEIGHT);

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

  const safeRowHeight = Math.max(1, rowHeight);
  const startIndex = Math.max(0, Math.floor(scrollTop / safeRowHeight) - overscan);
  const visibleCount = Math.ceil(viewportHeight / safeRowHeight) + overscan * 2;
  const endIndex = Math.min(items.length, startIndex + visibleCount);
  const visibleItems = items.slice(startIndex, endIndex);

  return (
    <div
      ref={viewportRef}
      data-testid={dataTestId}
      className={clsx("min-h-0 overflow-auto", className)}
      onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
    >
      <div className="relative" style={{ height: items.length * safeRowHeight }}>
        {visibleItems.map((item, offset) => {
          const index = startIndex + offset;
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
