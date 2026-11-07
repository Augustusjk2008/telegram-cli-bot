import { clsx } from "clsx";
import type { InputHTMLAttributes, ReactNode } from "react";

const focusRing = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--workbench-focus-ring)]";

export const settingsControlClassName = clsx(
  "h-8 w-full min-w-0 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 text-xs text-[var(--text)] outline-none transition-colors",
  "placeholder:text-[var(--muted)] hover:border-[var(--workbench-hover-border)] focus:border-[var(--accent-outline)] focus:ring-2 focus:ring-[var(--workbench-focus-ring)]",
  "disabled:cursor-not-allowed disabled:opacity-60 read-only:bg-[var(--workbench-panel-elevated-bg)]",
);

export const settingsTextareaClassName = clsx(
  "block w-full min-w-0 resize-y rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--bg)] px-2.5 py-1.5 text-xs leading-5 text-[var(--text)] outline-none transition-colors",
  "placeholder:text-[var(--muted)] hover:border-[var(--workbench-hover-border)] focus:border-[var(--accent-outline)] focus:ring-2 focus:ring-[var(--workbench-focus-ring)] disabled:cursor-not-allowed disabled:opacity-60",
);

export const settingsPrimaryButtonClassName = clsx(
  "tcb-solid-accent inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-transparent px-2.5 text-xs font-medium transition-opacity hover:opacity-90 disabled:pointer-events-none disabled:opacity-50",
  focusRing,
);

export const settingsButtonClassName = clsx(
  "inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--workbench-hairline)] bg-[var(--workbench-panel-elevated-bg)] px-2.5 text-xs font-medium text-[var(--text)] transition-colors",
  "hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)] disabled:pointer-events-none disabled:opacity-50",
  focusRing,
);

export const settingsIconButtonClassName = clsx(
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-control)] text-[var(--muted)] transition-colors",
  "hover:bg-[var(--workbench-hover-bg)] hover:text-[var(--text)] disabled:pointer-events-none disabled:opacity-45",
  focusRing,
);

export const settingsDangerIconButtonClassName = clsx(
  "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-control)] text-[var(--muted)] transition-colors",
  "hover:bg-[var(--feedback-error-background-subtle)] hover:text-[var(--feedback-error-text-strong)] disabled:pointer-events-none disabled:opacity-45",
  focusRing,
);

type SettingsSectionProps = {
  id?: string;
  titleId?: string;
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  badge?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  testId?: string;
};

/** Flat, densely spaced settings block; sections stack with hairline separators. */
export function SettingsSection({ id, titleId, icon, title, description, badge, actions, children, className, testId }: SettingsSectionProps) {
  return (
    <section
      id={id}
      data-settings-section={id}
      data-testid={testId}
      aria-labelledby={titleId}
      className={clsx("min-w-0 border-b border-[var(--workbench-hairline)] px-3 py-3 text-xs text-[var(--text)] last:border-b-0", className)}
    >
      <div className="mb-2.5 flex min-w-0 items-start gap-2">
        {icon ? (
          <span aria-hidden="true" className="mt-px inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-[var(--workbench-active-bg)] text-[var(--accent)]">
            {icon}
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="flex min-h-4 min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
            <h2 id={titleId} className="min-w-0 truncate text-[13px] font-semibold leading-5 text-[var(--text)]">{title}</h2>
            {badge}
          </div>
          {description ? <p className="text-[11px] leading-4 text-[var(--muted)]">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

type SettingsFieldProps = {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
};

export function SettingsField({ label, hint, children, className }: SettingsFieldProps) {
  return (
    <label className={clsx("block min-w-0 space-y-1", className)}>
      <span className="block text-[11px] font-medium text-[var(--muted)]">{label}</span>
      {children}
      {hint ? <span className="block text-[11px] leading-4 text-[var(--muted)]">{hint}</span> : null}
    </label>
  );
}

export function SettingsSwitch({ className, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  return <input {...props} type="checkbox" className={clsx("settings-switch", className)} />;
}

export function SettingsDirtyBadge({ children = "未保存" }: { children?: ReactNode }) {
  return (
    <span className="inline-flex h-4 shrink-0 items-center gap-1 rounded-full bg-[var(--status-warning-bg)] px-1.5 text-[10px] font-medium text-[var(--status-warning)]">
      <span aria-hidden="true" className="h-1 w-1 rounded-full bg-current" />
      {children}
    </span>
  );
}

type SettingsNoticeProps = {
  tone: "success" | "danger" | "warning";
  children: ReactNode;
  className?: string;
  role?: string;
};

export function SettingsNotice({ tone, children, className, role }: SettingsNoticeProps) {
  return (
    <div
      role={role}
      className={clsx(
        "break-words rounded-[var(--radius-control)] border px-2.5 py-1.5 text-xs leading-5",
        tone === "success" ? "border-[var(--status-success-border)] bg-[var(--status-success-bg)] text-[var(--status-success)]" : "",
        tone === "danger" ? "border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] text-[var(--status-danger)]" : "",
        tone === "warning" ? "border-[var(--status-warning-border)] bg-[var(--status-warning-bg)] text-[var(--status-warning)]" : "",
        className,
      )}
    >
      {children}
    </div>
  );
}
