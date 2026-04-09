import type { ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Props = {
  content: string;
};

function InlineCode({ className, children, ...props }: ComponentPropsWithoutRef<"code">) {
  const hasLanguageClass = Boolean(className && className.includes("language-"));
  if (hasLanguageClass) {
    return (
      <code
        className="block overflow-x-auto rounded-xl bg-[#1f2430] px-4 py-3 font-mono text-[13px] leading-6 text-[#f3f4f6]"
        {...props}
      >
        {children}
      </code>
    );
  }

  return (
    <code
      className="rounded-md bg-[color:rgba(15,140,120,0.12)] px-1.5 py-0.5 font-mono text-[0.92em] text-[var(--accent)]"
      {...props}
    >
      {children}
    </code>
  );
}

export function MarkdownPreview({ content }: Props) {
  return (
    <div className="max-h-[50vh] overflow-auto rounded-xl bg-[var(--surface-strong)] px-5 py-4 text-[15px] leading-7 text-[var(--text)]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="mb-4 text-3xl font-semibold tracking-tight">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-3 mt-8 text-2xl font-semibold tracking-tight">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-3 mt-6 text-xl font-semibold">{children}</h3>,
          h4: ({ children }) => <h4 className="mb-2 mt-5 text-lg font-semibold">{children}</h4>,
          p: ({ children }) => <p className="my-3 break-words">{children}</p>,
          ul: ({ children }) => <ul className="my-4 list-disc space-y-2 pl-6">{children}</ul>,
          ol: ({ children }) => <ol className="my-4 list-decimal space-y-2 pl-6">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-5 border-l-4 border-[color:rgba(15,140,120,0.45)] bg-[color:rgba(15,140,120,0.07)] px-4 py-3 text-[var(--muted)]">
              {children}
            </blockquote>
          ),
          a: ({ href, children }) => (
            <a
              className="font-medium text-[var(--accent)] underline decoration-[color:rgba(15,140,120,0.35)] underline-offset-4"
              href={href}
              rel="noreferrer"
              target="_blank"
            >
              {children}
            </a>
          ),
          pre: ({ children }) => <pre className="my-4 overflow-x-auto">{children}</pre>,
          code: InlineCode,
          table: ({ children }) => (
            <div className="my-5 overflow-x-auto">
              <table className="min-w-full border-collapse overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)]">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-[color:rgba(15,140,120,0.08)]">{children}</thead>,
          tbody: ({ children }) => <tbody>{children}</tbody>,
          tr: ({ children }) => <tr className="border-b border-[var(--border)] last:border-b-0">{children}</tr>,
          th: ({ children }) => <th className="px-3 py-2 text-left text-sm font-semibold">{children}</th>,
          td: ({ children }) => <td className="px-3 py-2 align-top text-sm">{children}</td>,
          hr: () => <hr className="my-6 border-0 border-t border-[var(--border)]" />,
          img: ({ src, alt }) => (
            <div className="my-4 rounded-xl border border-dashed border-[color:rgba(15,140,120,0.35)] bg-[color:rgba(15,140,120,0.06)] px-4 py-3 text-sm text-[var(--muted)]">
              <span className="mr-2 font-medium text-[var(--text)]">图片路径</span>
              <span>{src || alt || "(未提供路径)"}</span>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
