import { useLayoutEffect, useMemo, useRef } from "react";

const markerKey = "orbitMobileFilePreview";
const frameBackEvent = "orbit:preview-frame-back";

type Marker = {
  id: number;
  originKey?: string;
};
type BrowserNavigation = {
  currentEntry?: { key: string } | null;
  traverseTo(key: string): { committed: Promise<unknown>; finished: Promise<unknown> };
};
const navigation = () => (window as Window & { navigation?: BrowserNavigation }).navigation;

function currentMarker(): Marker | undefined {
  const value: unknown = window.history.state?.[markerKey];
  if (value && typeof value === "object" && "id" in value && typeof value.id === "number") return value as Marker;
}

// A scope/layout change can unmount and remount the mobile shell before its history traversal commits.
let returning: { resume?: () => void } | null = null;

function returnToOrigin(marker: Marker) {
  if (returning || currentMarker()?.id !== marker.id) return;
  const trip: NonNullable<typeof returning> = {};
  returning = trip;
  let timer: number | undefined;
  const finish = () => {
    if (returning !== trip) return;
    window.removeEventListener("popstate", onPop);
    window.clearTimeout(timer);
    returning = null;
    trip.resume?.();
  };
  const onPop = () => { if (!currentMarker()) finish(); };
  window.addEventListener("popstate", onPop);
  // An opaque sandbox contributes joint history entries. Traversing one of those may produce
  // no parent popstate, especially after the iframe unmounts. Check our own marker before
  // each single step. history.length includes forward entries and can be capped by the browser.
  let remaining = window.history.length;
  const stepBack = () => {
    if (returning !== trip) return;
    if (!currentMarker() || remaining-- <= 0 || document.visibilityState === "hidden") {
      finish();
      return;
    }
    window.history.back();
    timer = window.setTimeout(stepBack, 200);
  };
  const nav = navigation();
  if (marker.originKey && nav) {
    const traversal = nav.traverseTo(marker.originKey);
    void traversal.committed.then(finish, stepBack);
    void traversal.finished.catch(() => undefined);
  } else queueMicrotask(() => {
    // If a new preview opened synchronously, put it above the old entry. Its Back can then
    // close it in a single user gesture, even after nested frame navigation.
    if (trip.resume) finish();
    else stepBack();
  });
}

// Called only after HtmlPreview checks the sending WindowProxy and session ticket.
export function notifyMobilePreviewFrameBack(frame: HTMLIFrameElement) {
  if (frame.closest(".mobile-file-preview:not([inert])")) frame.dispatchEvent(new Event(frameBackEvent, { bubbles: true }));
}

export function useMobilePreviewHistory(onBack: () => void) {
  const callback = useRef(onBack);
  const active = useRef<number | null>(null);
  useLayoutEffect(() => { callback.current = onBack; }, [onBack]);

  useLayoutEffect(() => {
    const onPop = () => {
      if (returning || active.current === null || currentMarker()?.id === active.current) return;
      active.current = null;
      const previous = currentMarker();
      if (previous) returnToOrigin(previous);
      callback.current();
    };
    const onFrameBack = () => {
      const marker = currentMarker();
      if (!marker || marker.id !== active.current || returning) return;
      active.current = null;
      returnToOrigin(marker);
      callback.current();
    };
    window.addEventListener("popstate", onPop);
    window.addEventListener(frameBackEvent, onFrameBack);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener(frameBackEvent, onFrameBack);
    };
  }, []);

  return useMemo(() => ({
    open(id: number) {
      if (active.current === id) return;
      active.current = id;
      const install = () => {
        if (active.current !== id) return;
        const previous = currentMarker();
        // A stale entry reached by Forward, reload or immediate reopen never owns the new
        // viewer. Place a fresh entry above it and keep the original return destination.
        const marker = { id, originKey: previous?.originKey ?? navigation()?.currentEntry?.key };
        window.history.pushState({ ...window.history.state, [markerKey]: marker }, "");
      };
      if (returning) returning.resume = install;
      else install();
    },
    close(id: number) {
      if (active.current !== id) return;
      active.current = null;
      const marker = currentMarker();
      if (marker?.id === id) returnToOrigin(marker);
    },
  }), []);
}
