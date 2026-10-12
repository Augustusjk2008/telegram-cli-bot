import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { WebBotClient } from "../../services/webBotClient";
import type {
  DocumentBlock,
  DocumentBorder,
  DocumentBorders,
  DocumentParagraphBlock,
  DocumentSectionSummary,
  DocumentParagraphFormat,
  DocumentSlideImageRef,
  DocumentSlideItem,
  DocumentTextRun,
  DocumentViewSummary,
  DocumentWindowPayload,
  PluginAction,
  DocumentWidth,
  PluginRenderResult,
} from "../../services/types";
import { PluginActionBar } from "./PluginActionBar";

type Props = {
  botAlias: string;
  client: WebBotClient;
  view: Extract<PluginRenderResult, { renderer: "document" }>;
  onRunAction?: (action: PluginAction, payload?: Record<string, unknown>) => void | Promise<void>;
};

type DocumentHeadingLevel = Extract<DocumentBlock, { type: "heading" }>["level"];

const PdfView = lazy(() => import("./PdfView"));

type TextStyle = Omit<DocumentTextRun, "text">;

function quoteFontFamily(family: string) {
  return '"' + family.replace(/["\\\u0000-\u001f\u007f]/g, (character) =>
    "\\" + character.codePointAt(0)!.toString(16) + " ") + '"';
}

function fontFamily(style: TextStyle, eastAsia = false) {
  const families = eastAsia
    ? [style.fontFamilyEastAsia, style.fontFamily]
    : [style.fontFamily, style.fontFamilyEastAsia];
  return families.filter((family): family is string => Boolean(family)).map(quoteFontFamily).join(", ") || undefined;
}

function textStyle(style: TextStyle): React.CSSProperties {
  return {
    fontWeight: style.bold === undefined ? undefined : style.bold ? "bold" : "normal",
    fontStyle: style.italic === undefined ? undefined : style.italic ? "italic" : "normal",
    color: style.color,
    fontSize: style.fontSizePx,
    fontFamily: fontFamily(style),
  };
}

function runText(run: DocumentTextRun) {
  if (!run.fontFamilyEastAsia || run.fontFamilyEastAsia === run.fontFamily) {
    return run.text;
  }
  // Select the appropriate font even when the Latin font also contains CJK glyphs.
  return run.text.split(/([\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\p{Script=Bopomofo}\u3000-\u303f\uff00-\uffef]+)/u)
    .map((part, index) => part ? (
      <span key={index} style={{ fontFamily: fontFamily(run, index % 2 === 1) }}>{part}</span>
    ) : null);
}

function renderRuns(
  runs: DocumentTextRun[],
  defaults?: TextStyle,
  document = false,
  lineSpacing?: DocumentParagraphFormat["lineSpacing"],
) {
  return runs.map((run, index) => {
    const effective = { ...defaults, ...run };
    let node = effective.code
      ? <code
          className={document ? undefined : "rounded bg-[var(--surface-strong)] px-1 py-0.5 text-[0.92em]"}
          style={document ? { fontFamily: fontFamily(effective) ?? "monospace", fontSize: "inherit" } : undefined}
        >{runText(effective)}</code>
      : runText(effective);
    if (effective.underline) {
      node = <u>{node}</u>;
    }
    if (effective.italic) {
      node = <em>{node}</em>;
    }
    if (effective.bold) {
      node = <strong style={document || defaults ? { fontWeight: "bold" } : undefined}>{node}</strong>;
    }
    return (
      <span
        key={index}
        style={{
          ...textStyle(effective),
          // Keep the semantic elements' existing weight for legacy payloads.
          fontWeight: effective.bold === false ? "normal" : undefined,
          textDecoration: effective.underline === false ? "none" : undefined,
          backgroundColor: effective.highlightColor === "transparent"
            ? effective.shadingColor
            : effective.highlightColor ?? effective.shadingColor,
          // Fixed paragraph struts provide the minimum; inline fonts can grow it.
          lineHeight: lineSpacing?.mode === "atLeast" ? "normal" : undefined,
        }}
      >
        {node}
      </span>
    );
  });
}

function renderParagraph(block: DocumentParagraphBlock, index: number, document: boolean) {
  const format = block.format;
  const spacing = format?.lineSpacing;
  const Tag = block.type === "heading" ? `h${block.level}` as const : "p";
  const baseline = format?.textStyle;
  const hanging = Math.max(0, -(format?.firstLineIndentPx ?? 0));
  return (
    <Tag
      key={index}
      className="whitespace-pre-wrap"
      style={{
        ...(document ? { margin: 0, padding: 0 } : {}),
        ...textStyle(baseline ?? {}),
        fontSize: baseline?.fontSizePx ?? (document ? "inherit" : undefined),
        fontWeight: baseline?.bold === undefined ? (document ? "normal" : undefined) : baseline.bold ? "bold" : "normal",
        textAlign: format?.align,
        marginLeft: format?.indentLeftPx,
        marginRight: format?.indentRightPx,
        textIndent: format?.firstLineIndentPx,
        marginTop: format?.spaceBeforePx,
        marginBottom: format?.spaceAfterPx,
        lineHeight: spacing
          ? spacing.mode === "multiple" ? spacing.value : `${spacing.value}px`
          : document ? "inherit" : undefined,
      }}
    >
      {block.type === "list_item" ? (
        <span style={{ display: "inline-block", minWidth: hanging || undefined, textIndent: 0 }}>
          {renderRuns([{ ...block.markerStyle, text: block.marker ?? (block.ordered ? "1." : "•") }], baseline, document, spacing)}{hanging ? "" : "\t"}
        </span>
      ) : null}
      {renderRuns(block.runs, baseline, document, spacing)}
      {!block.runs.some((run) => run.text.length) ? (
        <span style={{ lineHeight: spacing?.mode === "atLeast" ? "normal" : undefined }}><br /></span>
      ) : null}
    </Tag>
  );
}

function renderHeading(level: DocumentHeadingLevel, runs: DocumentTextRun[], key: number) {
  const className = "font-semibold text-[var(--text)]";
  if (level === 1) {
    return <h1 key={key} className="text-2xl leading-tight text-[var(--text)]">{renderRuns(runs)}</h1>;
  }
  if (level === 2) {
    return <h2 key={key} className={`text-xl ${className}`}>{renderRuns(runs)}</h2>;
  }
  if (level === 3) {
    return <h3 key={key} className={`text-lg ${className}`}>{renderRuns(runs)}</h3>;
  }
  if (level === 4) {
    return <h4 key={key} className={className}>{renderRuns(runs)}</h4>;
  }
  if (level === 5) {
    return <h5 key={key} className={className}>{renderRuns(runs)}</h5>;
  }
  return <h6 key={key} className={className}>{renderRuns(runs)}</h6>;
}

function ArtifactImage({
  botAlias,
  client,
  image,
  className,
  style,
}: {
  botAlias: string;
  client: WebBotClient;
  image: DocumentSlideImageRef;
  className?: string;
  style?: React.CSSProperties;
}) {
  const [src, setSrc] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl = "";

    client
      .getPluginArtifactBlob(botAlias, image.artifactId)
      .then((blob) => {
        if (!active) {
          return;
        }
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
      })
      .catch((exc: unknown) => {
        if (active) {
          setError(exc instanceof Error ? exc.message : "图片加载失败");
        }
      });

    return () => {
      active = false;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [botAlias, client, image.artifactId]);

  if (error) {
    return <div className="rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">{error}</div>;
  }
  if (!src) {
    return <div className="text-xs text-[var(--muted)]">图片加载中...</div>;
  }
  return (
    <img
      src={src}
      alt={image.alt || image.title || image.filename}
      title={image.title || image.filename}
      loading="lazy"
      decoding="async"
      onError={() => setError("图片加载失败")}
      className={className}
      style={style}
    />
  );
}

function DocumentImage({
  botAlias,
  client,
  block,
  document = false,
}: {
  botAlias: string;
  client: WebBotClient;
  block: Extract<DocumentBlock, { type: "image" }>;
  document?: boolean;
}) {
  const width = Number(block.widthPx || 0);
  const height = Number(block.heightPx || 0);
  return (
    <figure className={document ? "m-0" : "space-y-2"}>
      <ArtifactImage
        botAlias={botAlias}
        client={client}
        image={block}
        className={document ? "max-w-full object-contain" : "max-w-full rounded border border-[var(--border)] bg-[var(--surface)] object-contain"}
        style={{
          maxWidth: width > 0 ? `${width}px` : "100%",
          maxHeight: height > 0 ? `${Math.max(height, 160)}px` : undefined,
        }}
      />
      {block.caption ? <figcaption className="text-xs text-[var(--muted)]">{block.caption}</figcaption> : null}
    </figure>
  );
}

function frameStyle(item: DocumentSlideItem): React.CSSProperties {
  return {
    left: `${item.frame.x}px`,
    top: `${item.frame.y}px`,
    width: `${item.frame.width}px`,
    height: `${item.frame.height}px`,
    zIndex: item.zIndex ?? 0,
  };
}

function renderSlideText(item: Extract<DocumentSlideItem, { type: "text" }>) {
  return (
    <div className="h-full overflow-hidden text-[var(--text)]">
      {item.paragraphs.map((paragraph, index) => (
        <p
          key={index}
          className="mb-1 whitespace-pre-wrap leading-snug last:mb-0"
          style={{
            textAlign: paragraph.align || "left",
            paddingLeft: `${(paragraph.level || 0) * 18}px`,
          }}
        >
          {paragraph.bullet ? <span className="mr-2 text-[var(--muted)]">{paragraph.bullet}</span> : null}
          {renderRuns(paragraph.runs)}
        </p>
      ))}
    </div>
  );
}

function renderSlideTable(item: Extract<DocumentSlideItem, { type: "table" }>) {
  return (
    <div className="h-full overflow-hidden rounded border border-black/10 bg-white/85">
      <table className="h-full w-full table-fixed border-collapse text-[11px]">
        <tbody>
          {item.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.cells.map((cell, cellIndex) => (
                <td key={cellIndex} className="border border-black/10 px-1 py-0.5 align-top">
                  <div className="whitespace-pre-wrap leading-tight">{renderRuns(cell.runs)}</div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DocumentSlide({
  botAlias,
  client,
  block,
}: {
  botAlias: string;
  client: WebBotClient;
  block: Extract<DocumentBlock, { type: "slide" }>;
}) {
  const backgroundColor = block.background?.color || "#ffffff";
  return (
    <section className="space-y-2" aria-label={`幻灯片 ${block.slideNumber}`}>
      <div className="flex items-center justify-between gap-3 text-xs text-[var(--muted)]">
        <span>{`幻灯片 ${block.slideNumber}`}</span>
        {block.title ? <span className="truncate">{block.title}</span> : null}
      </div>
      <div className="overflow-auto rounded border border-[var(--border)] bg-[var(--surface-strong)] p-3">
        <div
          className="relative overflow-hidden shadow-sm"
          style={{
            width: `${block.widthPx}px`,
            height: `${block.heightPx}px`,
            backgroundColor,
          }}
        >
          {block.background?.image ? (
            <ArtifactImage
              botAlias={botAlias}
              client={client}
              image={block.background.image}
              className="absolute inset-0 h-full w-full object-cover"
            />
          ) : null}
          {block.items.map((item, index) => {
            if (item.type === "text") {
              return (
                <div key={index} className="absolute overflow-hidden" style={frameStyle(item)}>
                  {renderSlideText(item)}
                </div>
              );
            }
            if (item.type === "image") {
              return (
                <div key={index} className="absolute overflow-hidden" style={frameStyle(item)}>
                  <ArtifactImage
                    botAlias={botAlias}
                    client={client}
                    image={item.image}
                    className="h-full w-full object-contain"
                  />
                </div>
              );
            }
            if (item.type === "table") {
              return (
                <div key={index} className="absolute overflow-hidden" style={frameStyle(item)}>
                  {renderSlideTable(item)}
                </div>
              );
            }
            return (
              <div
                key={index}
                className="absolute flex items-center justify-center rounded border border-dashed border-black/20 bg-white/60 px-2 text-center text-[10px] text-[var(--muted)]"
                style={frameStyle(item)}
              >
                {item.label}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function widthStyle(width?: DocumentWidth) {
  return width ? String(width.value) + (width.unit === "percent" ? "%" : "px") : undefined;
}

function borderValue(border?: DocumentBorder) {
  if (!border) return undefined;
  return border.style === "none" ? "none" : `${border.widthPx ?? 1}px ${border.style} ${border.color ?? "currentColor"}`;
}

function borderStyle(borders?: DocumentBorders): React.CSSProperties {
  return {
    borderTop: borderValue(borders?.top),
    borderRight: borderValue(borders?.right),
    borderBottom: borderValue(borders?.bottom),
    borderLeft: borderValue(borders?.left),
  };
}

function renderTable(
  block: Extract<DocumentBlock, { type: "table" }>,
  index: number,
  botAlias: string,
  client: WebBotClient,
  document: boolean,
) {
  // Locate cells in the grid, including slots occupied by earlier row spans.
  const occupiedUntil: number[] = [];
  let columnCount = block.columnWidthsPx?.length ?? 0;
  const rows = block.rows.map((row, rowIndex) => {
    let column = 0;
    return row.cells.map((cell) => {
      while ((occupiedUntil[column] ?? 0) > rowIndex) column += 1;
      const start = column;
      const endRow = cell.rowSpan === 0 ? block.rows.length : rowIndex + (cell.rowSpan ?? 1);
      column += cell.colSpan ?? 1;
      for (let slot = start; slot < column; slot += 1) occupiedUntil[slot] = endRow;
      columnCount = Math.max(columnCount, column);
      return { cell, start, end: column, endRow };
    });
  });
  return (
    <div key={index} className={document ? "overflow-x-auto" : "overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--surface)]"}>
      <table
        className={document ? "border-collapse" : "min-w-full border-collapse text-sm"}
        style={{
          width: widthStyle(block.width),
          minWidth: block.width ? 0 : undefined,
          backgroundColor: block.shadingColor,
          ...(document ? { font: "inherit", color: "inherit" } : {}),
        }}
      >
        {block.columnWidthsPx?.length ? (
          <colgroup>{block.columnWidthsPx.map((width, column) => <col key={column} style={{ width }} />)}</colgroup>
        ) : null}
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className={document ? undefined : "border-b border-[var(--border)] last:border-b-0"}>
              {row.map(({ cell, start, end, endRow }, cellIndex) => {
                const borders = block.borders;
                const padding = { ...block.cellPadding, ...cell.padding };
                return (
                  <td
                    key={cellIndex}
                    rowSpan={cell.rowSpan}
                    colSpan={cell.colSpan}
                    className={document ? undefined : "align-top border-r border-[var(--border)] px-3 py-2 last:border-r-0"}
                    style={{
                      width: widthStyle(cell.width),
                      verticalAlign: cell.verticalAlign === "center" ? "middle" : cell.verticalAlign ?? (document ? "top" : undefined),
                      backgroundColor: cell.shadingColor,
                      paddingTop: padding.topPx ?? (document ? 0 : undefined),
                      paddingRight: padding.rightPx ?? (document ? 0 : undefined),
                      paddingBottom: padding.bottomPx ?? (document ? 0 : undefined),
                      paddingLeft: padding.leftPx ?? (document ? 0 : undefined),
                      ...borderStyle({
                        top: rowIndex === 0 ? borders?.top : borders?.insideHorizontal,
                        bottom: endRow === rows.length ? borders?.bottom : borders?.insideHorizontal,
                        left: start === 0 ? borders?.left : borders?.insideVertical,
                        right: end === columnCount ? borders?.right : borders?.insideVertical,
                        ...cell.borders,
                      }),
                    }}
                  >
                    {cell.paragraphs !== undefined
                      ? cell.paragraphs.map((paragraph, paragraphIndex) => renderBlock(paragraph, paragraphIndex, botAlias, client, document))
                      : <div className={document ? "whitespace-pre-wrap" : "whitespace-pre-wrap text-[var(--text)]"}>{renderRuns(cell.runs, undefined, document)}</div>}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderBlock(block: DocumentBlock, index: number, botAlias: string, client: WebBotClient, document = false) {
  if ((block.type === "paragraph" || block.type === "heading" || block.type === "list_item") && (document || block.format)) {
    return renderParagraph(block, index, document);
  }
  if (block.type === "heading") {
    return renderHeading(block.level, block.runs, index);
  }
  if (block.type === "paragraph") {
    return <p key={index} className="whitespace-pre-wrap leading-7 text-[var(--text)]">{renderRuns(block.runs)}</p>;
  }
  if (block.type === "list_item") {
    return (
      <div
        key={index}
        className="flex gap-3 text-[var(--text)]"
        style={{ paddingLeft: `${(block.depth || 0) * 20}px` }}
      >
        <span className="w-8 shrink-0 text-[var(--muted)]">{block.marker || (block.ordered ? "1." : "•")}</span>
        <div className="min-w-0 flex-1 whitespace-pre-wrap">{renderRuns(block.runs)}</div>
      </div>
    );
  }
  if (block.type === "image") {
    return <DocumentImage key={index} botAlias={botAlias} client={client} block={block} document={document} />;
  }
  if (block.type === "slide") {
    return <DocumentSlide key={index} botAlias={botAlias} client={client} block={block} />;
  }
  if (block.type === "table") {
    return renderTable(block, index, botAlias, client, document);
  }
  return (
    <div key={index} className="text-sm text-[var(--muted)]">不支持的文档块</div>
  );
}

function sectionId(section: DocumentSectionSummary | undefined, index: number) {
  return section?.sectionId || section?.id || `section-${index}`;
}

function sectionTitle(section: DocumentSectionSummary, index: number) {
  return section.title || section.label || `第 ${index + 1} 节`;
}

function snapshotSummary(view: Extract<PluginRenderResult, { renderer: "document"; mode: "snapshot" }>): DocumentViewSummary {
  return {
    path: view.payload.path,
    title: view.payload.title,
    statsText: view.payload.statsText,
    formatting: view.payload.formatting,
    sections: [],
    actions: view.payload.actions,
  };
}

export function DocumentView(props: Props) {
  const { botAlias, client, view } = props;
  if (view.mode === "snapshot" && view.payload.pdf) {
    return (
      <Suspense fallback={<div className="p-5 text-sm text-[var(--muted)]">PDF 加载中...</div>}>
        <PdfView key={`${botAlias}:${view.payload.pdf.artifactId}`} botAlias={botAlias} client={client} payload={view.payload} />
      </Suspense>
    );
  }
  const contentKey = `${botAlias}:${view.pluginId}:${view.viewId}:${view.mode}:${view.mode === "session" ? view.sessionId : view.payload.path}`;
  return <DocumentContent key={contentKey} {...props} />;
}

function DocumentContent({ botAlias, client, view, onRunAction }: Props) {
  const session = view.mode === "session" ? view : null;
  const snapshot = view.mode === "snapshot" ? view : null;
  const summary = session ? session.summary : snapshotSummary(snapshot!);
  const initialWindow: DocumentWindowPayload = session
    ? session.initialWindow
    : { sectionId: "snapshot", blocks: snapshot!.payload.blocks };
  const initialSectionId = initialWindow.sectionId || sectionId(summary.sections[0], 0);
  const [selectedSectionId, setSelectedSectionId] = useState(initialSectionId);
  const [windows, setWindows] = useState(() => new Map([[initialSectionId, { ...initialWindow, sectionId: initialSectionId }]]));
  const [windowError, setWindowError] = useState("");
  const [loadAttempt, setLoadAttempt] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const navigationRef = useRef<HTMLElement>(null);
  const sectionRefs = useRef(new Map<string, HTMLDivElement>());
  const pendingSectionRef = useRef<string | null>(null);
  const sectionIds = summary.sections.map(sectionId);
  const nextSectionId = session ? sectionIds.find((id) => !windows.has(id)) : undefined;

  useEffect(() => {
    if (!session || !nextSectionId) {
      return;
    }
    const controller = new AbortController();
    setWindowError("");

    void client.queryPluginViewWindow(
      botAlias,
      view.pluginId,
      session.sessionId,
      { sectionId: nextSectionId },
      controller.signal,
    ).then((payload) => {
      if (controller.signal.aborted) {
        return;
      }
      const next = payload as DocumentWindowPayload;
      setWindows((previous) => new Map(previous).set(nextSectionId, {
        ...next,
        sectionId: nextSectionId,
        blocks: Array.isArray(next.blocks) ? next.blocks : [],
      }));
    }).catch((error: unknown) => {
      if (controller.signal.aborted) {
        return;
      }
      setWindowError(error instanceof Error && error.message ? error.message : "加载文档章节失败");
    });

    return () => controller.abort();
  }, [botAlias, client, nextSectionId, session?.sessionId, view.pluginId, loadAttempt]);

  function scrollToSection(id: string) {
    const container = scrollRef.current;
    const target = sectionRefs.current.get(id);
    if (!container || !target) {
      return false;
    }
    container.scrollTo({
      top: container.scrollTop + target.getBoundingClientRect().top - container.getBoundingClientRect().top
        - (navigationRef.current?.offsetHeight || 0) - 12,
      behavior: "auto",
    });
    return true;
  }

  useEffect(() => {
    const pending = pendingSectionRef.current;
    if (pending && scrollToSection(pending)) {
      pendingSectionRef.current = null;
    }
  }, [windows]);

  function selectSection(id: string) {
    setSelectedSectionId(id);
    pendingSectionRef.current = scrollToSection(id) ? null : id;
  }

  function updateCurrentSection() {
    const container = scrollRef.current;
    if (!container || pendingSectionRef.current) {
      return;
    }
    const top = container.getBoundingClientRect().top + (navigationRef.current?.offsetHeight || 0) + 16;
    let current = initialSectionId;
    for (const id of sectionIds) {
      const target = sectionRefs.current.get(id);
      if (!target || target.getBoundingClientRect().top > top) {
        break;
      }
      current = id;
    }
    if (container.scrollTop > 0 && Math.ceil(container.scrollTop + container.clientHeight) >= container.scrollHeight) {
      current = sectionIds.filter((id) => windows.has(id)).at(-1) || current;
    }
    setSelectedSectionId(current);
  }

  const document = summary.formatting === "document";
  const actions = session ? summary.actions : snapshot!.payload.actions;
  const visibleWindows = session
    ? (sectionIds.length ? sectionIds : [initialSectionId]).flatMap((id) => windows.has(id) ? [windows.get(id)!] : [])
    : [initialWindow];
  const hasBlocks = visibleWindows.some((window) => window.blocks.length);
  return (
    <div ref={scrollRef} onScroll={updateCurrentSection} data-testid="document-view" className="flex h-full min-h-0 flex-col overflow-y-auto px-5 pb-5">
      <div className="mb-4 shrink-0 pt-5">
        <PluginActionBar actions={actions} onRunAction={(action) => onRunAction?.(action)} />
        <div className="text-lg font-semibold text-[var(--text)]">{summary.title || view.title}</div>
        <div className="mt-1 text-xs text-[var(--muted)]">{summary.path}</div>
        {summary.statsText ? <div className="mt-1 text-xs text-[var(--muted)]">{summary.statsText}</div> : null}
      </div>

      {session && summary.sections.length ? (
        <nav ref={navigationRef} data-testid="document-section-list" aria-label="文档章节" className="sticky top-0 z-10 mb-3 flex shrink-0 items-center gap-3 border-b border-[var(--border)] bg-[var(--surface)]">
          <span className="shrink-0 text-xs text-[var(--muted)]">目录</span>
          <div className="flex min-w-0 gap-4 overflow-x-auto">
            {summary.sections.map((section, index) => {
              const currentSectionId = sectionId(section, index);
              const active = currentSectionId === selectedSectionId;
              return (
                <button
                  key={currentSectionId}
                  type="button"
                  aria-current={active ? "location" : undefined}
                  title={sectionTitle(section, index)}
                  onClick={() => selectSection(currentSectionId)}
                  className={`max-w-56 shrink-0 truncate border-b-2 py-2 text-sm ${active
                    ? "border-[var(--accent)] text-[var(--accent)]"
                    : "border-transparent text-[var(--muted)] hover:text-[var(--text)]"}`}
                >
                  {sectionTitle(section, index)}
                </button>
              );
            })}
          </div>
        </nav>
      ) : null}

      {hasBlocks || nextSectionId ? (
        <div
          data-testid="document-section-content"
          className={document ? "flow-root shrink-0 p-4" : "space-y-4 pb-6"}
          style={document ? {
            backgroundColor: "#ffffff",
            color: "#000000",
            fontFamily: "serif",
            fontSize: 16,
            fontWeight: "normal",
            fontStyle: "normal",
            lineHeight: "normal",
          } : undefined}
        >
          {session ? visibleWindows.map((window) => (
            <div
              key={window.sectionId}
              ref={(element) => {
                if (element) sectionRefs.current.set(window.sectionId, element);
                else sectionRefs.current.delete(window.sectionId);
              }}
              data-section-id={window.sectionId}
              className={document ? "flow-root" : "space-y-4"}
            >
              {window.blocks.map((block, index) => renderBlock(block, index, botAlias, client, document))}
            </div>
          )) : initialWindow.blocks.map((block, index) => renderBlock(block, index, botAlias, client, document))}
        </div>
      ) : windowError ? null : (
        <div className="text-sm text-[var(--muted)]">文档暂无可预览内容</div>
      )}

      {windowError ? (
        <div role="alert" className="flex shrink-0 items-center gap-3 py-3 text-sm text-red-600">
          <span>{windowError}</span>
          <button type="button" className="shrink-0 text-[var(--accent)] hover:underline" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>重试</button>
        </div>
      ) : nextSectionId ? (
        <div role="status" className="shrink-0 py-3 text-sm text-[var(--muted)]">正在加载后续内容…</div>
      ) : null}
    </div>
  );
}
