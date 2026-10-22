import { WeightedLruCache } from "../utils/lruCache";
import { getCurrentAppearance } from "../theme/appearanceRuntime";
import type { ResolvedAppearance } from "../theme/types";

export type MermaidRenderResult = { svg: string; error: string };

type MermaidModule = {
  initialize: (options: Record<string, unknown>) => void;
  render: (id: string, code: string) => Promise<{ svg: string }>;
};

type MermaidLoader = () => Promise<{ default: MermaidModule }>;

const MAX_CACHE_ENTRIES = 32;
const MAX_CACHE_WEIGHT = 4 * 1024 * 1024;

function createCache(maxEntries = MAX_CACHE_ENTRIES, maxWeight = MAX_CACHE_WEIGHT) {
  return new WeightedLruCache<string, MermaidRenderResult>({
    maxEntries,
    maxWeight,
    weigh: (value) => (value.svg.length + value.error.length) * 2,
  });
}

let completed = createCache();
const pending = new Map<string, Promise<MermaidRenderResult>>();
let renderQueue: Promise<unknown> = Promise.resolve();
let modulePromise: Promise<MermaidModule> | null = null;
let loader: MermaidLoader = () => import("mermaid");
let neutralIdSequence = 0;

async function loadMermaid() {
  if (!modulePromise) {
    modulePromise = loader().then(({ default: mermaid }) => mermaid).catch((error) => { modulePromise = null; throw error; });
  }
  return modulePromise;
}

export function mermaidAppearance(appearance: ResolvedAppearance = getCurrentAppearance()) {
  const colors = appearance.colors;
  const background = colors["diagram.background"] || colors["surface.base"];
  // Mermaid's derived palette uses opaque hex colors; composite alpha on its own canvas.
  const opaque = (value: string) => {
    const alpha = parseInt(value.slice(7, 9) || "FF", 16) / 255;
    return `#${[1, 3, 5].map((offset) => Math.round(parseInt(value.slice(offset, offset + 2), 16) * alpha
      + parseInt(background.slice(offset, offset + 2), 16) * (1 - alpha)).toString(16).padStart(2, "0")).join("")}`;
  };
  const color = (key: string, fallback: string) => opaque(colors[key] || colors[fallback]);
  const text = color("diagram.text", "text.primary");
  const primary = color("diagram.primary", "surface.muted");
  const border = color("diagram.primaryBorder", "border.strong");
  const variables = {
    darkMode: appearance.scheme === "dark",
    background: opaque(background),
    textColor: text,
    primaryColor: primary,
    primaryTextColor: text,
    primaryBorderColor: border,
    secondaryColor: color("diagram.secondary", "accent.soft"),
    secondaryTextColor: text,
    tertiaryColor: color("diagram.tertiary", "surface.strong"),
    tertiaryTextColor: text,
    lineColor: color("diagram.line", "text.muted"),
    mainBkg: primary,
    nodeBorder: border,
    edgeLabelBackground: opaque(background),
  };
  return { key: JSON.stringify(variables), variables };
}

type DiagramAppearance = ReturnType<typeof mermaidAppearance>;
function cacheKey(code: string, appearance: DiagramAppearance) { return JSON.stringify([appearance.key, code]); }

function rewriteSvgIds(result: MermaidRenderResult, diagramId: string): MermaidRenderResult {
  if (!result.svg || !diagramId) return result;
  const ids: string[] = [];
  result.svg.replace(/\bid=(['"])([^'"]+)\1/g, (_match, _quote, id: string) => {
    if (!ids.includes(id)) ids.push(id);
    return _match;
  });
  if (ids.length === 0) return result;
  const replacements = new Map(ids.map((id, index) => [id, index === 0 ? diagramId : `${diagramId}-${index}`]));
  let svg = result.svg;
  for (const [source, target] of [...replacements].sort(([left], [right]) => right.length - left.length)) {
    svg = svg.split(`#${source}`).join(`#${target}`);
  }
  svg = svg.replace(/\bid=(['"])([^'"]+)\1/g, (match, quote: string, id: string) => {
    const replacement = replacements.get(id);
    return replacement ? `id=${quote}${replacement}${quote}` : match;
  });
  return { ...result, svg };
}

export function getCachedMermaidRender(code: string, diagramId: string, appearance = mermaidAppearance()) {
  const cached = completed.get(cacheKey(code, appearance));
  return cached ? rewriteSvgIds(cached, diagramId) : undefined;
}

export function renderMermaidSingleFlight(code: string, diagramId: string, appearance = mermaidAppearance()) {
  const key = cacheKey(code, appearance);
  const cached = completed.get(key);
  if (cached) {
    return Promise.resolve(rewriteSvgIds(cached, diagramId));
  }
  const active = pending.get(key);
  if (active) {
    return active.then((result) => rewriteSvgIds(result, diagramId));
  }

  const neutralId = `mermaid-cache-${neutralIdSequence += 1}`;
  // initialize() mutates Mermaid's shared configuration. Keep initialization and render together.
  const task = renderQueue.then(async () => {
      const mermaid = await loadMermaid();
      mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "base", themeVariables: appearance.variables, suppressErrorRendering: true });
      return mermaid.render(neutralId, code);
    })
    .then<MermaidRenderResult>((result) => ({ svg: result.svg, error: "" }))
    .catch<MermaidRenderResult>(() => ({ svg: "", error: "Mermaid 图表渲染失败，已回退为源码。" }))
    .then((result) => {
      completed.set(key, result);
      return result;
    })
    .finally(() => {
      pending.delete(key);
    });
  renderQueue = task;
  pending.set(key, task);
  return task.then((result) => rewriteSvgIds(result, diagramId));
}

export function mermaidRendererDiagnostics() {
  return {
    completedEntries: completed.size,
    completedWeight: completed.weight,
    pendingEntries: pending.size,
  };
}

export function resetMermaidRendererForTests(options?: {
  load?: MermaidLoader;
  maxEntries?: number;
  maxWeight?: number;
}) {
  completed = createCache(options?.maxEntries, options?.maxWeight);
  pending.clear();
  renderQueue = Promise.resolve();
  modulePromise = null;
  neutralIdSequence = 0;
  loader = options?.load || (() => import("mermaid"));
}
