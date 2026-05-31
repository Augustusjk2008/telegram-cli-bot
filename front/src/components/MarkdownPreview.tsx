import { Children, isValidElement, type ComponentPropsWithoutRef, type ReactNode, useEffect, useRef, useState } from "react";
import { CheckCheck, Copy } from "lucide-react";
import "katex/dist/katex.min.css";
import rehypeKatex from "rehype-katex";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { copyText } from "../utils/clipboard";
import { isExternalHref, isLikelyLocalFileHref, isSafeMarkdownHref } from "../utils/fileLinks";

type Props = {
  content: string;
  variant?: "preview" | "desktop-preview";
  onFileLinkClick?: (href: string) => void;
  resolveImageSrc?: (src: string) => string;
};

type MarkdownContentProps = {
  content: string;
  variant?: "preview" | "desktop-preview" | "chat";
  onFileLinkClick?: (href: string) => void;
  resolveImageSrc?: (src: string) => string;
};

function safeUrlTransform(url: string) {
  return isSafeMarkdownHref(url) ? url : "";
}

let mermaidInitialized = false;
const mermaidRenderCache = new Map<string, { svg: string; error: string }>();

function stringifyCodeChildren(children: ReactNode) {
  if (Array.isArray(children)) {
    return children.map((item) => stringifyCodeChildren(item)).join("");
  }
  return typeof children === "string" ? children : String(children ?? "");
}

function MermaidDiagram({ code, isChat }: { code: string; isChat: boolean }) {
  const [rendered, setRendered] = useState(() => ({
    code,
    svg: mermaidRenderCache.get(code)?.svg || "",
    error: mermaidRenderCache.get(code)?.error || "",
  }));
  const diagramIdRef = useRef(`mermaid-${Math.random().toString(36).slice(2)}`);

  useEffect(() => {
    const cached = mermaidRenderCache.get(code);
    if (cached) {
      setRendered({ code, ...cached });
      return;
    }

    let active = true;
    setRendered((current) => (
      current.code === code && !current.svg && !current.error
        ? current
        : { code, svg: "", error: "" }
    ));

    void import("mermaid")
      .then(({ default: mermaid }) => {
        if (!mermaidInitialized) {
          mermaid.initialize({
            startOnLoad: false,
            securityLevel: "strict",
            theme: "neutral",
            suppressErrorRendering: true,
          });
          mermaidInitialized = true;
        }

        return mermaid.render(diagramIdRef.current, code);
      })
      .then((result) => {
        if (!active) {
          return;
        }
        const next = { svg: result.svg, error: "" };
        mermaidRenderCache.set(code, next);
        setRendered({ code, ...next });
      })
      .catch(() => {
        if (!active) {
          return;
        }
        const next = { svg: "", error: "Mermaid 图表渲染失败，已回退为源码。" };
        mermaidRenderCache.set(code, next);
        setRendered({ code, ...next });
      });

    return () => {
      active = false;
    };
  }, [code]);

  const svg = rendered.code === code ? rendered.svg : "";
  const error = rendered.code === code ? rendered.error : "";

  if (error) {
    return (
      <div
        data-mermaid-wrapper="true"
        className={isChat
          ? "rounded-xl border border-dashed border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800"
          : "my-4 rounded-xl border border-dashed border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800"}
      >
        <div className="mb-2 font-medium">{error}</div>
        <pre className="min-w-0 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-white/70 px-3 py-2 font-mono text-[13px] leading-6">
          {code}
        </pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <div
        data-mermaid-wrapper="true"
        className={isChat
          ? "rounded-xl border border-dashed border-[var(--accent-outline)] bg-[var(--accent-soft)] px-4 py-3 text-sm text-[var(--muted)]"
          : "my-4 rounded-xl border border-dashed border-[var(--accent-outline)] bg-[var(--accent-soft)] px-4 py-3 text-sm text-[var(--muted)]"}
      >
        正在渲染 Mermaid 图表...
      </div>
    );
  }

  return (
    <div
      data-mermaid-wrapper="true"
      data-mermaid-diagram="true"
      aria-label="Mermaid 图表"
      className={isChat
        ? "overflow-auto rounded-xl border border-[var(--border)] bg-white px-3 py-3 [&_svg]:h-auto [&_svg]:max-w-full"
        : "my-4 overflow-auto rounded-xl border border-[var(--border)] bg-white px-3 py-3 [&_svg]:h-auto [&_svg]:max-w-full"}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

type MarkdownCodeProps = ComponentPropsWithoutRef<"code"> & {
  node?: unknown;
  isChat: boolean;
};

type MarkdownPreChildProps = ComponentPropsWithoutRef<"code"> & {
  "data-mermaid-wrapper"?: boolean | string;
};

function MarkdownCode({ className, children, node: _node, isChat, ...props }: MarkdownCodeProps) {
  const codeText = stringifyCodeChildren(children).replace(/\n$/, "");
  if (className?.includes("language-mermaid")) {
    return <MermaidDiagram code={codeText} isChat={isChat} />;
  }

  const hasLanguageClass = Boolean(className && className.includes("language-"));
  if (hasLanguageClass) {
    return (
      <code
        className="block overflow-x-auto rounded-xl border border-[var(--code-border)] bg-[var(--code-bg)] px-4 py-3 font-mono text-[13px] leading-6 text-[var(--code-text)]"
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

function MarkdownPre({
  children,
  isChat,
}: {
  children: ReactNode;
  isChat: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const copyFeedbackTimerRef = useRef<number | null>(null);
  const childNodes = Children.toArray(children);
  const firstChild = childNodes[0];
  const firstChildElement = isValidElement<MarkdownPreChildProps>(firstChild) ? firstChild : null;

  useEffect(() => () => {
    if (copyFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
  }, []);

  if (
    childNodes.length === 1
    && firstChildElement
    && Boolean(firstChildElement.props["data-mermaid-wrapper"])
  ) {
    return <>{firstChild}</>;
  }

  const codeText = childNodes.length === 1 && firstChildElement
    ? stringifyCodeChildren(firstChildElement.props.children).replace(/\n$/, "")
    : stringifyCodeChildren(children).replace(/\n$/, "");

  if (firstChildElement?.props.className?.includes("language-mermaid")) {
    return <MermaidDiagram code={codeText} isChat={isChat} />;
  }

  const copyButtonLabel = copied ? "已复制代码块" : "复制代码块";
  const handleCopyCode = async () => {
    if (copied) {
      return;
    }

    const ok = await copyText(codeText);
    if (!ok) {
      setCopyFailed(true);
      return;
    }

    setCopyFailed(false);
    setCopied(true);
    if (copyFeedbackTimerRef.current !== null) {
      window.clearTimeout(copyFeedbackTimerRef.current);
    }
    copyFeedbackTimerRef.current = window.setTimeout(() => {
      setCopied(false);
      copyFeedbackTimerRef.current = null;
    }, 2000);
  };

  return (
    <div className={isChat ? "group relative min-w-0 overflow-hidden rounded-xl border border-[var(--code-border)] bg-[var(--code-bg)]" : "group relative my-4 min-w-0 overflow-hidden rounded-xl border border-[var(--code-border)] bg-[var(--code-bg)]"}>
      <button
        type="button"
        aria-label={copyButtonLabel}
        title={copyButtonLabel}
        disabled={copied}
        onClick={() => {
          void handleCopyCode();
        }}
        className={copied
          ? "absolute right-2 top-2 z-10 inline-flex h-7 w-7 items-center justify-center rounded-md border border-[var(--accent-outline)] bg-[var(--accent-soft)] text-[var(--accent)] transition-colors disabled:cursor-not-allowed"
          : "absolute right-2 top-2 z-10 inline-flex h-7 w-7 items-center justify-center rounded-md border border-[var(--code-copy-border)] bg-[var(--code-copy-bg)] text-[var(--code-copy-text)] opacity-0 transition-colors hover:bg-[var(--code-copy-bg-hover)] focus-visible:opacity-100 group-hover:opacity-100"}
      >
        {copied ? <CheckCheck className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
      {copyFailed ? (
        <div className="absolute right-2 top-10 z-10 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">
          复制失败，请检查剪贴板权限
        </div>
      ) : null}
      <pre className="min-w-0 overflow-x-auto">
        <code className="block bg-transparent px-4 py-3 pr-12 font-mono text-[13px] leading-6 text-[var(--code-text)]">
          {codeText}
        </code>
      </pre>
    </div>
  );
}

export function MarkdownContent({ content, variant = "preview", onFileLinkClick, resolveImageSrc }: MarkdownContentProps) {
  const isChat = variant === "chat";
  const isDesktopPreview = variant === "desktop-preview";
  const lastLocalLinkActivationRef = useRef<{ href: string; at: number } | null>(null);
  const containerClassName = isChat
    ? "chat-body-content chat-markdown-content min-w-0 w-full text-[var(--text)]"
    : isDesktopPreview
      ? "h-full overflow-auto rounded-xl bg-[var(--surface-strong)] px-5 py-4 text-[15px] leading-7 text-[var(--text)]"
      : "max-h-[50vh] overflow-auto rounded-xl bg-[var(--surface-strong)] px-5 py-4 text-[15px] leading-7 text-[var(--text)]";

  function activateLocalLink(
    event: { preventDefault: () => void; stopPropagation: () => void },
    href: string,
  ) {
    event.preventDefault();
    event.stopPropagation();
    if (!onFileLinkClick) {
      return;
    }

    const now = Date.now();
    const lastActivation = lastLocalLinkActivationRef.current;
    if (lastActivation && lastActivation.href === href && now - lastActivation.at < 400) {
      return;
    }

    lastLocalLinkActivationRef.current = { href, at: now };
    onFileLinkClick(href);
  }

  return (
    <div className={containerClassName}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        urlTransform={safeUrlTransform}
        components={{
          h1: ({ children }) => <h1 className={isChat ? "break-words text-3xl font-semibold tracking-tight [overflow-wrap:anywhere]" : "mb-4 break-words text-3xl font-semibold tracking-tight [overflow-wrap:anywhere]"}>{children}</h1>,
          h2: ({ children }) => <h2 className={isChat ? "break-words text-2xl font-semibold tracking-tight [overflow-wrap:anywhere]" : "mb-3 mt-8 break-words text-2xl font-semibold tracking-tight [overflow-wrap:anywhere]"}>{children}</h2>,
          h3: ({ children }) => <h3 className={isChat ? "break-words text-xl font-semibold [overflow-wrap:anywhere]" : "mb-3 mt-6 break-words text-xl font-semibold [overflow-wrap:anywhere]"}>{children}</h3>,
          h4: ({ children }) => <h4 className={isChat ? "break-words text-lg font-semibold [overflow-wrap:anywhere]" : "mb-2 mt-5 break-words text-lg font-semibold [overflow-wrap:anywhere]"}>{children}</h4>,
          p: ({ children }) => <p className={isChat ? "break-words [overflow-wrap:anywhere]" : "my-3 break-words [overflow-wrap:anywhere]"}>{children}</p>,
          ul: ({ children }) => <ul className={isChat ? "list-disc space-y-2 pl-6" : "my-4 list-disc space-y-2 pl-6"}>{children}</ul>,
          ol: ({ children }) => <ol className={isChat ? "list-decimal space-y-2 pl-6" : "my-4 list-decimal space-y-2 pl-6"}>{children}</ol>,
          li: ({ children }) => <li className="break-words pl-1 [overflow-wrap:anywhere]">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className={isChat
              ? "break-words border-l-4 border-[var(--accent-outline)] bg-[var(--accent-soft)] px-4 py-3 text-[var(--muted)] [overflow-wrap:anywhere]"
              : "my-5 break-words border-l-4 border-[var(--accent-outline)] bg-[var(--accent-soft)] px-4 py-3 text-[var(--muted)] [overflow-wrap:anywhere]"}
            >
              {children}
            </blockquote>
          ),
          a: ({ href, children }) => {
            const nextHref = href || "";
            const handleFileLink = Boolean(onFileLinkClick && nextHref && isLikelyLocalFileHref(nextHref));

            return (
              <a
                className="break-all font-medium text-[var(--accent)] underline decoration-[var(--accent-outline)] underline-offset-4"
                data-local-file-href={handleFileLink ? nextHref : undefined}
                href={nextHref || undefined}
                rel={handleFileLink ? undefined : "noreferrer"}
                target={handleFileLink ? undefined : "_blank"}
                onMouseDown={handleFileLink ? (event) => {
                  activateLocalLink(event, nextHref);
                } : undefined}
                onClick={handleFileLink ? (event) => {
                  activateLocalLink(event, nextHref);
                } : undefined}
              >
                {children}
              </a>
            );
          },
          pre: ({ children }) => <MarkdownPre isChat={isChat}>{children}</MarkdownPre>,
          code: ({ node, className, children, ...props }) => (
            <MarkdownCode node={node} className={className} isChat={isChat} {...props}>
              {children}
            </MarkdownCode>
          ),
          table: ({ children }) => (
            <div className={isChat ? "overflow-x-auto" : "my-5 overflow-x-auto"}>
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
          hr: () => <hr className={isChat ? "border-0 border-t border-[var(--border)]" : "my-6 border-0 border-t border-[var(--border)]"} />,
          img: ({ src, alt }) => {
            const rawSrc = src || "";
            const resolvedSrc = rawSrc
              ? resolveImageSrc?.(rawSrc) || (isSafeMarkdownHref(rawSrc) && isExternalHref(rawSrc) ? rawSrc : "")
              : "";

            if (resolvedSrc) {
              return (
                <span className={isChat ? "my-2 block" : "my-4 block"}>
                  <img
                    src={resolvedSrc}
                    alt={alt || rawSrc || "Markdown 图片"}
                    loading="lazy"
                    decoding="async"
                    className="block h-auto max-w-full rounded-lg border border-[var(--border)] bg-[var(--surface)]"
                  />
                  {alt ? (
                    <span className="mt-2 block text-xs leading-5 text-[var(--muted)]">{alt}</span>
                  ) : null}
                </span>
              );
            }

            return (
              <span className={isChat
                ? "block rounded-xl border border-dashed border-[var(--accent-outline)] bg-[var(--accent-soft)] px-4 py-3 text-sm text-[var(--muted)]"
                : "my-4 block rounded-xl border border-dashed border-[var(--accent-outline)] bg-[var(--accent-soft)] px-4 py-3 text-sm text-[var(--muted)]"}
              >
                <span className="mr-2 font-medium text-[var(--text)]">图片路径</span>
                <span className="break-all">{rawSrc || alt || "(未提供路径)"}</span>
              </span>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

export function MarkdownPreview({ content, variant = "preview", onFileLinkClick, resolveImageSrc }: Props) {
  return (
    <MarkdownContent
      content={content}
      variant={variant}
      onFileLinkClick={onFileLinkClick}
      resolveImageSrc={resolveImageSrc}
    />
  );
}
