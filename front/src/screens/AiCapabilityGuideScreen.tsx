import { clsx } from "clsx";
import {
  BookOpenCheck,
  ClipboardList,
  ExternalLink,
  GitPullRequest,
  Network,
  ShieldCheck,
  Sparkles,
  Workflow,
  Wrench,
} from "lucide-react";
import {
  aiCapabilityGuideUpdatedAt,
  guideAcceptanceLoop,
  guideCapabilities,
  guideClusterRoles,
  guideCollaborationFlow,
  guidePathSteps,
  guidePromptTemplates,
  guideQuickEntries,
  guideReferences,
  guideTools,
  guideWelcomeLead,
  guideWelcomeSummary,
  guideWelcomeTitle,
  type GuideTone,
} from "../content/aiCapabilityGuide";

type Props = {
  embedded?: boolean;
};

const navItems = [
  { id: "path", label: "新手路径" },
  { id: "toolbox", label: "工具箱" },
  { id: "cluster", label: "多 agent" },
  { id: "acceptance", label: "验收" },
  { id: "templates", label: "模板" },
  { id: "references", label: "来源" },
];

const toneClass: Record<GuideTone, { card: string; icon: string; badge: string; line: string; panel: string }> = {
  blue: {
    card: "border-sky-200 bg-sky-50 text-sky-950 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-100",
    icon: "bg-sky-500 text-white",
    badge: "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200",
    line: "bg-sky-400",
    panel: "bg-sky-500/10",
  },
  green: {
    card: "border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-100",
    icon: "bg-emerald-500 text-white",
    badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200",
    line: "bg-emerald-400",
    panel: "bg-emerald-500/10",
  },
  orange: {
    card: "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100",
    icon: "bg-amber-500 text-white",
    badge: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200",
    line: "bg-amber-400",
    panel: "bg-amber-500/10",
  },
  cyan: {
    card: "border-cyan-200 bg-cyan-50 text-cyan-950 dark:border-cyan-900/60 dark:bg-cyan-950/30 dark:text-cyan-100",
    icon: "bg-cyan-500 text-white",
    badge: "bg-cyan-100 text-cyan-800 dark:bg-cyan-500/15 dark:text-cyan-200",
    line: "bg-cyan-400",
    panel: "bg-cyan-500/10",
  },
  violet: {
    card: "border-violet-200 bg-violet-50 text-violet-950 dark:border-violet-900/60 dark:bg-violet-950/30 dark:text-violet-100",
    icon: "bg-violet-500 text-white",
    badge: "bg-violet-100 text-violet-800 dark:bg-violet-500/15 dark:text-violet-200",
    line: "bg-violet-400",
    panel: "bg-violet-500/10",
  },
};

function sectionClass(extra = "") {
  return clsx("scroll-mt-5 border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm", extra);
}

function sectionHeading(title: string, subtitle: string, icon: typeof Workflow) {
  const Icon = icon;
  return (
    <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <div className="mb-2 inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] bg-[var(--surface-strong)] text-[var(--accent)]">
          <Icon className="h-4 w-4" />
        </div>
        <h2 className="text-lg font-semibold tracking-normal text-[var(--text)]">{title}</h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-[var(--muted)]">{subtitle}</p>
      </div>
    </div>
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
        <header className="overflow-hidden border border-[var(--border)] bg-[var(--surface-strong)]">
          <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_25rem] lg:p-5">
            <div className="min-w-0">
              <div className="mb-3 inline-flex items-center gap-2 rounded border border-[var(--border)] bg-[var(--accent-soft)] px-2 py-1 text-xs text-[var(--muted)]">
                <Sparkles className="h-3.5 w-3.5 text-[var(--accent)]" />
                <span>更新：{aiCapabilityGuideUpdatedAt}</span>
              </div>
              <h1 className="max-w-4xl text-2xl font-semibold tracking-normal text-[var(--text)] sm:text-3xl">
                {guideWelcomeTitle}
              </h1>
              <p className="mt-3 max-w-4xl text-sm leading-6 text-[var(--muted)] sm:text-base">
                {guideWelcomeLead}
              </p>
              <p className="mt-2 max-w-4xl text-sm leading-6 text-[var(--muted)]">
                {guideWelcomeSummary}
              </p>
            </div>
            <div className="grid min-w-0 grid-cols-2 gap-2">
              {guideQuickEntries.map(({ id, label, description, icon: Icon, tone }) => (
                <a
                  key={id}
                  href={`#${id}`}
                  className={clsx("min-w-0 border p-3 transition hover:-translate-y-0.5 hover:shadow-md", toneClass[tone].card)}
                >
                  <div className={clsx("mb-2 inline-flex h-8 w-8 items-center justify-center rounded", toneClass[tone].icon)}>
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="text-sm font-semibold">{label}</div>
                  <div className="mt-1 text-xs leading-5 opacity-80">{description}</div>
                </a>
              ))}
            </div>
          </div>
          <div className="border-t border-[var(--border)] px-4 py-2 lg:px-5">
            <nav aria-label="AI 使用指南目录" className="flex gap-2 overflow-x-auto">
              {navItems.map((item) => (
                <a
                  key={item.id}
                  href={`#${item.id}`}
                  className="shrink-0 rounded border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-xs text-[var(--muted)] hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)]"
                >
                  {item.label}
                </a>
              ))}
            </nav>
          </div>
        </header>

        <div className="mt-4 space-y-4">
          <section id="path" className={sectionClass()}>
            {sectionHeading("新手路径：一次正确协作流程", "按这 5 步给任务，智能体会先拿事实，再执行，再交出可验收证据。", Workflow)}
            <div className="mt-4 grid gap-2 md:grid-cols-3 xl:grid-cols-6">
              {guideCollaborationFlow.map(({ label, icon: Icon, tone }, index) => (
                <div key={label} className="flex min-w-0 items-center gap-2">
                  <div className={clsx("min-w-0 flex-1 border p-3", toneClass[tone].card)}>
                    <div className={clsx("mb-2 inline-flex h-7 w-7 items-center justify-center rounded", toneClass[tone].icon)}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="text-sm font-semibold">{label}</div>
                  </div>
                  {index < guideCollaborationFlow.length - 1 ? (
                    <span className="hidden h-px w-4 bg-[var(--border)] xl:block" aria-hidden="true" />
                  ) : null}
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-3 xl:grid-cols-5">
              {guidePathSteps.map((step, index) => {
                const Icon = step.icon;
                return (
                  <article key={step.title} className={clsx("min-w-0 border p-3", toneClass[step.tone].card)}>
                    <div className="flex items-start gap-2">
                      <div className={clsx("inline-flex h-8 w-8 shrink-0 items-center justify-center rounded", toneClass[step.tone].icon)}>
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-xs font-medium opacity-70">0{index + 1}</div>
                        <h3 className="mt-0.5 text-sm font-semibold leading-5">{step.title}</h3>
                      </div>
                    </div>
                    <p className="mt-3 text-xs leading-5 opacity-85">{step.text}</p>
                    <dl className="mt-3 space-y-2 text-xs leading-5">
                      <div className="border-t border-current/10 pt-2">
                        <dt className="font-semibold">你可以这样说</dt>
                        <dd className="mt-1 opacity-85">{step.say}</dd>
                      </div>
                      <div>
                        <dt className="font-semibold">智能体会怎么做</dt>
                        <dd className="mt-1 opacity-85">{step.agent}</dd>
                      </div>
                      <div>
                        <dt className="font-semibold">最后怎么验收</dt>
                        <dd className="mt-1 opacity-85">{step.accept}</dd>
                      </div>
                    </dl>
                  </article>
                );
              })}
            </div>
          </section>

          <section id="toolbox" className={sectionClass()}>
            {sectionHeading("工具箱：让事实进入对话", "文件、终端、Git、插件、集群都不是装饰，它们负责把猜测变成可检查证据。", Wrench)}
            <div className="mt-4 grid gap-3 lg:grid-cols-[1.1fr_0.9fr]">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {guideCapabilities.map(({ title, text, icon: Icon, tone }) => (
                  <article key={title} className={clsx("border p-3", toneClass[tone].card)}>
                    <div className={clsx("mb-3 inline-flex h-8 w-8 items-center justify-center rounded", toneClass[tone].icon)}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <h3 className="text-sm font-semibold">{title}</h3>
                    <p className="mt-1 text-xs leading-5 opacity-85">{text}</p>
                  </article>
                ))}
              </div>
              <div className="border border-[var(--border)] bg-[var(--surface-strong)] p-3">
                <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-[var(--text)]">
                  <Workflow className="h-4 w-4 text-[var(--accent)]" />
                  工作台事实流
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {guideTools.map(({ title, text, icon: Icon, tone }) => (
                    <div key={title} className={clsx("flex min-w-0 items-start gap-2 rounded border border-transparent p-2", toneClass[tone].panel)}>
                      <span className={clsx("inline-flex h-7 w-7 shrink-0 items-center justify-center rounded", toneClass[tone].icon)}>
                        <Icon className="h-4 w-4" />
                      </span>
                      <span className="min-w-0">
                        <span className="block text-xs font-semibold text-[var(--text)]">{title}</span>
                        <span className="mt-0.5 block text-xs leading-5 text-[var(--muted)]">{text}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section id="cluster" className={sectionClass()}>
            {sectionHeading("集群多 agent：把复杂任务拆开", "主 agent 负责方向和合并，子 agent 并行拿事实、执行指定小块、复核风险。", Network)}
            <div className="mt-4 grid gap-3 lg:grid-cols-[18rem_minmax(0,1fr)]">
              <div className="border border-violet-200 bg-violet-50 p-4 text-violet-950 dark:border-violet-900/60 dark:bg-violet-950/30 dark:text-violet-100">
                <div className="mx-auto flex h-24 w-24 items-center justify-center rounded-full border border-violet-300 bg-white/70 text-center text-sm font-semibold dark:border-violet-700 dark:bg-white/10">
                  主 agent
                </div>
                <div className="mt-4 grid gap-2">
                  {guideClusterRoles.slice(1).map((role) => (
                    <div key={role.role} className={clsx("border p-2 text-xs", toneClass[role.tone].card)}>
                      <div className="font-semibold">{role.role}</div>
                      <div className="mt-1 opacity-80">{role.task}</div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {guideClusterRoles.map((role) => (
                  <article key={role.role} className={clsx("border p-3", toneClass[role.tone].card)}>
                    <div className={clsx("mb-3 h-1 w-12 rounded", toneClass[role.tone].line)} />
                    <h3 className="text-sm font-semibold">{role.role}</h3>
                    <p className="mt-2 text-xs leading-5 opacity-85">{role.task}</p>
                  </article>
                ))}
              </div>
            </div>
          </section>

          <section id="acceptance" className={sectionClass()}>
            {sectionHeading("验收闭环：不要只听完成", "让智能体用测试、构建、diff、reviewer 结论交付，保留失败和剩余风险。", ShieldCheck)}
            <div className="mt-4 grid gap-3 md:grid-cols-5">
              {guideAcceptanceLoop.map(({ label, text, icon: Icon, tone }, index) => (
                <div key={label} className="flex min-w-0 items-stretch gap-2">
                  <article className={clsx("min-w-0 flex-1 border p-3", toneClass[tone].card)}>
                    <div className={clsx("mb-2 inline-flex h-8 w-8 items-center justify-center rounded", toneClass[tone].icon)}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <h3 className="text-sm font-semibold">{label}</h3>
                    <p className="mt-1 text-xs leading-5 opacity-85">{text}</p>
                  </article>
                  {index < guideAcceptanceLoop.length - 1 ? (
                    <span className="hidden w-px bg-[var(--border)] md:block" aria-hidden="true" />
                  ) : null}
                </div>
              ))}
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-3">
              <div className="border border-emerald-200 bg-emerald-50 p-3 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-100">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <BookOpenCheck className="h-4 w-4" />
                  可接受
                </div>
                <p className="mt-2 text-xs leading-5 opacity-85">列出已跑命令、实际输出、diff 摘要和剩余风险。</p>
              </div>
              <div className="border border-amber-200 bg-amber-50 p-3 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <GitPullRequest className="h-4 w-4" />
                  需复核
                </div>
                <p className="mt-2 text-xs leading-5 opacity-85">有跳过测试、依赖环境或高风险 diff 时，明确标注。</p>
              </div>
              <div className="border border-sky-200 bg-sky-50 p-3 text-sky-950 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-100">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <ClipboardList className="h-4 w-4" />
                  交付格式
                </div>
                <p className="mt-2 text-xs leading-5 opacity-85">用“改了什么、验证了什么、还有什么风险”收尾。</p>
              </div>
            </div>
          </section>

          <section id="templates" className={sectionClass()}>
            {sectionHeading("可复制 prompt 模板", "复制后替换尖括号内容，就能给智能体清晰任务。", ClipboardList)}
            <div className="mt-4 grid gap-3 xl:grid-cols-2">
              {guidePromptTemplates.map((template) => (
                <article key={template.title} className={clsx("border p-3", toneClass[template.tone].card)}>
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold">{template.title}</h3>
                      <p className="mt-1 text-xs opacity-80">{template.purpose}</p>
                    </div>
                    <ClipboardList className="h-4 w-4 shrink-0 opacity-80" />
                  </div>
                  <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded border border-current/15 bg-white/60 p-3 text-xs leading-5 text-current dark:bg-black/15">
                    {template.prompt}
                  </pre>
                </article>
              ))}
            </div>
          </section>

          <section id="references" className={sectionClass()}>
            {sectionHeading("参考来源", `更新时间：${aiCapabilityGuideUpdatedAt}`, BookOpenCheck)}
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              {guideReferences.map((reference) => (
                <a
                  key={reference.url}
                  href={reference.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex min-w-0 items-center justify-between gap-3 border border-[var(--border)] bg-[var(--surface-strong)] p-3 text-sm text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]"
                >
                  <span className="min-w-0 break-words">{reference.title}</span>
                  <ExternalLink className="h-4 w-4 shrink-0 text-[var(--accent)]" />
                </a>
              ))}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
