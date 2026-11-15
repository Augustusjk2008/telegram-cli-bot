import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from "react";
import { createPortal } from "react-dom";
import { motion, useReducedMotion } from "motion/react";
import { premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import { TutorialCover } from "./TutorialCover";
import { TutorialReader } from "./TutorialReader";
import { TUTORIAL_CHAPTERS, findTutorialChapter } from "./tutorialContent";
import {
  TUTORIAL_COLLAPSE_EASING,
  TUTORIAL_REVEAL_EASING,
  TUTORIAL_TIMING,
  revealClipPath,
  revealRadius,
  type TutorialPoint,
} from "./tutorialMotion";
import { readTutorialProgress, updateTutorialProgress } from "./tutorialProgress";
import "./tutorial.css";

type Props = {
  /** The header logo button: origin of the reveal, and where focus returns on close. */
  originRef: RefObject<HTMLElement | null>;
  onClosed: () => void;
};

type Phase = "opening" | "open" | "closing";
type View = { kind: "cover" } | { kind: "reader"; chapterId: string; stepIndex: number };
type OriginBox = { left: number; top: number; width: number; height: number };

const FALLBACK_ORIGIN: OriginBox = { left: 14, top: 13, width: 24, height: 24 };

function measureOrigin(anchor: HTMLElement | null): OriginBox {
  const logo = anchor?.querySelector<HTMLElement>(".app-logo") ?? anchor;
  const rect = logo?.getBoundingClientRect();
  if (!rect || rect.width <= 0 || rect.height <= 0) {
    return FALLBACK_ORIGIN;
  }
  return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

function originCentre(box: OriginBox): TutorialPoint {
  return { x: Math.round(box.left + box.width / 2), y: Math.round(box.top + box.height / 2) };
}

function viewportRadius(centre: TutorialPoint): number {
  return revealRadius(centre, { width: window.innerWidth, height: window.innerHeight });
}

const canAnimate = (element: Element | null): element is Element => (
  Boolean(element) && typeof (element as Element).animate === "function"
);

/** Full-screen usage tutorial. Default export so the launcher can load it with `React.lazy`. */
export default function TutorialOverlay({ originRef, onClosed }: Props) {
  const reduceMotion = Boolean(useReducedMotion());
  const [phase, setPhase] = useState<Phase>("opening");
  const [view, setView] = useState<View>({ kind: "cover" });
  const [progress, setProgress] = useState(readTutorialProgress);
  const [origin] = useState(() => measureOrigin(originRef.current));
  const [centre, setCentre] = useState(() => originCentre(origin));
  const [radius, setRadius] = useState(() => viewportRadius(originCentre(origin)));
  // The staged cover entrance belongs to the unfold only; later visits to the cover use the short preset.
  const [introCover, setIntroCover] = useState(true);

  const overlayRef = useRef<HTMLDivElement | null>(null);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const edgeRef = useRef<SVGGElement | null>(null);
  const revealAnimationRef = useRef<Animation | null>(null);
  const workbenchRef = useRef<{ root: HTMLElement; wasInert: boolean } | null>(null);
  const onClosedRef = useRef(onClosed);
  onClosedRef.current = onClosed;

  const releaseWorkbench = useCallback(() => {
    const held = workbenchRef.current;
    workbenchRef.current = null;
    if (held && !held.wasInert) {
      held.root.removeAttribute("inert");
    }
  }, []);

  // Opening: block the workbench underneath, take focus and run the reveal before the first paint.
  useLayoutEffect(() => {
    const root = originRef.current?.closest<HTMLElement>(".desktop-workbench-root") ?? null;
    if (root) {
      workbenchRef.current = { root, wasInert: root.hasAttribute("inert") };
      root.setAttribute("inert", "");
    }
    overlayRef.current?.focus({ preventScroll: true });

    const animations: Animation[] = [];
    if (!reduceMotion && canAnimate(surfaceRef.current)) {
      const reveal = surfaceRef.current.animate(
        [{ clipPath: revealClipPath(0, centre) }, { clipPath: revealClipPath(radius, centre) }],
        { duration: TUTORIAL_TIMING.reveal, easing: TUTORIAL_REVEAL_EASING },
      );
      revealAnimationRef.current = reveal;
      animations.push(reveal);
      if (canAnimate(edgeRef.current)) {
        animations.push(edgeRef.current.animate(
          [
            { transform: "scale(0)", opacity: 0.95 },
            { transform: "scale(0.82)", opacity: 0.7, offset: 0.7 },
            { transform: "scale(1)", opacity: 0 },
          ],
          { duration: TUTORIAL_TIMING.reveal, easing: TUTORIAL_REVEAL_EASING },
        ));
      }
    }
    const timer = window.setTimeout(
      () => setPhase((current) => (current === "opening" ? "open" : current)),
      reduceMotion ? TUTORIAL_TIMING.reducedFade : TUTORIAL_TIMING.openTotal,
    );
    return () => {
      window.clearTimeout(timer);
      animations.forEach((animation) => animation.cancel());
      revealAnimationRef.current = null;
      // Also covers the workbench unmounting while the guide is open (for example a switch to the mobile shell).
      releaseWorkbench();
    };
    // Mount-only: the origin is measured once and the launcher never swaps its ref.
  }, []);

  // Closing: collapse back into the logo, then hand the workbench and focus back.
  useEffect(() => {
    if (phase !== "closing") {
      return;
    }
    const animations: Animation[] = [];
    if (!reduceMotion && canAnimate(surfaceRef.current)) {
      const nextCentre = originCentre(measureOrigin(originRef.current));
      const nextRadius = viewportRadius(nextCentre);
      // Closing mid-reveal starts from wherever the circle currently is.
      const reveal = revealAnimationRef.current;
      const revealProgress = reveal && reveal.playState === "running"
        ? reveal.effect?.getComputedTiming().progress ?? 1
        : 1;
      reveal?.cancel();
      revealAnimationRef.current = null;
      setCentre(nextCentre);
      setRadius(nextRadius);
      const timing: KeyframeAnimationOptions = {
        delay: TUTORIAL_TIMING.collapseDelay,
        duration: TUTORIAL_TIMING.collapse,
        easing: TUTORIAL_COLLAPSE_EASING,
        fill: "both",
      };
      animations.push(surfaceRef.current.animate(
        [
          { clipPath: revealClipPath(nextRadius * revealProgress, nextCentre) },
          { clipPath: revealClipPath(0, nextCentre) },
        ],
        timing,
      ));
      if (canAnimate(edgeRef.current)) {
        animations.push(edgeRef.current.animate(
          [
            { transform: `scale(${revealProgress})`, opacity: 0.85 },
            { transform: "scale(0.12)", opacity: 0.85, offset: 0.88 },
            { transform: "scale(0)", opacity: 0 },
          ],
          timing,
        ));
      }
    }
    const timer = window.setTimeout(() => {
      releaseWorkbench();
      originRef.current?.focus({ preventScroll: true });
      onClosedRef.current();
    }, reduceMotion ? TUTORIAL_TIMING.reducedFade : TUTORIAL_TIMING.closeTotal);
    return () => {
      window.clearTimeout(timer);
      animations.forEach((animation) => animation.cancel());
    };
  }, [originRef, phase, reduceMotion, releaseWorkbench]);

  const requestClose = useCallback(() => {
    setPhase("closing");
  }, []);

  const openStep = useCallback((chapterId: string, stepIndex: number) => {
    const chapter = findTutorialChapter(chapterId);
    if (!chapter || chapter.steps.length === 0) {
      return;
    }
    const nextIndex = Math.min(chapter.steps.length - 1, Math.max(0, stepIndex));
    setIntroCover(false);
    setView({ kind: "reader", chapterId: chapter.id, stepIndex: nextIndex });
    // A chapter counts as read once its last step has been shown.
    const { completed } = readTutorialProgress();
    const finished = nextIndex === chapter.steps.length - 1 && !completed.includes(chapter.id);
    setProgress(updateTutorialProgress({
      chapterId: chapter.id,
      stepIndex: nextIndex,
      completed: finished ? [...completed, chapter.id] : completed,
    }));
  }, []);

  const showCover = useCallback(() => {
    setIntroCover(false);
    setView({ kind: "cover" });
  }, []);

  // One capture-phase listener owns the keyboard while the guide is open. Stopping propagation keeps
  // the workbench shortcuts (Ctrl+P, Ctrl+Shift+F) from firing underneath, so nothing in the guide
  // may rely on React key handlers; native Tab and Enter/Space activation are unaffected.
  const keyStateRef = useRef({ view, openStep, requestClose });
  keyStateRef.current = { view, openStep, requestClose };
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      event.stopPropagation();
      const state = keyStateRef.current;
      if (event.key === "Escape") {
        event.preventDefault();
        state.requestClose();
        return;
      }
      if (event.ctrlKey || event.metaKey) {
        // Swallow the workbench's own shortcuts so trying them here does not open the browser's print or find UI.
        const key = event.key.toLowerCase();
        if ((key === "p" && !event.shiftKey) || (key === "f" && event.shiftKey)) {
          event.preventDefault();
        }
        return;
      }
      if (event.altKey || state.view.kind !== "reader") {
        return;
      }
      const direction = event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
      if (direction !== 0) {
        event.preventDefault();
        state.openStep(state.view.chapterId, state.view.stepIndex + direction);
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, []);

  const readerChapter = view.kind === "reader" ? findTutorialChapter(view.chapterId) : undefined;
  const viewMotion = resolveMotionProps(premiumMotion.dialogPanel, reduceMotion);
  const timingStyle = {
    "--tut-scrim-ms": `${TUTORIAL_TIMING.scrim}ms`,
    "--tut-ring-delay": `${TUTORIAL_TIMING.ringDelay}ms`,
    "--tut-ring-ms": `${TUTORIAL_TIMING.ring}ms`,
    "--tut-content-delay": `${TUTORIAL_TIMING.contentDelay}ms`,
    "--tut-card-stagger": `${TUTORIAL_TIMING.cardStagger}ms`,
    "--tut-close-content-ms": `${TUTORIAL_TIMING.closeContent}ms`,
    "--tut-close-total-ms": `${TUTORIAL_TIMING.closeTotal}ms`,
    "--tut-reduced-ms": `${TUTORIAL_TIMING.reducedFade}ms`,
  } as CSSProperties;

  return createPortal(
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label="使用教程"
      tabIndex={-1}
      data-testid="tutorial-overlay"
      data-phase={phase}
      data-motion={reduceMotion ? "reduced" : "full"}
      data-view={view.kind}
      className="tutorial-overlay desktop-workbench-popover fixed inset-0 z-[1100]"
      style={timingStyle}
    >
      <div className="tutorial-scrim" aria-hidden="true" />
      <div ref={surfaceRef} className="tutorial-surface">
        <div className="tutorial-content">
          {readerChapter && view.kind === "reader" ? (
            <motion.div key="reader" className="tutorial-view" {...viewMotion}>
              <TutorialReader
                chapters={TUTORIAL_CHAPTERS}
                chapter={readerChapter}
                stepIndex={view.stepIndex}
                completed={progress.completed}
                onOpenStep={openStep}
                onShowCover={showCover}
                onClose={requestClose}
              />
            </motion.div>
          ) : (
            <motion.div key="cover" className="tutorial-view" {...viewMotion} initial={introCover ? false : viewMotion.initial}>
              <TutorialCover
                chapters={TUTORIAL_CHAPTERS}
                progress={progress}
                introOrigin={introCover && !reduceMotion ? origin : null}
                onOpenStep={openStep}
                onClose={requestClose}
              />
            </motion.div>
          )}
        </div>
      </div>
      <svg className="tutorial-reveal-edge" aria-hidden="true" focusable="false">
        <g ref={edgeRef} style={{ transformOrigin: `${centre.x}px ${centre.y}px` }}>
          <circle className="tutorial-reveal-edge-glow" cx={centre.x} cy={centre.y} r={radius} />
          <circle className="tutorial-reveal-edge-line" cx={centre.x} cy={centre.y} r={radius} />
        </g>
      </svg>
    </div>,
    document.body,
  );
}
