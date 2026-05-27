import { clsx } from "clsx";
import {
  BookOpenCheck,
  Bot,
  ClipboardCheck,
  Compass,
  FileSearch,
  FileText,
  GitBranch,
  GitPullRequest,
  MessageSquareText,
  Network,
  PanelsTopLeft,
  Route,
  Search,
  ShieldCheck,
  SquareTerminal,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  aiCapabilityGuideUpdatedAt,
  guideChapters,
  guideLead,
  guideRoute,
  guideTitle,
  type GuideChapter,
  type GuideSectionTone,
} from "../content/aiCapabilityGuide";

type Props = {
  embedded?: boolean;
};

const chapterIcon = {
  "model-capability": BookOpenCheck,
  overview: BookOpenCheck,
  chat: MessageSquareText,
  agents: Network,
  workspace: FileSearch,
  "desktop-workbench": PanelsTopLeft,
  terminal: SquareTerminal,
  debug: Search,
  git: GitBranch,
  plugins: Wrench,
  "assistant-ops": ClipboardCheck,
  settings: Wrench,
  "bot-management": Bot,
  "admin-center": ShieldCheck,
  global: Network,
  updates: GitPullRequest,
} satisfies Record<GuideChapter["id"], LucideIcon>;

const toneClass: Record<GuideSectionTone, { marker: string; panel: string; soft: string }> = {
  primary: {
    marker: "bg-[var(--accent)]",
    panel: "border-[var(--border)] bg-[var(--surface)]",
    soft: "bg-[var(--accent-soft)] text-[var(--text)]",
  },
  green: {
    marker: "bg-emerald-500",
    panel: "border-emerald-200/70 bg-emerald-50/60 dark:border-emerald-900/50 dark:bg-emerald-950/20",
    soft: "bg-emerald-500/10 text-[var(--text)]",
  },
  amber: {
    marker: "bg-amber-500",
    panel: "border-amber-200/70 bg-amber-50/60 dark:border-amber-900/50 dark:bg-amber-950/20",
    soft: "bg-amber-500/10 text-[var(--text)]",
  },
  cyan: {
    marker: "bg-cyan-500",
    panel: "border-cyan-200/70 bg-cyan-50/60 dark:border-cyan-900/50 dark:bg-cyan-950/20",
    soft: "bg-cyan-500/10 text-[var(--text)]",
  },
};

function GuideArticle({ chapter, index }: { chapter: GuideChapter; index: number }) {
  const item = chapter.items[index];
  if (!item) return null;

  return (
    <article className="border-l-2 border-[var(--border)] pl-3 sm:pl-4">
      <div className="flex min-w-0 items-start gap-3">
        <span
          className={clsx(
            "mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border border-[var(--border)] text-xs font-semibold",
            toneClass[chapter.tone].soft,
          )}
        >
          {String(index + 1).padStart(2, "0")}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold tracking-normal text-[var(--text)]">{item.title}</h3>
          <div className="mt-3 grid gap-3 text-sm leading-6 lg:grid-cols-2">
            <div className="border border-[var(--border)] bg-[var(--surface-strong)] p-3">
              <div className="text-xs font-semibold text-[var(--muted)]">入口</div>
              <p className="mt-1 text-[var(--text)]">{item.entry}</p>
            </div>
            <div className="border border-[var(--border)] bg-[var(--surface-strong)] p-3">
              <div className="text-xs font-semibold text-[var(--muted)]">适用场景</div>
              <p className="mt-1 text-[var(--text)]">{item.scenario}</p>
            </div>
          </div>
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <div>
              <div className="text-xs font-semibold text-[var(--muted)]">常用操作</div>
              <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-6 text-[var(--text)]">
                {item.actions.map((action) => (
                  <li key={action}>{action}</li>
                ))}
              </ul>
            </div>
            <div>
              <div className="text-xs font-semibold text-[var(--muted)]">注意事项</div>
              <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm leading-6 text-[var(--text)]">
                {item.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}

export function AiCapabilityGuideScreen({ embedded = false }: Props) {
  return (
    <main
      data-testid="ai-capability-guide-screen"
      className={clsx(
        "h-full min-h-0 overflow-y-auto bg-[var(--bg)] text-[var(--text)]",
        embedded && "bg-[var(--surface)]",
      )}
    >
      <div className={clsx("mx-auto w-full max-w-7xl px-4 py-4 sm:px-5 lg:px-6", embedded && "max-w-none px-3 py-3")}>
        <div className="guide-layout grid gap-4 lg:grid-cols-[14rem_minmax(0,1fr)]">
          <aside className="self-start border border-[var(--border)] bg-[var(--surface)] lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
            <div className="border-b border-[var(--border)] px-3 py-2.5">
              <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text)]">
                <Compass className="h-4 w-4 text-[var(--accent)]" />
                目录
              </div>
            </div>
            <nav aria-label="AI 使用指南目录" className="flex gap-1.5 overflow-x-auto p-2 lg:flex-col lg:overflow-visible">
              {guideChapters.map((chapter) => (
                <a
                  key={chapter.id}
                  href={`#${chapter.id}`}
                  className="shrink-0 border border-transparent px-2.5 py-1.5 text-xs leading-5 text-[var(--muted)] hover:border-[var(--border)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"
                >
                  {chapter.title}
                </a>
              ))}
            </nav>
          </aside>

          <article className="min-w-0 space-y-4">
            <header className="border border-[var(--border)] bg-[var(--surface)] p-4 sm:p-5">
              <div className="inline-flex items-center gap-2 border border-[var(--border)] bg-[var(--surface-strong)] px-2 py-1 text-xs text-[var(--muted)]">
                <FileText className="h-3.5 w-3.5 text-[var(--accent)]" />
                <span>更新：{aiCapabilityGuideUpdatedAt}</span>
              </div>
              <h1 className="mt-3 text-2xl font-semibold tracking-normal text-[var(--text)] sm:text-3xl">{guideTitle}</h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--muted)] sm:text-base">{guideLead}</p>
              <div className="mt-4 border border-[var(--border)] bg-[var(--surface-strong)] p-3">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--text)]">
                  <Route className="h-4 w-4 text-[var(--accent)]" />
                  学习路线
                </div>
                <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--muted)]">
                  {guideRoute.map((step, index) => (
                    <span key={step} className="inline-flex items-center gap-2">
                      <span>{step}</span>
                      {index < guideRoute.length - 1 ? <span className="text-[var(--border-strong)]">→</span> : null}
                    </span>
                  ))}
                </div>
              </div>
            </header>

            {guideChapters.map((chapter) => {
              const Icon = chapterIcon[chapter.id];

              return (
                <section
                  key={chapter.id}
                  id={chapter.id}
                  className={clsx("scroll-mt-4 border p-4 sm:p-5", toneClass[chapter.tone].panel)}
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <span className={clsx("mt-1 h-10 w-1 shrink-0", toneClass[chapter.tone].marker)} aria-hidden="true" />
                    <div className="min-w-0 flex-1">
                      <div
                        className={clsx(
                          "mb-3 inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)]",
                          toneClass[chapter.tone].soft,
                        )}
                      >
                        <Icon className="h-4 w-4" />
                      </div>
                      <h2 className="text-xl font-semibold tracking-normal text-[var(--text)]">{chapter.title}</h2>
                      <p className="mt-1 max-w-3xl text-sm leading-6 text-[var(--muted)]">{chapter.description}</p>
                    </div>
                  </div>
                  <div className="mt-5 space-y-5">
                    {chapter.items.map((item, index) => (
                      <GuideArticle key={item.title} chapter={chapter} index={index} />
                    ))}
                  </div>
                </section>
              );
            })}
          </article>
        </div>
      </div>
    </main>
  );
}
