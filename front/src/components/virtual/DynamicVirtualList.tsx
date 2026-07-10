import { useCallback, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";

export type DynamicVirtualListProps<T> = {
  items: readonly T[];
  getKey: (item: T, index: number) => string;
  renderItem: (item: T, index: number) => ReactNode;
  estimateHeight?: number;
  overscan?: number;
  className?: string;
};

export function DynamicVirtualList<T>({ items, getKey, renderItem, estimateHeight = 72, overscan = 6, className }: DynamicVirtualListProps<T>) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const heights = useRef(new Map<string, number>());
  const itemObservers = useRef(new Map<string, ResizeObserver>());
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(520);
  const [, forceLayout] = useState(0);
  const offsets = useMemo(() => {
    let top = 0;
    return items.map((item, index) => {
      const entry = { top, height: heights.current.get(getKey(item, index)) || estimateHeight };
      top += entry.height;
      return entry;
    });
  }, [estimateHeight, getKey, items]);
  const totalHeight = offsets.length ? offsets[offsets.length - 1].top + offsets[offsets.length - 1].height : 0;
  const first = Math.max(0, offsets.findIndex((entry) => entry.top + entry.height >= scrollTop) - overscan);
  const lastVisible = offsets.findIndex((entry) => entry.top > scrollTop + viewportHeight);
  const last = Math.min(items.length, (lastVisible < 0 ? items.length : lastVisible + overscan));

  useLayoutEffect(() => {
    const element = viewportRef.current;
    if (!element) return;
    const update = () => setViewportHeight(element.clientHeight || 520);
    update();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(element);
    return () => observer?.disconnect();
  }, []);

  useLayoutEffect(() => () => {
    itemObservers.current.forEach((observer) => observer.disconnect());
    itemObservers.current.clear();
  }, []);

  const measure = useCallback((key: string, element: HTMLDivElement | null) => {
    itemObservers.current.get(key)?.disconnect();
    itemObservers.current.delete(key);
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const height = Math.ceil(entry.contentRect.height);
      if (height && heights.current.get(key) !== height) {
        heights.current.set(key, height);
        forceLayout((version) => version + 1);
      }
    });
    observer.observe(element);
    itemObservers.current.set(key, observer);
  }, []);

  return <div ref={viewportRef} className={className || "min-h-0 overflow-auto"} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}>
    <div className="relative" style={{ height: totalHeight }}>
      {items.slice(first, last).map((item, offset) => {
        const index = first + offset;
        const key = getKey(item, index);
        return <div key={key} ref={(element) => measure(key, element)} className="absolute left-0 right-0" style={{ top: offsets[index].top }}>{renderItem(item, index)}</div>;
      })}
    </div>
  </div>;
}
