import { clsx } from "clsx";
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Moon, Sun } from "lucide-react";
import type { UiThemeName } from "../theme";
import { useOptionalAppearance } from "../theme/AppearanceProvider";
import { BUILTIN_THEME, resolveAppearance } from "../theme/resolveAppearance";
import { withPublicBase } from "../utils/publicBase";

type Props = {
  value: UiThemeName;
  onChange: (themeName: UiThemeName) => void;
  className?: string;
  variant?: "default" | "compact";
  menuAlign?: "stretch" | "right";
};

export function ManageThemesButton() {
  return null;
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
      <button type="button" aria-label="界面主题" aria-haspopup="listbox" aria-expanded={open} disabled={context ? !context.canSelect || context.loading : false} onClick={() => setOpen(!open)}
        className={clsx("flex w-full items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-glass)] text-left text-[var(--text)] hover:bg-[var(--workbench-hover-bg)]", compact ? "h-8 px-2 text-xs" : "px-3 py-2.5 text-sm")}>
        <Icon className="h-4 w-4 text-[var(--accent)]" /><span className="min-w-0 flex-1 truncate">{selected.name}</span><ChevronDown className="h-4 w-4 text-[var(--muted)]" />
      </button>
      {open && <div role="listbox" aria-label="界面主题选项"
        className={clsx("theme-dropdown-menu absolute z-50 mt-2 max-h-[70vh] overflow-y-auto p-1.5", menuAlign === "right" ? "right-0 w-72 max-w-[calc(100vw-1rem)]" : "left-0 right-0")}>
        {themes.map((theme) => {
          const resolved = resolveAppearance(theme);
          const colors = resolved.colors;
          const art = resolved.illustrations.opacity > 0 && resolved.illustrations.surfaces.workbench
            ? resolved.illustrations.resources.workbench
            : "";
          const artUrl = art ? (art.startsWith("data:") ? art : withPublicBase(art)) : "";
          return <button key={theme.id} type="button" role="option" aria-label={theme.name} aria-selected={theme.id === value}
            onClick={() => { onChange(theme.id); setOpen(false); }}
            className="theme-dropdown-option flex w-full items-center gap-3 px-2 py-1.5 text-left text-sm text-[var(--text)]">
            <span
              className="theme-dropdown-thumb"
              aria-hidden="true"
              style={{
                backgroundColor: colors.canvas,
                backgroundImage: artUrl
                  ? `url("${artUrl}")`
                  : `linear-gradient(135deg, ${colors.canvas}, ${colors.accent})`,
              }}
            >
              <span className="theme-dropdown-swatches">
                {[colors["surface.base"], colors.accent, colors["light.glow"]].map((color, index) => <span key={index} style={{ background: color }} />)}
              </span>
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{theme.name}</span>
              <span className="block text-[11px] text-[var(--muted)]">{resolved.scheme === "dark" ? "深色" : "浅色"}</span>
            </span>
            {theme.id === value && <Check className="h-4 w-4 shrink-0 text-[var(--accent)]" />}
          </button>;
        })}
      </div>}
    </div>
    {context?.error && <p role="alert" className="text-xs text-[var(--status-danger)]">{context.error}</p>}
  </div>;
}
