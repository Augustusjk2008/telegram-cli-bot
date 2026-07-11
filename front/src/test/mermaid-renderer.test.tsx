import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MarkdownContent } from "../components/MarkdownPreview";
import {
  mermaidRendererDiagnostics,
  renderMermaidSingleFlight,
  resetMermaidRendererForTests,
} from "../markdown/mermaidRenderer";

afterEach(() => {
  resetMermaidRendererForTests();
});

function mermaidLoader() {
  const renderDiagram = vi.fn(async (id: string, code: string) => ({
    svg: `<svg id="${id}" data-code="${code}"><defs><clipPath id="${id}-clip" /></defs><g clip-path="url(#${id}-clip)"><a href="#${id}">x</a></g></svg>`,
  }));
  const initialize = vi.fn();
  return {
    initialize,
    renderDiagram,
    load: vi.fn(async () => ({
      default: { initialize, render: renderDiagram },
    })),
  };
}

describe("Mermaid renderer cache", () => {
  it("shares one pending render for concurrent identical diagrams", async () => {
    const loader = mermaidLoader();
    resetMermaidRendererForTests({ load: loader.load });

    const [first, second] = await Promise.all([
      renderMermaidSingleFlight("graph TD;A-->B", "diagram-a"),
      renderMermaidSingleFlight("graph TD;A-->B", "diagram-b"),
    ]);

    expect(first.svg).toContain('id="diagram-a"');
    expect(second.svg).toContain('id="diagram-b"');
    expect(first.svg).not.toBe(second.svg);
    expect(loader.load).toHaveBeenCalledTimes(1);
    expect(loader.initialize).toHaveBeenCalledTimes(1);
    expect(loader.renderDiagram).toHaveBeenCalledTimes(1);
    expect(mermaidRendererDiagnostics()).toMatchObject({ completedEntries: 1, pendingEntries: 0 });
  });

  it("rewrites neutral cached SVG ids for simultaneous mounts", async () => {
    const loader = mermaidLoader();
    resetMermaidRendererForTests({ load: loader.load });
    const content = ["```mermaid", "graph TD;A-->B", "```"].join("\n");

    render(<><MarkdownContent content={content} variant="chat" /><MarkdownContent content={content} variant="chat" /></>);

    const diagrams = await screen.findAllByLabelText("Mermaid 图表");
    const ids = diagrams.map((diagram) => diagram.querySelector("svg")?.id);
    expect(new Set(ids).size).toBe(2);
    for (const diagram of diagrams) {
      const svg = diagram.querySelector("svg");
      const clip = diagram.querySelector("clipPath");
      expect(svg?.querySelector("g")?.getAttribute("clip-path")).toBe(`url(#${clip?.id})`);
      expect(svg?.querySelector("a")?.getAttribute("href")).toBe(`#${svg?.id}`);
    }
    expect(loader.renderDiagram).toHaveBeenCalledTimes(1);
  });

  it("evicts completed LRU entries without changing an already mounted SVG", async () => {
    const loader = mermaidLoader();
    resetMermaidRendererForTests({ load: loader.load, maxEntries: 1, maxWeight: 1024 * 1024 });
    render(
      <MarkdownContent
        content={["```mermaid", "graph TD;A-->B", "```"].join("\n")}
        variant="chat"
      />,
    );

    const mounted = await screen.findByLabelText("Mermaid 图表");
    const mountedSvg = mounted.innerHTML;
    await renderMermaidSingleFlight("graph TD;B-->C", "diagram-c");

    expect(mermaidRendererDiagnostics().completedEntries).toBe(1);
    expect(mounted.innerHTML).toBe(mountedSvg);
    await renderMermaidSingleFlight("graph TD;A-->B", "diagram-a-again");
    expect(loader.renderDiagram).toHaveBeenCalledTimes(3);
  });
});
