import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { isLikelyLocalFileHref, isSafeMarkdownHref } from "../utils/fileLinks";

type Props = {
  content: string;
  onFileLinkClick?: (href: string) => void;
};

type MarkdownContentProps = {
  content: string;
  variant?: "preview" | "chat";
  onFileLinkClick?: (href: string) => void;
};

function safeUrlTransform(url: string) {
  return isSafeMarkdownHref(url) ? url : "";
}

function InlineCode({ className, children, ...props }: ComponentPropsWithoutRef<"code">) {
  const hasLanguageClass = Boolean(className && className.includes("language-"));
  if (hasLanguageClass) {
    return (
      <code
        className="block overflow-x-auto rounded-xl bg-[var(--code-bg)] px-4 py-3 font-mono text-[13px] leading-6 text-[var(--code-text)]"
        {...props}
      >
        {children}
      </code>
    );
  }

  return (
    <code
      className="whitespace-pre-wrap break-all rounded-md bg-[var(--accent-soft)] px-1.5 py-0.5 font-mono text-[0.92em] text-[var(--accent)]"
      {...props}
    >
      {children}
    </code>
  );
}

export function MarkdownContent({ content, variant = "preview", onFileLinkClick }: MarkdownContentProps) {
  const containerClassName = variant === "chat"
    ? "min-w-0 w-full text-[15px] leading-7 text-[var(--text)]"
    : "max-h-[50vh] overflow-auto rounded-xl bg-[var(--surface-strong)] px-5 py-4 text-[15px] leading-7 text-[var(--text)]";

  return (
    <div className={containerClassName}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeUrlTransform}
        components={{
          h1: ({ children }) => <h1 className="mb-4 break-words text-3xl font-semibold tracking-tight [overflow-wrap:anywhere]">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-3 mt-8 break-words text-2xl font-semibold tracking-tight [overflow-wrap:anywhere]">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-3 mt-6 break-words text-xl font-semibold [overflow-wrap:anywhere]">{children}</h3>,
          h4: ({ children }) => <h4 className="mb-2 mt-5 break-words text-lg font-semibold [overflow-wrap:anywhere]">{children}</h4>,
          p: ({ children }) => <p className="my-3 break-words [overflow-wrap:anywhere]">{children}</p>,
          ul: ({ children }) => <ul className="my-4 list-disc space-y-2 pl-6">{children}</ul>,
          ol: ({ children }) => <ol className="my-4 list-decimal space-y-2 pl-6">{children}</ol>,
          li: ({ children }) => <li className="break-words pl-1 [overflow-wrap:anywhere]">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-5 break-words border-l-4 border-[var(--accent-outline)] bg-[var(--accent-soft)] px-4 py-3 text-[var(--muted)] [overflow-wrap:anywhere]">
              {children}
            </blockquote>
          ),
          a: ({ href, children }) => {
            const nextHref = href || "";
            const handleFileLink = Boolean(onFileLinkClick && nextHref && isLikelyLocalFileHref(nextHref));

            return (
              <a
                className="break-all font-medium text-[var(--accent)] underline decoration-[var(--accent-outline)] underline-offset-4"
                href={nextHref || undefined}
                rel={handleFileLink ? undefined : "noreferrer"}
                target={handleFileLink ? undefined : "_blank"}
                onClick={(event) => {
                  if (handleFileLink) {
                    event.preventDefault();
                    onFileLinkClick?.(nextHref);
                  }
                }}
              >
                {children}
              </a>
            );
          },
          pre: ({ children }) => <pre className="my-4 min-w-0 overflow-x-auto">{children}</pre>,
          code: InlineCode,
          table: ({ children }) => (
            <div className="my-5 overflow-x-auto">
              <table className="min-w-full border-collapse overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-[var(--accent-soft)]">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-b border-[var(--border)] last:border-b-0">{children}</tr>,
          th: ({ children }) => <th className="break-words px-3 py-2 text-left text-sm font-semibold [overflow-wrap:anywhere]">{children}</th>,
          td: ({ children }) => <td className="break-words px-3 py-2 align-top text-sm [overflow-wrap:anywhere]">{children}</td>,
          hr: () => <hr className="my-6 border-0 border-t border-[var(--border)]" />,
          img: ({ src, alt }) => (
            <div className="my-4 rounded-xl border border-dashed border-[var(--accent-outline)] bg-[var(--accent-soft)] px-4 py-3 text-sm text-[var(--muted)]">
              <span className="mr-2 font-medium text-[var(--text)]">图片路径</span>
              <span className="break-all">{src || alt || "(未提供路径)"}</span>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export function MarkdownPreview({ content, onFileLinkClick }: Props) {
  return <MarkdownContent content={content} variant="preview" onFileLinkClick={onFileLinkClick} />;
}
