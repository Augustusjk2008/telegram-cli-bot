import { Fragment } from "react";
import { motion, useReducedMotion } from "motion/react";
import { ArrowLeft, ArrowRight, Check, ChevronRight, LayoutGrid, Lightbulb, X } from "lucide-react";
import { AppLogo } from "../components/AppLogo";
import { premiumMotion, resolveMotionProps } from "../motion/premiumMotion";
import { TutorialStage } from "./TutorialStage";
import { TutorialText } from "./TutorialText";
import { tutorialHotspot, tutorialShotUrl, type TutorialChapter } from "./tutorialContent";

type Props = {
  chapters: TutorialChapter[];
  chapter: TutorialChapter;
  stepIndex: number;
  completed: string[];
  onOpenStep: (chapterId: string, stepIndex: number) => void;
  onShowCover: () => void;
  onClose: () => void;
};

export function TutorialReader({ chapters, chapter, stepIndex, completed, onOpenStep, onShowCover, onClose }: Props) {
  const reduceMotion = useReducedMotion();
  const stepMotion = resolveMotionProps(premiumMotion.detailSwap, reduceMotion);
  const step = chapter.steps[stepIndex];
  const nextStep = chapter.steps[stepIndex + 1];
  const readable = chapters.filter((item) => item.steps.length > 0);
  const position = readable.findIndex((item) => item.id === chapter.id);
  const previousChapter = position > 0 ? readable[position - 1] : undefined;
  const nextChapter = position >= 0 ? readable[position + 1] : undefined;
  const isFirstStep = stepIndex === 0;
  const isLastStep = stepIndex === chapter.steps.length - 1;

  return (
    <div className="tut-reader">
      <header className="tut-reader-bar">
        <AppLogo size={20} decorative />
        <span className="tut-reader-brand">使用教程</span>
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-[var(--muted)]" aria-hidden="true" />
        <h1 className="tut-reader-title">{chapter.title}</h1>
        <span className="tut-reader-count" aria-label={`第 ${stepIndex + 1} 步，共 ${chapter.steps.length} 步`}>
          {stepIndex + 1} / {chapter.steps.length}
        </span>
        <span className="flex-1" />
        <button type="button" onClick={onShowCover} className="orbit-btn orbit-btn--ghost orbit-btn--sm text-xs">
          <LayoutGrid className="h-3.5 w-3.5" aria-hidden="true" />
          返回目录
        </button>
        <button
          type="button"
          aria-label="关闭教程"
          onClick={onClose}
          className="orbit-btn orbit-btn--ghost orbit-btn--sm text-xs"
        >
          <X className="h-3.5 w-3.5" aria-hidden="true" />
          <span>关闭</span>
          <kbd className="orbit-kbd">Esc</kbd>
        </button>
      </header>

      <nav className="tut-rail" aria-label="教程章节">
        <ol>
          {chapters.map((item, index) => {
            const pending = item.steps.length === 0;
            const active = item.id === chapter.id;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  disabled={pending}
                  aria-current={active ? "true" : undefined}
                  onClick={() => onOpenStep(item.id, 0)}
                  className="tut-rail-item text-[13px] font-normal"
                >
                  <span className="tut-rail-number" aria-hidden="true">{String(index).padStart(2, "0")}</span>
                  <span className="min-w-0 flex-1 truncate">{item.title}</span>
                  {pending ? <span className="tut-rail-note">编写中</span> : null}
                  {completed.includes(item.id) ? (
                    <Check className="h-3.5 w-3.5 shrink-0 text-[var(--status-success)]" aria-label="已读完" />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      <TutorialStage
        src={tutorialShotUrl(chapter.id, step.shot)}
        alt={step.alt}
        hotspot={tutorialHotspot(chapter.id, step.shot, step.hotspot)}
        zoom={step.zoom}
        badge={stepIndex + 1}
        caption={{ title: step.title, body: step.body }}
        preloadSrc={nextStep ? tutorialShotUrl(chapter.id, nextStep.shot) : undefined}
      />

      <section className="tut-steps" aria-label={`${chapter.title}的步骤`}>
        <ol className="tut-step-list">
          {chapter.steps.map((item, index) => {
            const active = index === stepIndex;
            return (
              <li key={item.id} className="tut-step" data-active={active ? "true" : "false"}>
                <button
                  type="button"
                  aria-current={active ? "step" : undefined}
                  aria-expanded={active}
                  onClick={() => onOpenStep(chapter.id, index)}
                  className="tut-step-head text-[13.5px] font-medium"
                >
                  <span className="tut-step-number" aria-hidden="true">{index + 1}</span>
                  <span className="min-w-0 flex-1">{item.title}</span>
                </button>
                {active ? (
                  <motion.div className="tut-step-body" {...stepMotion}>
                    {item.body.map((paragraph) => (
                      <p key={paragraph}><TutorialText text={paragraph} /></p>
                    ))}
                    {item.points?.length ? (
                      <ul className="tut-step-points">
                        {item.points.map((point) => (
                          <li key={point}><TutorialText text={point} /></li>
                        ))}
                      </ul>
                    ) : null}
                    {item.keys?.length ? (
                      <p className="tut-step-keys" aria-label={`快捷键 ${item.keys.join(" + ")}`}>
                        {item.keys.map((key, keyIndex) => (
                          <Fragment key={key}>
                            {keyIndex > 0 ? <span aria-hidden="true">+</span> : null}
                            <kbd className="orbit-kbd">{key}</kbd>
                          </Fragment>
                        ))}
                      </p>
                    ) : null}
                    {item.tip ? (
                      <p className="tut-step-tip">
                        <Lightbulb className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                        <span><TutorialText text={item.tip} /></span>
                      </p>
                    ) : null}
                  </motion.div>
                ) : null}
              </li>
            );
          })}
        </ol>
        <div className="tut-steps-nav">
          {isFirstStep ? (
            previousChapter ? (
              <button
                type="button"
                onClick={() => onOpenStep(previousChapter.id, 0)}
                className="orbit-btn orbit-btn--secondary text-[13px] font-medium"
              >
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
                上一章
              </button>
            ) : <span />
          ) : (
            <button
              type="button"
              onClick={() => onOpenStep(chapter.id, stepIndex - 1)}
              className="orbit-btn orbit-btn--secondary text-[13px] font-medium"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              上一步
            </button>
          )}
          {!isLastStep ? (
            <button
              type="button"
              onClick={() => onOpenStep(chapter.id, stepIndex + 1)}
              className="orbit-btn orbit-btn--primary text-[13px] font-medium"
            >
              下一步
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          ) : nextChapter ? (
            <button
              type="button"
              onClick={() => onOpenStep(nextChapter.id, 0)}
              className="orbit-btn orbit-btn--primary min-w-0 text-[13px] font-medium"
            >
              <span className="truncate">下一章：{nextChapter.title}</span>
              <ArrowRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            </button>
          ) : (
            <button type="button" onClick={onShowCover} className="orbit-btn orbit-btn--primary text-[13px] font-medium">
              返回目录
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
