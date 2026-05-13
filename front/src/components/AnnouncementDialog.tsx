import { Fragment, type CSSProperties, type ReactNode } from "react";
import { X } from "lucide-react";
import type { AnnouncementItem } from "../services/types";

type Props = {
  open: boolean;
  items: AnnouncementItem[];
  latestId: string;
  onClose: (latestId: string) => void;
};

const severityClass: Record<string, string> = {
  info: "border-blue-500 bg-blue-500",
  success: "border-emerald-500 bg-emerald-500",
  warning: "border-amber-500 bg-amber-500",
  danger: "border-red-500 bg-red-500",
};

const allowedInlineTags = new Set(["span", "strong", "b", "em", "i", "u", "s", "code", "br"]);
const dangerousTags = new Set(["script", "style", "iframe", "object", "embed", "link", "meta"]);
const stylePropertyMap: Record<string, keyof CSSProperties> = {
  color: "color",
  "background-color": "backgroundColor",
  "font-weight": "fontWeight",
  "font-style": "fontStyle",
  "text-decoration": "textDecoration",
};

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isSafeStyleValue(property: keyof CSSProperties, value: string) {
  const normalized = value.trim();
  const lower = normalized.toLowerCase();
  if (!normalized || /url\s*\(|expression\s*\(|javascript:|data:|@import|behavior\s*:/.test(lower)) {
    return false;
  }
  if (property === "color" || property === "backgroundColor") {
    return /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|hsla?\([\d\s.,%]+\)|[a-z]+|transparent|currentcolor)$/i.test(normalized);
  }
  if (property === "fontWeight") {
    return /^(normal|bold|bolder|lighter|[1-9]00)$/i.test(normalized);
  }
  if (property === "fontStyle") {
    return /^(normal|italic|oblique)$/i.test(normalized);
  }
  if (property === "textDecoration") {
    return /^(none|underline|overline|line-through)(\s+(none|underline|overline|line-through))*$/i.test(normalized);
  }
  return false;
}

function sanitizeStyleAttribute(value: string): CSSProperties {
  const style: CSSProperties = {};
  value.split(";").forEach((declaration) => {
    const separatorIndex = declaration.indexOf(":");
    if (separatorIndex < 0) {
      return;
    }
    const rawProperty = declaration.slice(0, separatorIndex).trim().toLowerCase();
    const rawValue = declaration.slice(separatorIndex + 1).trim();
    const property = stylePropertyMap[rawProperty];
    if (!property || !isSafeStyleValue(property, rawValue)) {
      return;
    }
    (style as Record<string, string>)[property] = rawValue;
  });
  return style;
}

function styleProps(element: Element): { style?: CSSProperties } {
  const style = sanitizeStyleAttribute(element.getAttribute("style") || "");
  return Object.keys(style).length > 0 ? { style } : {};
}

function renderInlineNode(node: ChildNode, key: string): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent || "";
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  const element = node as Element;
  const tag = element.tagName.toLowerCase();
  if (dangerousTags.has(tag)) {
    return null;
  }
  const children = Array.from(element.childNodes).map((child, index) => renderInlineNode(child, `${key}-${index}`));
  if (!allowedInlineTags.has(tag)) {
    return <Fragment key={key}>{children}</Fragment>;
  }
  if (tag === "br") {
    return <br key={key} />;
  }

  const props = styleProps(element);
  if (tag === "strong" || tag === "b") {
    return <strong key={key} {...props}>{children}</strong>;
  }
  if (tag === "em" || tag === "i") {
    return <em key={key} {...props}>{children}</em>;
  }
  if (tag === "u") {
    return <u key={key} {...props}>{children}</u>;
  }
  if (tag === "s") {
    return <s key={key} {...props}>{children}</s>;
  }
  if (tag === "code") {
    return <code key={key} {...props}>{children}</code>;
  }
  return <span key={key} {...props}>{children}</span>;
}

function renderSafeInlineHtml(value: string): ReactNode {
  if (!value || typeof DOMParser === "undefined") {
    return value;
  }
  const document = new DOMParser().parseFromString(`<body>${value}</body>`, "text/html");
  return Array.from(document.body.childNodes).map((node, index) => renderInlineNode(node, `announcement-html-${index}`));
}

export function AnnouncementDialog({ open, items, latestId, onClose }: Props) {
  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/45 p-0 sm:items-center sm:p-4">
      <section
        role="dialog"
        aria-modal="true"
        aria-label="公告"
        className="grid max-h-[88dvh] w-full grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-t-lg border border-[var(--border)] bg-[var(--surface)] shadow-2xl sm:max-h-[80vh] sm:w-[min(720px,calc(100vw-32px))] sm:rounded-lg"
      >
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <div>
            <h2 className="text-base font-semibold text-[var(--text)]">公告</h2>
          </div>
          <button
            type="button"
            aria-label="关闭公告"
            onClick={() => onClose(latestId)}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--text)] hover:bg-[var(--surface-strong)]"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </header>

        <div className="overflow-y-auto px-4 py-4">
          {items.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] p-6 text-center text-sm text-[var(--muted)]">
              暂无公告
            </div>
          ) : (
            <ol className="relative space-y-4 border-l border-[var(--border)] pl-4">
              {items.map((item) => (
                <li key={item.id} className="relative">
                  <span
                    aria-hidden="true"
                    className={`absolute -left-[21px] top-1.5 h-3 w-3 rounded-full border-2 ${severityClass[item.severity] || severityClass.info}`}
                  />
                  <article className="rounded-lg border border-[var(--border)] bg-[var(--surface-strong)] p-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                      <span>{item.publisher}</span>
                      <span>{formatTime(item.publishedAt)}</span>
                      <span className="rounded border border-[var(--border)] px-1.5 py-0.5">{item.category}</span>
                    </div>
                    <h3 className="mt-2 text-sm font-semibold text-[var(--text)]">{renderSafeInlineHtml(item.title)}</h3>
                    <p className="mt-1 text-sm text-[var(--muted)]">{renderSafeInlineHtml(item.summary)}</p>
                    {item.sections.length ? (
                      <div className="mt-3 space-y-3">
                        {item.sections.map((section) => (
                          <section key={`${item.id}-${section.label}`}>
                            <h4 className="text-xs font-semibold text-[var(--text)]">{section.label}</h4>
                            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-[var(--muted)]">
                              {section.items.map((entry) => <li key={entry}>{renderSafeInlineHtml(entry)}</li>)}
                            </ul>
                          </section>
                        ))}
                      </div>
                    ) : null}
                  </article>
                </li>
              ))}
            </ol>
          )}
        </div>

        <footer className="sticky bottom-0 border-t border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <button
            type="button"
            onClick={() => onClose(latestId)}
            className="w-full rounded-lg bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white"
          >
            关闭
          </button>
        </footer>
      </section>
    </div>
  );
}
