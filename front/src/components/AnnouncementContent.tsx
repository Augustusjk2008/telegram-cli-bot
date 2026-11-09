import { Fragment, type CSSProperties, type ReactNode } from "react";
import type { AnnouncementCategory, AnnouncementItem, AnnouncementSeverity } from "../services/types";

export const ANNOUNCEMENT_CATEGORIES: AnnouncementCategory[] = ["release", "feature", "fix", "maintenance", "notice"];
export const ANNOUNCEMENT_SEVERITIES: AnnouncementSeverity[] = ["info", "success", "warning", "danger"];

export const ANNOUNCEMENT_CATEGORY_LABELS: Record<AnnouncementCategory, string> = {
  release: "版本",
  feature: "功能",
  fix: "修复",
  maintenance: "维护",
  notice: "通知",
};

export const ANNOUNCEMENT_SEVERITY_LABELS: Record<AnnouncementSeverity, string> = {
  info: "信息",
  success: "成功",
  warning: "警告",
  danger: "紧急",
};

const severityClass: Record<string, string> = {
  info: "border-[var(--feedback-information-border)] bg-[var(--feedback-information-background)]",
  success: "border-[var(--feedback-success-border)] bg-[var(--feedback-success-background)]",
  warning: "border-[var(--feedback-warning-border)] bg-[var(--feedback-warning-background)]",
  danger: "border-[var(--feedback-error-border)] bg-[var(--feedback-error-background)]",
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

export function formatAnnouncementTime(value: string) {
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

/** Renders the small whitelist of inline tags announcements allow; everything else becomes text. */
export function renderSafeInlineHtml(value: string): ReactNode {
  if (!value || typeof DOMParser === "undefined") {
    return value;
  }
  const document = new DOMParser().parseFromString(`<body>${value}</body>`, "text/html");
  return Array.from(document.body.childNodes).map((node, index) => renderInlineNode(node, `announcement-html-${index}`));
}

/** The timeline users see in the announcement dialog; the admin preview reuses it verbatim. */
export function AnnouncementTimeline({ items }: { items: AnnouncementItem[] }) {
  return (
    <ol className="relative ml-1.5 space-y-4 border-l border-[var(--hairline-strong)] pl-5">
      {items.map((item) => (
        <li key={item.id} className="relative">
          <span
            aria-hidden="true"
            className={`announcement-dot absolute -left-[27px] top-4 h-3 w-3 rounded-full border-2 ${severityClass[item.severity] || severityClass.info}`}
          />
          <article className="rounded-[var(--radius-card)] bg-[var(--fill-subtle)] p-4 shadow-[inset_0_0_0_1px_var(--hairline)]">
            <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
              <span className="font-medium text-[var(--text)]">{item.publisher}</span>
              <span>{formatAnnouncementTime(item.publishedAt)}</span>
              <span className="orbit-chip" data-tone="accent">{ANNOUNCEMENT_CATEGORY_LABELS[item.category] || item.category}</span>
            </div>
            <h3 className="mt-2 text-sm font-semibold text-[var(--text)]">{renderSafeInlineHtml(item.title)}</h3>
            <p className="mt-1 text-sm text-[var(--muted)]">{renderSafeInlineHtml(item.summary)}</p>
            {item.sections.length ? (
              <div className="mt-3 space-y-3">
                {item.sections.map((section, sectionIndex) => (
                  <section key={`${item.id}-${sectionIndex}`}>
                    <h4 className="text-xs font-semibold text-[var(--text)]">{section.label}</h4>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-[var(--muted)]">
                      {section.items.map((entry, entryIndex) => <li key={entryIndex}>{renderSafeInlineHtml(entry)}</li>)}
                    </ul>
                  </section>
                ))}
              </div>
            ) : null}
          </article>
        </li>
      ))}
    </ol>
  );
}
