import { clsx } from "clsx";
import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Check,
  ChevronDown,
  Contrast,
  FlaskConical,
  Moon,
  Orbit,
  Sun,
  Terminal,
} from "lucide-react";
import { UI_THEME_OPTIONS, type UiThemeName } from "../theme";

type ThemeOption = (typeof UI_THEME_OPTIONS)[number];
type ThemeIconComponent = typeof Orbit;

const THEME_ICONS: Record<UiThemeName, ThemeIconComponent> = {
  "deep-space": Orbit,
  classic: Sun,
  graphite: Terminal,
  "lab-light": FlaskConical,
  "ink-paper": BookOpen,
  "high-contrast": Contrast,
};

function ThemePreviewSwatches({ option, compact = false }: { option: ThemeOption; compact?: boolean }) {
  return (
    <div
      className={clsx(
        "grid shrink-0 grid-cols-3 overflow-hidden rounded-md border shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]",
        compact ? "h-5 w-10" : "h-8 w-16",
      )}
      style={{
        backgroundColor: option.preview.surface,
        borderColor: option.preview.border,
      }}
      aria-hidden="true"
    >
      <span style={{ backgroundColor: option.preview.surface }} />
      <span style={{ backgroundColor: option.preview.accent }} />
      <span style={{ backgroundColor: option.preview.accentStrong }} />
    </div>
  );
}

type Props = {
  value: UiThemeName;
  onChange: (themeName: UiThemeName) => void;
  className?: string;
  variant?: "default" | "compact";
  menuAlign?: "stretch" | "right";
};

export function ThemeDropdown({
  value,
  onChange,
  className,
  variant = "default",
  menuAlign = "stretch",
}: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selectedOption = UI_THEME_OPTIONS.find((option) => option.value === value) || UI_THEME_OPTIONS[0];
  const SelectedIcon = THEME_ICONS[selectedOption.value] || Moon;
  const compact = variant === "compact";

  useEffect(() => {
    if (!open) {
      return;
    }

    const closeOnPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    window.addEventListener("pointerdown", closeOnPointerDown);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOnPointerDown);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={clsx("relative", className)}>
      <button
        type="button"
        aria-label="界面主题"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className={clsx(
          "flex w-full items-center border border-[var(--border)] bg-[var(--surface-glass)] text-left shadow-sm transition hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)]",
          compact ? "h-8 gap-1.5 rounded-md px-2" : "gap-3 rounded-md px-3 py-2.5",
        )}
      >
        <span
          className={clsx(
            "flex shrink-0 items-center justify-center rounded-md bg-[var(--accent-soft)] text-[var(--accent)]",
            compact ? "h-5 w-5" : "h-9 w-9",
          )}
        >
          <SelectedIcon className={compact ? "h-3.5 w-3.5" : "h-4.5 w-4.5"} />
        </span>
        <span className="min-w-0 flex-1">
          {compact ? null : <span className="block text-xs text-[var(--muted)]">主题</span>}
          <span className={clsx("block truncate font-semibold text-[var(--text)]", compact ? "text-xs" : "mt-0.5 text-sm")}>
            {selectedOption.label}
          </span>
        </span>
        {compact ? null : <ThemePreviewSwatches option={selectedOption} />}
        <ChevronDown className={clsx("h-4 w-4 shrink-0 text-[var(--muted)] transition", open && "rotate-180")} />
      </button>

      {open ? (
        <div
          role="listbox"
          aria-label="界面主题选项"
          className={clsx(
            "absolute z-50 mt-2 max-h-[min(28rem,70vh)] overflow-y-auto rounded-md border border-[var(--workbench-hairline)] bg-[var(--surface-overlay)] p-1.5 shadow-[var(--shadow-card)] backdrop-blur",
            menuAlign === "right" ? "right-0 w-64 max-w-[calc(100vw-1rem)]" : "left-0 right-0",
          )}
        >
          {UI_THEME_OPTIONS.map((option) => {
            const selected = option.value === value;
            const ThemeIcon = THEME_ICONS[option.value] || Moon;
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
                className={clsx(
                  "flex w-full items-center gap-2.5 rounded-md border px-2 py-2 text-left transition",
                  selected
                    ? "border-[var(--accent-outline)] bg-[var(--workbench-active-bg)] text-[var(--text)]"
                    : "border-transparent text-[var(--text)] hover:border-[var(--workbench-hover-border)] hover:bg-[var(--workbench-hover-bg)]",
                )}
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[var(--accent-soft)] text-[var(--accent)]">
                  <ThemeIcon className="h-4.5 w-4.5" />
                </span>
                <ThemePreviewSwatches option={option} compact={compact} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{option.label}</span>
                  <span className="block truncate text-xs text-[var(--muted)]">{option.description}</span>
                </span>
                {selected ? <Check className="h-4 w-4 shrink-0 text-[var(--accent)]" /> : <span className="h-4 w-4 shrink-0" />}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
