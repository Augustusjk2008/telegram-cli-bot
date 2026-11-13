import { useLayoutEffect, useRef, type ReactNode, type Ref, type RefObject } from "react";

// Vertical scroll distance that stands for one column. It only has to be larger than the
// chat's stick-to-bottom tolerance, so that one column before the end is not "at the bottom".
const SCROLL_STEP_PX = 160;
// A mouse wheel notch moves one column. Touchpads send many small deltas instead, which add up.
const WHEEL_NOTCH_MIN_PX = 50;
const TOUCHPAD_STEP_PX = 200;
const WHEEL_IDLE_RESET_MS = 250;
const EXTERNAL_SCROLL_SETTLE_MS = 150;
const COLUMN_SLIDE_MS = 180;

type Props = {
  scrollContainerRef: RefObject<HTMLElement | null>;
  contentRef?: Ref<HTMLDivElement>;
  before?: ReactNode;
  after?: ReactNode;
  children: ReactNode;
};

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === "function") {
    ref(value);
  } else if (ref) {
    (ref as { current: T | null }).current = value;
  }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

/**
 * Lays the transcript out as screen-height columns and shows two neighbours at a time, so
 * the bottom of the left column continues at the top of the right one. The chat's scroll
 * container keeps scrolling vertically: its position selects which pair of columns is shown.
 */
export function ChatSplitColumns({ scrollContainerRef, contentRef, before, after, children }: Props) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const pagerRef = useRef<HTMLDivElement | null>(null);
  const flowRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const scroller = scrollContainerRef.current;
    const track = trackRef.current;
    const pager = pagerRef.current;
    const flow = flowRef.current;
    if (!scroller || !track || !pager || !flow) {
      return;
    }

    let columnCount = 2;
    let firstRow = flow.firstElementChild;
    let measureFrame: number | null = null;
    let settleTimer: number | null = null;
    let wheelDistance = 0;
    let lastWheelAt = 0;
    let shownColumn = 0;
    let pointerInside = false;
    let slide: Animation | null = null;

    const columnGap = () => Number.parseFloat(window.getComputedStyle(flow).columnGap) || 0;
    const columnPitch = () => (pager.clientWidth + columnGap()) / 2;
    const lastLeftColumn = () => Math.max(0, columnCount - 2);
    const leftColumn = () => clamp(Math.round(scroller.scrollTop / SCROLL_STEP_PX), 0, lastLeftColumn());
    const prefersReducedMotion = () => (
      typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );

    // The pager jumps straight to its column; a neighbouring column slides in on top of that,
    // so the pager's own scroll position is never mid-way.
    const showColumns = (animate: boolean) => {
      const column = leftColumn();
      const pitch = columnPitch();
      const distance = column - shownColumn;
      shownColumn = column;
      pager.scrollLeft = column * pitch;
      slide?.cancel();
      slide = null;
      if (animate && Math.abs(distance) === 1 && !prefersReducedMotion() && typeof flow.animate === "function") {
        slide = flow.animate(
          [{ transform: `translateX(${distance * pitch}px)` }, { transform: "translateX(0)" }],
          { duration: COLUMN_SLIDE_MS, easing: "ease-out" },
        );
      }
    };

    const measure = () => {
      measureFrame = null;
      const scrollerStyle = window.getComputedStyle(scroller);
      const paddingTop = Number.parseFloat(scrollerStyle.paddingTop) || 0;
      const paddingBottom = Number.parseFloat(scrollerStyle.paddingBottom) || 0;
      const viewportHeight = Math.max(0, scroller.clientHeight - paddingTop - paddingBottom);
      track.style.setProperty("--chat-split-top", `${paddingTop}px`);
      track.style.setProperty("--chat-split-viewport-height", `${viewportHeight}px`);
      track.style.setProperty("--chat-split-column-height", `${pager.clientHeight}px`);

      const pitch = columnPitch();
      const previousLeftColumn = leftColumn();
      columnCount = pitch > 0 ? Math.max(2, Math.round((pager.scrollWidth + columnGap()) / pitch)) : 2;
      track.style.height = `${viewportHeight + lastLeftColumn() * SCROLL_STEP_PX}px`;

      // Older turns were added in front: keep showing what was on screen before.
      const nextFirstRow = flow.firstElementChild;
      if (firstRow && nextFirstRow !== firstRow && firstRow.isConnected && pitch > 0) {
        const anchor = firstRow.getClientRects()[0];
        if (anchor) {
          const anchorColumn = Math.round((anchor.left - flow.getBoundingClientRect().left) / pitch);
          scroller.scrollTop = clamp(anchorColumn + previousLeftColumn, 0, lastLeftColumn()) * SCROLL_STEP_PX;
        }
      }
      firstRow = nextFirstRow;
      showColumns(false);
    };

    const scheduleMeasure = () => {
      if (measureFrame === null) {
        measureFrame = window.requestAnimationFrame(measure);
      }
    };

    const step = (columns: number) => {
      scroller.scrollTop = clamp(leftColumn() + columns, 0, lastLeftColumn()) * SCROLL_STEP_PX;
      showColumns(true);
    };

    const nestedScrollerConsumes = (target: EventTarget | null, deltaY: number) => {
      let element = target instanceof Element ? target : null;
      while (element && element !== pager) {
        if (element.scrollHeight > element.clientHeight + 1) {
          const overflowY = window.getComputedStyle(element).overflowY;
          if (overflowY === "auto" || overflowY === "scroll") {
            const canScroll = deltaY < 0
              ? element.scrollTop > 0
              : element.scrollTop + element.clientHeight < element.scrollHeight - 1;
            if (canScroll) {
              return true;
            }
          }
        }
        element = element.parentElement;
      }
      return false;
    };

    const handleWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey || !event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
        return;
      }
      if (nestedScrollerConsumes(event.target, event.deltaY)) {
        return;
      }
      event.preventDefault();
      const now = performance.now();
      if (now - lastWheelAt > WHEEL_IDLE_RESET_MS) {
        wheelDistance = 0;
      }
      lastWheelAt = now;
      const unit = event.deltaMode === 1 ? 32 : event.deltaMode === 2 ? scroller.clientHeight : 1;
      const distance = event.deltaY * unit;
      if (Math.abs(distance) >= WHEEL_NOTCH_MIN_PX) {
        wheelDistance = 0;
        step(distance > 0 ? 1 : -1);
        return;
      }
      wheelDistance += distance;
      if (Math.abs(wheelDistance) >= TOUCHPAD_STEP_PX) {
        step(wheelDistance > 0 ? 1 : -1);
        wheelDistance = 0;
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) {
        return;
      }
      const target = event.target instanceof Element ? event.target : null;
      // The transcript is not focusable, so keys pressed after clicking it arrive at the body.
      const aimedAtTranscript = target && (scroller.contains(target) || (target === document.body && pointerInside));
      if (!aimedAtTranscript || target.closest("input, textarea, select, [contenteditable='true']")) {
        return;
      }
      let columns = 0;
      if (event.key === "PageDown") columns = 2;
      else if (event.key === "PageUp") columns = -2;
      else if (!event.shiftKey && (event.key === "ArrowDown" || event.key === "ArrowRight")) columns = 1;
      else if (!event.shiftKey && (event.key === "ArrowUp" || event.key === "ArrowLeft")) columns = -1;
      else if (event.key === "Home") columns = -columnCount;
      else if (event.key === "End") columns = columnCount;
      if (!columns) {
        return;
      }
      event.preventDefault();
      step(columns);
    };

    const handleScrollerScroll = () => showColumns(true);
    const handlePointerDown = (event: PointerEvent) => {
      pointerInside = event.target instanceof Node && scroller.contains(event.target);
    };

    // Find-in-page, focus moves and selection drags scroll the pager themselves. Once that
    // settles, adopt the nearest column so the vertical position stays the source of truth.
    const handlePagerScroll = () => {
      if (settleTimer !== null) {
        window.clearTimeout(settleTimer);
      }
      settleTimer = window.setTimeout(() => {
        settleTimer = null;
        const pitch = columnPitch();
        if (pitch <= 0 || Math.abs(pager.scrollLeft - shownColumn * pitch) < 1) {
          return;
        }
        scroller.scrollTop = clamp(Math.round(pager.scrollLeft / pitch), 0, lastLeftColumn()) * SCROLL_STEP_PX;
        showColumns(false);
      }, EXTERNAL_SCROLL_SETTLE_MS);
    };

    measure();
    const resizeObserver = typeof window.ResizeObserver === "function" ? new window.ResizeObserver(scheduleMeasure) : null;
    resizeObserver?.observe(scroller);
    resizeObserver?.observe(pager);
    const mutationObserver = typeof window.MutationObserver === "function" ? new window.MutationObserver(scheduleMeasure) : null;
    mutationObserver?.observe(flow, { attributes: true, characterData: true, childList: true, subtree: true });
    flow.addEventListener("load", scheduleMeasure, true);
    void document.fonts?.ready.then(scheduleMeasure);
    scroller.addEventListener("wheel", handleWheel, { passive: false });
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown, true);
    scroller.addEventListener("scroll", handleScrollerScroll, { passive: true });
    pager.addEventListener("scroll", handlePagerScroll, { passive: true });

    return () => {
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      flow.removeEventListener("load", scheduleMeasure, true);
      scroller.removeEventListener("wheel", handleWheel);
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown, true);
      scroller.removeEventListener("scroll", handleScrollerScroll);
      pager.removeEventListener("scroll", handlePagerScroll);
      if (measureFrame !== null) {
        window.cancelAnimationFrame(measureFrame);
      }
      if (settleTimer !== null) {
        window.clearTimeout(settleTimer);
      }
      slide?.cancel();
    };
  }, [scrollContainerRef]);

  return (
    <div
      ref={(element) => {
        trackRef.current = element;
        assignRef(contentRef, element);
      }}
      data-testid="chat-scroll-content"
      className="chat-split-track"
    >
      <div className="chat-split-viewport">
        {before}
        <div ref={pagerRef} className="chat-split-pager">
          <div ref={flowRef} data-testid="chat-message-column-flow" className="chat-message-column-flow">
            {children}
          </div>
        </div>
        {after}
      </div>
    </div>
  );
}
