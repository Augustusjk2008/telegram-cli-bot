import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MarkdownContent } from "../components/MarkdownPreview";
import {
  mermaidRendererDiagnostics,
  mermaidAppearance,
  renderMermaidSingleFlight,
  resetMermaidRendererForTests,
} from "../markdown/mermaidRenderer";
import { applyResolvedAppearance } from "../theme/appearanceRuntime";
import { BUILTIN_THEME, resolveAppearance } from "../theme/resolveAppearance";

afterEach(() => {
  cleanup();
  applyResolvedAppearance(resolveAppearance(BUILTIN_THEME));
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
  it("separates palette caches and serializes shared configuration across colors", async () => {
    const base = resolveAppearance(BUILTIN_THEME);
    const firstPalette = mermaidAppearance({ ...base, colors: { ...base.colors, "diagram.primary": "#123456FF" } });
    const secondPalette = mermaidAppearance({ ...base, colors: { ...base.colors, "diagram.primary": "#654321FF" } });
    let variables: { primaryColor: string };
    const releases: Array<() => void> = [];
    const initialize = vi.fn((options: { themeVariables: typeof variables }) => { variables = options.themeVariables; });
    const renderDiagram = vi.fn(async (id: string) => {
      const before = variables.primaryColor;
      await new Promise<void>((done) => releases.push(done));
      expect(variables.primaryColor).toBe(before);
      return { svg: `<svg id="${id}" data-color="${before}" />` };
    });
    resetMermaidRendererForTests({ load: async () => ({ default: { initialize, render: renderDiagram } }) });
    const first = renderMermaidSingleFlight("graph TD;A-->B", "first", firstPalette);
    const second = renderMermaidSingleFlight("graph TD;A-->B", "second", secondPalette);
    await waitFor(() => expect(renderDiagram).toHaveBeenCalledTimes(1));
    expect(initialize).toHaveBeenCalledTimes(1);
    releases[0]();
    await waitFor(() => expect(renderDiagram).toHaveBeenCalledTimes(2));
    releases[1]();
    expect((await first).svg).toContain("#123456");
    expect((await second).svg).toContain("#654321");
    await renderMermaidSingleFlight("graph TD;A-->B", "cached-first", firstPalette);
    expect(renderDiagram).toHaveBeenCalledTimes(2);
  });

  it("rejects stale asynchronous results when the same theme changes color", async () => {
    const base = resolveAppearance(BUILTIN_THEME);
    const releases: Array<() => void> = [];
    const renderDiagram = vi.fn(async (id: string) => {
      const index = releases.length;
      await new Promise<void>((done) => releases.push(done));
      return { svg: `<svg id="${id}" data-generation="${index}" />` };
    });
    resetMermaidRendererForTests({ load: async () => ({ default: { initialize: vi.fn(), render: renderDiagram } }) });
    render(<MarkdownContent content={"```mermaid\ngraph TD;A-->B\n```"} variant="chat" />);
    await waitFor(() => expect(renderDiagram).toHaveBeenCalledTimes(1));
    act(() => applyResolvedAppearance({ ...base, colors: { ...base.colors, "diagram.primary": "#112233FF" }, revision: "same-id-new-colors" }));
    await act(async () => { releases[0](); });
    expect(document.querySelector('[data-generation="0"]')).toBeNull();
    await waitFor(() => expect(renderDiagram).toHaveBeenCalledTimes(2));
    await act(async () => { releases[1](); });
    expect((await screen.findByLabelText("Mermaid 图表")).querySelector("svg")).toHaveAttribute("data-generation", "1");
  });
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
