import { useLayoutEffect, useRef, type ReactNode, type Ref, type RefObject } from "react";

// Away from the end, a growing transcript only refreshes the scroll range this often.
const RANGE_REFRESH_INTERVAL_MS = 300;
const RANGE_SEARCH_LIMIT = 8;
// Free space tolerated under the last line before the range is tightened. Column breaks leave
// up to a line or two unused, and a range that is still good must not move: any change in the
// scroll height makes a chat that follows new messages jump back to the end.
const RANGE_END_SLACK_PX = 48;

type Props = {
  scrollContainerRef: RefObject<HTMLElement | null>;
  contentRef?: Ref<HTMLDivElement>;
  before?: ReactNode;
  after?: ReactNode;
  children: ReactNode;
};

const rowRevealers = new WeakMap<Element, (row: Element) => boolean>();

/** Scrolls a split chat so the given message row starts at the top of the left column. */
export function revealSplitChatRow(scroller: Element, row: Element) {
  return rowRevealers.get(scroller)?.(row) ?? false;
}

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
 * Shows the transcript as one strip folded into two screen-height columns: the left column
 * starts at the scroll position and the right column continues where the left one ends.
 *
 * The chat's scroll container still scrolls vertically. Its position is applied as a negative
 * offset in front of the transcript, and the browser re-divides the text between the columns,
 * so the left column moves pixel by pixel and whole lines hop over from the right column.
 */
export function ChatSplitColumns({ scrollContainerRef, contentRef, before, after, children }: Props) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const pagerRef = useRef<HTMLDivElement | null>(null);
  const flowRef = useRef<HTMLDivElement | null>(null);
  const stripRef = useRef<HTMLDivElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const scroller = scrollContainerRef.current;
    const track = trackRef.current;
    const pager = pagerRef.current;
    const flow = flowRef.current;
    const strip = stripRef.current;
    const end = endRef.current;
    if (!scroller || !track || !pager || !flow || !strip || !end) {
      return;
    }

    let maxOffset = 0;
    let appliedOffset = 0;
    let firstRow = strip.firstElementChild;
    let measured: { offset: number; end: number; columnHeight: number; pitch: number } | null = null;
    let measureFrame: number | null = null;
    let refreshTimer: number | null = null;
    let lastRefreshAt = 0;

    const columnPitch = () => (pager.clientWidth + (Number.parseFloat(window.getComputedStyle(flow).columnGap) || 0)) / 2;

    const applyOffset = (offset: number) => {
      if (offset !== appliedOffset) {
        strip.style.marginTop = `${-offset}px`;
        appliedOffset = offset;
      }
    };

    // Distance along the strip from the top of the left column to the top of a box.
    const stripPosition = (rect: DOMRect, columnHeight: number, pitch: number) => {
      const origin = flow.getBoundingClientRect();
      return Math.max(0, Math.round((rect.left - origin.left) / pitch)) * columnHeight + (rect.top - origin.top);
    };

    const endPositionAt = (offset: number, columnHeight: number, pitch: number) => {
      applyOffset(offset);
      return stripPosition(end.getBoundingClientRect(), columnHeight, pitch);
    };

    // The largest offset is the one where the transcript ends at the bottom of the right column.
    // Column breaks shift with the offset, so it is found by trying offsets rather than by sum.
    // Starting from the previous answer keeps it unchanged while it still fits.
    const findMaxOffset = (start: number, columnHeight: number, pitch: number) => {
      const visible = columnHeight * 2;
      let offset = Math.max(0, start);
      let endPosition = endPositionAt(offset, columnHeight, pitch);
      let tightened = false;
      for (let attempt = 0; attempt < RANGE_SEARCH_LIMIT; attempt += 1) {
        if (endPosition > visible + 0.5) {
          offset += endPosition - visible;
        } else if (offset > 0 && !tightened && endPosition < visible - RANGE_END_SLACK_PX) {
          offset = Math.max(0, offset - (visible - endPosition));
          tightened = true;
        } else {
          break;
        }
        endPosition = endPositionAt(offset, columnHeight, pitch);
      }
      // Whole pixels keep the scroll height, and with it the sticky column area, off half-pixels.
      return Math.ceil(offset);
    };

    const scheduleMeasure = () => {
      if (measureFrame === null) {
        measureFrame = window.requestAnimationFrame(measure);
      }
    };

    function measure() {
      measureFrame = null;
      const scrollerStyle = window.getComputedStyle(scroller!);
      const paddingTop = Number.parseFloat(scrollerStyle.paddingTop) || 0;
      const paddingBottom = Number.parseFloat(scrollerStyle.paddingBottom) || 0;
      const viewportHeight = Math.max(0, scroller!.clientHeight - paddingTop - paddingBottom);
      track!.style.setProperty("--chat-split-viewport-height", `${viewportHeight}px`);

      const columnHeight = pager!.clientHeight;
      const pitch = columnPitch();
      track!.style.setProperty("--chat-split-column-height", `${columnHeight}px`);
      if (columnHeight <= 0 || pitch <= 0) {
        maxOffset = 0;
        measured = null;
        track!.style.height = `${viewportHeight}px`;
        return;
      }

      const current = clamp(scroller!.scrollTop, 0, maxOffset);
      const endPosition = endPositionAt(current, columnHeight, pitch);
      const nextFirstRow = strip!.firstElementChild;
      const sameGeometry = measured?.columnHeight === columnHeight && measured.pitch === pitch;
      if (sameGeometry && nextFirstRow === firstRow && measured?.offset === current && measured.end === endPosition) {
        return;
      }

      const now = performance.now();
      const nearEnd = current >= maxOffset - columnHeight;
      if (sameGeometry && nextFirstRow === firstRow && !nearEnd && now - lastRefreshAt < RANGE_REFRESH_INTERVAL_MS) {
        if (refreshTimer === null) {
          refreshTimer = window.setTimeout(() => {
            refreshTimer = null;
            scheduleMeasure();
          }, RANGE_REFRESH_INTERVAL_MS);
        }
        return;
      }
      lastRefreshAt = now;

      // Older turns were added in front: keep the previous first row where it was on screen.
      let target: number | null = null;
      if (firstRow && firstRow !== end && nextFirstRow !== firstRow && firstRow.isConnected) {
        const rect = firstRow.getClientRects()[0];
        if (rect) {
          let inserted = current + stripPosition(rect, columnHeight, pitch);
          applyOffset(inserted);
          const settled = firstRow.getClientRects()[0];
          if (settled) {
            inserted += stripPosition(settled, columnHeight, pitch);
          }
          target = inserted + current;
        }
      }
      firstRow = nextFirstRow;

      maxOffset = findMaxOffset(maxOffset + (target === null ? 0 : target - current), columnHeight, pitch);
      track!.style.height = `${viewportHeight + maxOffset}px`;
      if (target !== null) {
        scroller!.scrollTop = Math.min(target, maxOffset);
      }
      const offset = clamp(scroller!.scrollTop, 0, maxOffset);
      measured = { offset, end: endPositionAt(offset, columnHeight, pitch), columnHeight, pitch };
    }

    const handleScroll = () => applyOffset(clamp(scroller.scrollTop, 0, maxOffset));

    // Find-in-page and focus moves scroll the pager itself to reach text in a later column.
    // Turn that into ordinary scrolling so the two visible columns stay the start of the strip.
    const handlePagerScroll = () => {
      if (!pager.scrollLeft && !pager.scrollTop) {
        return;
      }
      const pitch = columnPitch();
      const distance = (pitch > 0 ? (pager.scrollLeft / pitch) * pager.clientHeight : 0) + pager.scrollTop;
      pager.scrollLeft = 0;
      pager.scrollTop = 0;
      scroller.scrollTop += distance;
    };

    const revealRow = (row: Element) => {
      const columnHeight = pager.clientHeight;
      const pitch = columnPitch();
      const rect = row.getClientRects()[0];
      if (!rect || columnHeight <= 0 || pitch <= 0) {
        return false;
      }
      let target = appliedOffset + stripPosition(rect, columnHeight, pitch);
      applyOffset(clamp(target, 0, maxOffset));
      const settled = row.getClientRects()[0];
      if (settled) {
        target = appliedOffset + stripPosition(settled, columnHeight, pitch);
      }
      scroller.scrollTop = clamp(target, 0, maxOffset);
      handleScroll();
      return true;
    };

    measure();
    rowRevealers.set(scroller, revealRow);
    const resizeObserver = typeof window.ResizeObserver === "function" ? new window.ResizeObserver(scheduleMeasure) : null;
    resizeObserver?.observe(scroller);
    resizeObserver?.observe(pager);
    const mutationObserver = typeof window.MutationObserver === "function"
      ? new window.MutationObserver((records) => {
          // The strip's own style only changes when the offset above is applied.
          if (records.some((record) => record.target !== strip || record.type !== "attributes")) {
            scheduleMeasure();
          }
        })
      : null;
    mutationObserver?.observe(strip, { attributes: true, characterData: true, childList: true, subtree: true });
    strip.addEventListener("load", scheduleMeasure, true);
    void document.fonts?.ready.then(scheduleMeasure);
    scroller.addEventListener("scroll", handleScroll, { passive: true });
    pager.addEventListener("scroll", handlePagerScroll, { passive: true });

    return () => {
      rowRevealers.delete(scroller);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      strip.removeEventListener("load", scheduleMeasure, true);
      scroller.removeEventListener("scroll", handleScroll);
      pager.removeEventListener("scroll", handlePagerScroll);
      if (measureFrame !== null) {
        window.cancelAnimationFrame(measureFrame);
      }
      if (refreshTimer !== null) {
        window.clearTimeout(refreshTimer);
      }
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
            <div ref={stripRef}>
              {children}
              <div ref={endRef} aria-hidden="true" />
            </div>
          </div>
        </div>
        {after}
      </div>
    </div>
  );
}
