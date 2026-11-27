import { PanelLeft } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { DocumentSectionSummary } from "../../services/types";

export function sectionId(section: DocumentSectionSummary | undefined, index: number) {
  return section?.sectionId || section?.id || `section-${index}`;
}

export function DocumentOutline({
  sections, selectedId, onSelect, children,
}: {
  sections: DocumentSectionSummary[];
  selectedId: string;
  onSelect: (id: string) => void;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const navId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const activeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) activeRef.current?.focus({ preventScroll: true });
  }, [open]);

  useEffect(() => {
    const list = listRef.current;
    const item = activeRef.current;
    if (!list?.clientHeight || !item) return;
    if (item.offsetTop < list.scrollTop) list.scrollTop = item.offsetTop;
    else if (item.offsetTop + item.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = item.offsetTop + item.offsetHeight - list.clientHeight;
    }
  }, [selectedId, open]);

  function closeOutline() {
    setOpen(false);
    toggleRef.current?.focus({ preventScroll: true });
  }

  return (
    <div className="@container flex h-full min-h-0 min-w-0 flex-col" onKeyDown={(event) => {
      if (open && event.key === "Escape" && toggleRef.current?.offsetWidth) {
        event.stopPropagation();
        closeOutline();
      }
    }}>
      <button type="button" ref={toggleRef} aria-expanded={open} aria-controls={navId}
        onClick={() => setOpen(!open)}
        className="mx-3 my-1 inline-flex shrink-0 items-center gap-2 self-start rounded px-2 py-1.5 text-sm text-[var(--text)] hover:bg-[var(--surface-strong)] @xl:hidden">
        <PanelLeft size={16} aria-hidden="true" /> 目录
      </button>
      <div className="relative flex min-h-0 flex-1">
        {open && <button type="button" tabIndex={-1} aria-label="关闭目录" onClick={closeOutline}
          className="absolute inset-0 z-10 bg-black/15 @xl:hidden" />}
        <nav id={navId} aria-label="文档章节" data-testid="document-section-list"
          className={`${open ? "flex" : "hidden"} absolute inset-y-0 left-0 z-20 w-[min(16rem,85%)] flex-col border-r border-[var(--border)] bg-[var(--surface)] @xl:static @xl:flex @xl:w-[clamp(10rem,24%,15rem)] @xl:shrink-0`}>
          <div className="shrink-0 px-4 pb-2 pt-4 text-sm font-semibold text-[var(--text)]">目录</div>
          <div ref={listRef} className="relative min-h-0 flex-1 overflow-y-auto px-2 pb-3">
            {sections.map((section, index) => {
              const id = sectionId(section, index);
              const active = id === selectedId;
              const title = section.title || section.label || `第 ${index + 1} 节`;
              const level = Math.max(1, Math.min(6, section.headingLevel ?? section.level ?? 1));
              return (
                <button key={id} type="button" title={title} aria-current={active ? "location" : undefined}
                  ref={active ? activeRef : undefined}
                  onClick={() => {
                    onSelect(id);
                    if (open) closeOutline();
                  }}
                  style={{ paddingInlineStart: 8 + (level - 1) * 12 }}
                  className={`block w-full rounded-r border-l-2 py-1.5 pr-2 text-left text-sm [overflow-wrap:anywhere] ${active
                    ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                    : "border-transparent text-[var(--muted)] hover:bg-[var(--surface-strong)] hover:text-[var(--text)]"}`}>
                  {title}
                </button>
              );
            })}
          </div>
        </nav>
        {children}
      </div>
    </div>
  );
}
