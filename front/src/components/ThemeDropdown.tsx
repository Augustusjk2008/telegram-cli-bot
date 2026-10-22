import { clsx } from "clsx";
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Moon, Palette, Sun } from "lucide-react";
import type { UiThemeName } from "../theme";
import { useOptionalAppearance } from "../theme/AppearanceProvider";
import { BUILTIN_THEME, resolveAppearance } from "../theme/resolveAppearance";

type Props = {
  value: UiThemeName;
  onChange: (themeName: UiThemeName) => void;
  className?: string;
  variant?: "default" | "compact";
  menuAlign?: "stretch" | "right";
};

export function ManageThemesButton() {
  const appearance = useOptionalAppearance();
  if (!appearance?.canManage) return null;
  return <button type="button" onClick={appearance.openManager}
    className="inline-flex min-h-8 items-center gap-1.5 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-xs text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]">
    <Palette className="h-4 w-4" />管理主题
  </button>;
}

export function ThemeDropdown({ value, onChange, className, variant = "default", menuAlign = "stretch" }: Props) {
  const context = useOptionalAppearance();
  const themes = context?.library.themes || [BUILTIN_THEME];
  const selected = themes.find((theme) => theme.id === value) || BUILTIN_THEME;
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const compact = variant === "compact";
  const Icon = selected.appearance.colors.scheme === "dark" ? Moon : Sun;

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("pointerdown", onPointer); window.removeEventListener("keydown", onKey); };
  }, [open]);

  return <div className={clsx("space-y-2", className)}>
    <div ref={rootRef} className="relative">
      <button type="button" aria-label="界面主题" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}
        className={clsx("flex w-full items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-glass)] text-left text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]", compact ? "h-8 px-2 text-xs" : "px-3 py-2.5 text-sm")}>
        <Icon className="h-4 w-4 text-[var(--accent)]" /><span className="min-w-0 flex-1 truncate">{selected.name}</span><ChevronDown className="h-4 w-4 text-[var(--muted)]" />
      </button>
      {open && <div role="listbox" aria-label="界面主题选项"
        className={clsx("absolute z-50 mt-2 max-h-[70vh] overflow-y-auto rounded-md border border-[var(--border)] bg-[var(--surface-overlay)] p-1.5 shadow-[var(--shadow-card)]", menuAlign === "right" ? "right-0 w-64 max-w-[calc(100vw-1rem)]" : "left-0 right-0")}>
        {themes.map((theme) => {
          const colors = resolveAppearance(theme).colors;
          return <button key={theme.id} type="button" role="option" aria-selected={theme.id === value}
            onClick={() => { onChange(theme.id); setOpen(false); }}
            className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]">
            <span className="flex h-6 w-12 overflow-hidden rounded border border-[var(--border)]" aria-hidden="true">
              {[colors["surface.base"], colors.accent, colors["accent.strong"]].map((color, index) => <span key={index} className="flex-1" style={{ background: color }} />)}
            </span>
            <span className="min-w-0 flex-1 truncate">{theme.name}</span>{theme.id === value && <Check className="h-4 w-4 text-[var(--accent)]" />}
          </button>;
        })}
      </div>}
    </div>
    {variant === "default" && <ManageThemesButton />}
    {context?.error && <p role="alert" className="text-xs text-[var(--status-danger)]">{context.error}</p>}
  </div>;
}
