import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ForwardedRef,
  type ReactElement,
  type ReactNode,
  type Ref,
  type RefObject,
} from "react";

export type DynamicVirtualListVisibleRange = {
  startIndex: number;
  endIndex: number;
  keys: string[];
};

export type DynamicVirtualListHandle = {
  scrollToKey: (key: string, options?: { align?: "auto" | "start" | "center" | "end" }) => boolean;
  getVisibleRange: () => DynamicVirtualListVisibleRange;
  invalidateMeasurement: (key?: string) => void;
};

export type DynamicVirtualListProps<T> = {
  items: readonly T[];
  getKey: (item: T, index: number) => string;
  renderItem: (item: T, index: number) => ReactNode;
  estimateHeight?: number;
  overscan?: number;
  className?: string;
  style?: CSSProperties;
  dataTestId?: string;
  scrollElementRef?: RefObject<HTMLElement | null>;
  preserveScrollOnPrepend?: boolean;
  stickToBottom?: boolean;
  bottomThreshold?: number;
};

const FALLBACK_VIEWPORT_HEIGHT = 520;

function DynamicVirtualListInner<T>({
  items,
  getKey,
  renderItem,
  estimateHeight = 72,
  overscan = 6,
  className,
  style,
  dataTestId,
  scrollElementRef,
  preserveScrollOnPrepend = false,
  stickToBottom = false,
  bottomThreshold = 96,
}: DynamicVirtualListProps<T>, forwardedRef: ForwardedRef<DynamicVirtualListHandle>) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const heights = useRef(new Map<string, number>());
  const itemObservers = useRef(new Map<string, ResizeObserver>());
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(FALLBACK_VIEWPORT_HEIGHT);
  const [layoutVersion, forceLayout] = useState(0);
  const previousKeysRef = useRef<string[]>([]);
  const scrollFrameRef = useRef<number | null>(null);
  const keys = useMemo(() => items.map(getKey), [getKey, items]);
  const offsets = useMemo(() => {
    let top = 0;
    return items.map((item, index) => {
      const entry = { top, height: heights.current.get(keys[index]) || estimateHeight };
      top += entry.height;
      return entry;
    });
  }, [estimateHeight, items, keys, layoutVersion]);
  const totalHeight = offsets.length ? offsets[offsets.length - 1].top + offsets[offsets.length - 1].height : 0;
  const localScrollTop = Math.max(0, scrollTop);
  const firstVisible = offsets.findIndex((entry) => entry.top + entry.height >= localScrollTop);
  const first = Math.max(0, (firstVisible < 0 ? items.length : firstVisible) - overscan);
  const lastVisible = offsets.findIndex((entry) => entry.top > localScrollTop + viewportHeight);
  const last = Math.min(items.length, (lastVisible < 0 ? items.length : lastVisible + overscan));

  const getScrollElement = useCallback(
    () => scrollElementRef?.current || viewportRef.current,
    [scrollElementRef],
  );

  const updateViewport = useCallback(() => {
    const scrollElement = getScrollElement();
    const listElement = listRef.current;
    if (!scrollElement || !listElement) {
      return;
    }
    const listOffset = scrollElementRef ? listElement.offsetTop : 0;
    setScrollTop(Math.max(0, scrollElement.scrollTop - listOffset));
    setViewportHeight(scrollElement.clientHeight || FALLBACK_VIEWPORT_HEIGHT);
  }, [getScrollElement, scrollElementRef]);

  useImperativeHandle(forwardedRef, () => ({
    scrollToKey: (key, options = {}) => {
      const index = keys.indexOf(key);
      const scrollElement = getScrollElement();
      const listElement = listRef.current;
      const entry = offsets[index];
      if (index < 0 || !scrollElement || !listElement || !entry) {
        return false;
      }
      const listOffset = scrollElementRef ? listElement.offsetTop : 0;
      const itemTop = listOffset + entry.top;
      const itemBottom = itemTop + entry.height;
      const viewportTop = scrollElement.scrollTop;
      const viewportBottom = viewportTop + scrollElement.clientHeight;
      const align = options.align || "auto";
      let nextTop = itemTop;
      if (align === "auto") {
        if (itemTop >= viewportTop && itemBottom <= viewportBottom) {
          return true;
        }
        nextTop = itemTop < viewportTop ? itemTop : itemBottom - scrollElement.clientHeight;
      } else if (align === "center") {
        nextTop = itemTop - (scrollElement.clientHeight - entry.height) / 2;
      } else if (align === "end") {
        nextTop = itemBottom - scrollElement.clientHeight;
      }
      scrollElement.scrollTop = Math.max(0, nextTop);
      updateViewport();
      return true;
    },
    getVisibleRange: () => {
      if (items.length === 0) {
        return { startIndex: -1, endIndex: -1, keys: [] };
      }
      const visibleStart = firstVisible < 0 ? items.length - 1 : firstVisible;
      const visibleEndBoundary = offsets.findIndex((entry) => entry.top >= localScrollTop + viewportHeight);
      const visibleEnd = visibleEndBoundary < 0 ? items.length - 1 : Math.max(visibleStart, visibleEndBoundary - 1);
      return {
        startIndex: visibleStart,
        endIndex: visibleEnd,
        keys: keys.slice(visibleStart, visibleEnd + 1),
      };
    },
    invalidateMeasurement: (key) => {
      if (key) {
        heights.current.delete(key);
      } else {
        heights.current.clear();
      }
      forceLayout((version) => version + 1);
    },
  }), [firstVisible, getScrollElement, items.length, keys, localScrollTop, offsets, scrollElementRef, updateViewport, viewportHeight]);

  useLayoutEffect(() => {
    const element = getScrollElement();
    if (!element) return;
    updateViewport();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateViewport);
    observer?.observe(element);
    return () => observer?.disconnect();
  }, [getScrollElement, updateViewport]);

  useEffect(() => {
    const element = getScrollElement();
    if (!element) {
      return;
    }
    const handleScroll = () => {
      if (scrollFrameRef.current !== null) {
        return;
      }
      scrollFrameRef.current = window.requestAnimationFrame(() => {
        scrollFrameRef.current = null;
        updateViewport();
      });
    };
    element.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      element.removeEventListener("scroll", handleScroll);
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [getScrollElement, updateViewport]);

  useLayoutEffect(() => {
    const previousKeys = previousKeysRef.current;
    previousKeysRef.current = keys;
    if (!preserveScrollOnPrepend || previousKeys.length === 0 || keys.length <= previousKeys.length) {
      return;
    }
    const previousFirstIndex = keys.indexOf(previousKeys[0]);
    const scrollElement = getScrollElement();
    if (previousFirstIndex <= 0 || !scrollElement) {
      return;
    }
    const insertedHeight = keys
      .slice(0, previousFirstIndex)
      .reduce((total, key) => total + (heights.current.get(key) || estimateHeight), 0);
    scrollElement.scrollTop += insertedHeight;
    updateViewport();
  }, [estimateHeight, getScrollElement, keys, preserveScrollOnPrepend, updateViewport]);

  useLayoutEffect(() => () => {
    itemObservers.current.forEach((observer) => observer.disconnect());
    itemObservers.current.clear();
  }, []);

  const measure = useCallback((key: string, index: number, element: HTMLDivElement | null) => {
    itemObservers.current.get(key)?.disconnect();
    itemObservers.current.delete(key);
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      const height = Math.ceil(entry.contentRect.height);
      const previousHeight = heights.current.get(key) || estimateHeight;
      if (height && previousHeight !== height) {
        const scrollElement = getScrollElement();
        const listElement = listRef.current;
        const distanceFromBottom = scrollElement
          ? scrollElement.scrollHeight - scrollElement.scrollTop - scrollElement.clientHeight
          : Number.POSITIVE_INFINITY;
        heights.current.set(key, height);
        const rowTop = (listElement?.offsetTop || 0) + (offsets[index]?.top || 0);
        if (scrollElement && stickToBottom && distanceFromBottom <= bottomThreshold) {
          window.requestAnimationFrame(() => {
            scrollElement.scrollTop = scrollElement.scrollHeight;
            updateViewport();
          });
        } else if (scrollElement && rowTop < scrollElement.scrollTop) {
          scrollElement.scrollTop += height - previousHeight;
          updateViewport();
        }
        forceLayout((version) => version + 1);
      }
    });
    observer.observe(element);
    itemObservers.current.set(key, observer);
  }, [bottomThreshold, estimateHeight, getScrollElement, offsets, stickToBottom, updateViewport]);

  return <div
    ref={scrollElementRef ? listRef : (element) => {
      listRef.current = element;
      viewportRef.current = element;
    }}
    data-testid={dataTestId}
    className={className || (scrollElementRef ? "relative" : "min-h-0 overflow-auto")}
    style={scrollElementRef ? { ...style, height: totalHeight } : style}
  >
    <div className="relative" style={{ height: totalHeight }}>
      {items.slice(first, last).map((item, offset) => {
        const index = first + offset;
        const key = keys[index];
        return <div
          key={key}
          ref={(element) => measure(key, index, element)}
          className="absolute left-0 right-0"
          style={{ top: offsets[index].top }}
        >
          {renderItem(item, index)}
        </div>;
      })}
    </div>
  </div>;
}

export const DynamicVirtualList = forwardRef(DynamicVirtualListInner) as <T>(
  props: DynamicVirtualListProps<T> & { ref?: Ref<DynamicVirtualListHandle> },
) => ReactElement;
