import { Fragment, useEffect, useState } from "react";
import type { WebBotClient } from "../../services/webBotClient";
import type { DocumentBlock, DocumentTextRun, PluginRenderResult } from "../../services/types";

type Props = {
  botAlias: string;
  client: WebBotClient;
  view: Extract<PluginRenderResult, { renderer: "document"; mode: "snapshot" }>;
};

type DocumentHeadingLevel = Extract<DocumentBlock, { type: "heading" }>["level"];

function renderRuns(runs: DocumentTextRun[]) {
  return runs.map((run, index) => {
    let node = run.code
      ? <code className="rounded bg-[var(--surface-strong)] px-1 py-0.5 text-[0.92em]">{run.text}</code>
      : run.text;
    if (run.underline) {
      node = <u>{node}</u>;
    }
    if (run.italic) {
      node = <em>{node}</em>;
    }
    if (run.bold) {
      node = <strong>{node}</strong>;
    }
    return <Fragment key={`${index}-${run.text}`}>{node}</Fragment>;
  });
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

function DocumentImage({
  botAlias,
  client,
  block,
}: {
  botAlias: string;
  client: WebBotClient;
  block: Extract<DocumentBlock, { type: "image" }>;
}) {
  const [src, setSrc] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let objectUrl = "";

    client
      .getPluginArtifactBlob(botAlias, block.artifactId)
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
  }, [block.artifactId, botAlias, client]);

  if (error) {
    return <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>;
  }
  if (!src) {
    return <div className="text-sm text-[var(--muted)]">图片加载中...</div>;
  }

  const width = Number(block.widthPx || 0);
  const height = Number(block.heightPx || 0);
  return (
    <figure className="space-y-2">
      <img
        src={src}
        alt={block.alt || block.title || block.filename}
        title={block.title || block.filename}
        className="max-w-full rounded border border-[var(--border)] bg-[var(--surface)] object-contain"
        style={{
          maxWidth: width > 0 ? `${width}px` : "100%",
          maxHeight: height > 0 ? `${Math.max(height, 160)}px` : undefined,
        }}
      />
      {block.caption ? <figcaption className="text-xs text-[var(--muted)]">{block.caption}</figcaption> : null}
    </figure>
  );
}

function renderBlock(block: DocumentBlock, index: number, botAlias: string, client: WebBotClient) {
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
    return <DocumentImage key={index} botAlias={botAlias} client={client} block={block} />;
  }
  return (
    <div key={index} className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <table className="min-w-full border-collapse text-sm">
        <tbody>
          {block.rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="border-b border-[var(--border)] last:border-b-0">
              {row.cells.map((cell, cellIndex) => (
                <td key={cellIndex} className="align-top border-r border-[var(--border)] px-3 py-2 last:border-r-0">
                  <div className="whitespace-pre-wrap text-[var(--text)]">{renderRuns(cell.runs)}</div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DocumentView({ botAlias, client, view }: Props) {
  return (
    <div data-testid="document-view" className="flex h-full min-h-0 flex-col overflow-y-auto p-5">
      <div className="mb-4">
        <div className="text-lg font-semibold text-[var(--text)]">{view.payload.title || view.title}</div>
        <div className="mt-1 text-xs text-[var(--muted)]">{view.payload.path}</div>
        {view.payload.statsText ? <div className="mt-1 text-xs text-[var(--muted)]">{view.payload.statsText}</div> : null}
      </div>
      {view.payload.blocks.length ? (
        <div className="space-y-4 pb-6">
          {view.payload.blocks.map((block, index) => renderBlock(block, index, botAlias, client))}
        </div>
      ) : (
        <div className="text-sm text-[var(--muted)]">文档暂无可预览内容</div>
      )}
    </div>
  );
}
