import { WeightedLruCache } from "../utils/lruCache";

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
let initialized = false;
let modulePromise: Promise<MermaidModule> | null = null;
let loader: MermaidLoader = () => import("mermaid");
let neutralIdSequence = 0;

async function loadMermaid() {
  if (!modulePromise) {
    modulePromise = loader().then(({ default: mermaid }) => {
      if (!initialized) {
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "neutral",
          suppressErrorRendering: true,
        });
        initialized = true;
      }
      return mermaid;
    });
  }
  return modulePromise;
}

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

export function getCachedMermaidRender(code: string, diagramId: string) {
  const cached = completed.get(code);
  return cached ? rewriteSvgIds(cached, diagramId) : undefined;
}

export function renderMermaidSingleFlight(code: string, diagramId: string) {
  const cached = completed.get(code);
  if (cached) {
    return Promise.resolve(rewriteSvgIds(cached, diagramId));
  }
  const active = pending.get(code);
  if (active) {
    return active.then((result) => rewriteSvgIds(result, diagramId));
  }

  const neutralId = `mermaid-cache-${neutralIdSequence += 1}`;
  const task = loadMermaid()
    .then((mermaid) => mermaid.render(neutralId, code))
    .then<MermaidRenderResult>((result) => ({ svg: result.svg, error: "" }))
    .catch<MermaidRenderResult>(() => ({ svg: "", error: "Mermaid 图表渲染失败，已回退为源码。" }))
    .then((result) => {
      completed.set(code, result);
      return result;
    })
    .finally(() => {
      pending.delete(code);
    });
  pending.set(code, task);
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
  initialized = false;
  modulePromise = null;
  neutralIdSequence = 0;
  loader = options?.load || (() => import("mermaid"));
}
