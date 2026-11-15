import { useLayoutEffect, useRef, type CSSProperties } from "react";
import { clsx } from "clsx";
import { Check, X } from "lucide-react";
import { AppLogo } from "../components/AppLogo";
import { APP_NAME } from "../theme";
import type { TutorialChapter } from "./tutorialContent";
import { TUTORIAL_TIMING, TUTORIAL_TRAVEL_EASING } from "./tutorialMotion";
import type { TutorialProgress } from "./tutorialProgress";

type Props = {
  chapters: TutorialChapter[];
  progress: TutorialProgress;
  /** Rectangle of the header logo while the unfold runs; the hero logo travels from it. Null afterwards. */
  introOrigin: { left: number; top: number; width: number; height: number } | null;
  onOpenStep: (chapterId: string, stepIndex: number) => void;
  onClose: () => void;
};

export function TutorialCover({ chapters, progress, introOrigin, onOpenStep, onClose }: Props) {
  const heroLogoRef = useRef<HTMLSpanElement | null>(null);
  const readable = chapters.filter((chapter) => chapter.steps.length > 0);
  const firstChapter = readable[0];
  const resumeChapter = readable.find((chapter) => chapter.id === progress.chapterId);

  // Manual FLIP: start on top of the header logo, then travel to the hero position while scaling up.
  useLayoutEffect(() => {
    const logo = heroLogoRef.current;
    if (!introOrigin || !logo || typeof logo.animate !== "function") {
      return;
    }
    const target = logo.getBoundingClientRect();
    if (target.width <= 0 || target.height <= 0) {
      return;
    }
    const dx = introOrigin.left + introOrigin.width / 2 - (target.left + target.width / 2);
    const dy = introOrigin.top + introOrigin.height / 2 - (target.top + target.height / 2);
    const scale = introOrigin.width / target.width;
    const animation = logo.animate(
      [{ transform: `translate(${dx}px, ${dy}px) scale(${scale})` }, { transform: "translate(0px, 0px) scale(1)" }],
      {
        delay: TUTORIAL_TIMING.travelDelay,
        duration: TUTORIAL_TIMING.travel,
        easing: TUTORIAL_TRAVEL_EASING,
        fill: "backwards",
      },
    );
    return () => animation.cancel();
    // Runs once for the unfold; the origin does not change afterwards.
  }, []);

  return (
    <div className={clsx("tut-cover", introOrigin && "tut-cover--intro")}>
      <button
        type="button"
        aria-label="关闭教程"
        onClick={onClose}
        className="tut-close tut-intro-item orbit-btn orbit-btn--ghost text-xs"
      >
        <X className="h-4 w-4" aria-hidden="true" />
        <span>关闭教程</span>
        <kbd className="orbit-kbd">Esc</kbd>
      </button>
      <div className="tut-cover-inner">
        <header className="tut-hero">
          <div className="tut-hero-mark" aria-hidden="true">
            <svg className="tut-hero-ring" viewBox="0 0 120 120" focusable="false">
              <circle cx="60" cy="60" r="52" pathLength={1} />
            </svg>
            <span ref={heroLogoRef} className="tut-hero-logo">
              <AppLogo size={64} decorative />
            </span>
          </div>
          <div className="min-w-0">
            <h1 className="tut-hero-title tut-intro-item">{APP_NAME} 使用教程</h1>
            <p className="tut-hero-sub tut-intro-item">从第一次对话到多 Agent 协作，按章节查看各项功能的用法。</p>
            <div className="tut-hero-actions tut-intro-item">
              <button
                type="button"
                disabled={!firstChapter}
                onClick={() => firstChapter && onOpenStep(firstChapter.id, 0)}
                className="orbit-btn orbit-btn--primary text-[13px] font-medium"
              >
                从头开始
              </button>
              {resumeChapter ? (
                <button
                  type="button"
                  onClick={() => onOpenStep(resumeChapter.id, progress.stepIndex)}
                  className="orbit-btn orbit-btn--secondary text-[13px] font-medium"
                >
                  继续上次阅读 · {resumeChapter.title}
                </button>
              ) : null}
            </div>
          </div>
        </header>
        <ol className="tut-chapters" aria-label="教程章节">
          {chapters.map((chapter, index) => {
            const Icon = chapter.icon;
            const pending = chapter.steps.length === 0;
            const done = progress.completed.includes(chapter.id);
            return (
              <li key={chapter.id} className="tut-chapter-slot" style={{ "--tut-i": index } as CSSProperties}>
                <button
                  type="button"
                  disabled={pending}
                  data-chapter={chapter.id}
                  onClick={() => onOpenStep(chapter.id, 0)}
                  className="tut-card text-[13px] font-normal"
                >
                  <span className="tut-card-top">
                    <span className="tut-card-icon"><Icon className="h-4 w-4" aria-hidden="true" /></span>
                    <span className="tut-card-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                  </span>
                  <span className="tut-card-title">{chapter.title}</span>
                  <span className="tut-card-summary">{chapter.summary}</span>
                  <span className="tut-card-meta">
                    <span>{pending ? "编写中" : `${chapter.steps.length} 步`}</span>
                    {done ? (
                      <span className="tut-card-done"><Check className="h-3.5 w-3.5" aria-hidden="true" />已读完</span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
