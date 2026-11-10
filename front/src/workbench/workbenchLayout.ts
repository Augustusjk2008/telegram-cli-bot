import {
  ACTIVITY_RAIL_WIDTH_PX,
  PANE_RESIZER_SIZE_PX,
  type FocusedWorkbenchPane,
} from "./workbenchTypes";

/**
 * Desktop workbench layout presets.
 *
 * A preset (template) defines fixed slots and their geometry; the user only permutes the four
 * panes among those slots. Sizes belong to slots, so swapping panes keeps the geometry.
 * Layout changes are expressed purely as grid templates and grid placements so that the pane
 * sections never change parent or order in the DOM.
 */

export type WorkbenchPaneId = "sidebar" | "editor" | "terminal" | "chat";
export type LayoutTemplateId = "classic" | "bottomPanel" | "columns" | "sideStack";
/** `x`: top-level items sit side by side (columns); `y`: they are stacked (rows). */
export type LayoutAxis = "x" | "y";
export type RailSide = "start" | "end";

export const WORKBENCH_PANE_IDS: readonly WorkbenchPaneId[] = ["sidebar", "editor", "terminal", "chat"];
export const WORKBENCH_LAYOUT_VERSION = 1;
export const MIN_STORED_LAYOUT_SIZE_PX = 48;
export const MAX_STORED_LAYOUT_SIZE_PX = 4096;

export const PANE_LABELS: Readonly<Record<WorkbenchPaneId, string>> = {
  sidebar: "侧边栏",
  editor: "编辑器",
  terminal: "终端",
  chat: "聊天",
};

/** Pane minimum sizes apply wherever a pane sits. The editor width reproduces the old center minimum. */
export const PANE_MIN_SIZE: Readonly<Record<WorkbenchPaneId, { width: number; height: number }>> = {
  sidebar: { width: 220, height: 160 },
  editor: { width: 480, height: 220 },
  terminal: { width: 320, height: 160 },
  chat: { width: 260, height: 240 },
};

export type LayoutTemplateGroup = {
  key: string;
  /** Group members are arranged on the axis opposite to the template axis. */
  members: readonly string[];
  fillPriority: readonly string[];
};

export type LayoutDiagramCell = { column: string; row: string };

export type LayoutTemplate = {
  id: LayoutTemplateId;
  name: string;
  description: string;
  axis: LayoutAxis;
  /** Top-level items in order; at most one of them is the group key. */
  items: readonly string[];
  group?: LayoutTemplateGroup;
  fillPriority: readonly string[];
  /** Slot ids (top-level slots and group members) in reading order. */
  slots: readonly string[];
  defaultSlots: Readonly<Record<string, WorkbenchPaneId>>;
  /** Default sizes in px for every item and group member along its own axis. */
  defaultSizes: Readonly<Record<string, number>>;
  /** Static fr-based diagram for the layout menu. */
  diagram: {
    columns: string;
    rows: string;
    cells: Readonly<Record<string, LayoutDiagramCell>>;
  };
};

function defineTemplate(template: Omit<LayoutTemplate, "slots">): LayoutTemplate {
  const group = template.group;
  return {
    ...template,
    slots: template.items.flatMap((item) => (group && item === group.key ? [...group.members] : [item])),
  };
}

export const WORKBENCH_LAYOUT_TEMPLATES: readonly LayoutTemplate[] = [
  defineTemplate({
    id: "classic",
    name: "经典",
    description: "侧边栏 | 编辑器/终端 | 聊天",
    axis: "x",
    items: ["left", "center", "right"],
    group: { key: "center", members: ["centerTop", "centerBottom"], fillPriority: ["centerBottom", "centerTop"] },
    fillPriority: ["center", "right", "left"],
    defaultSlots: { left: "sidebar", centerTop: "editor", centerBottom: "terminal", right: "chat" },
    defaultSizes: { left: 320, center: 640, right: 384, centerTop: 420, centerBottom: 280 },
    diagram: {
      columns: "1fr 2fr 1fr",
      rows: "1fr 1fr",
      cells: {
        left: { column: "1", row: "1 / span 2" },
        centerTop: { column: "2", row: "1" },
        centerBottom: { column: "2", row: "2" },
        right: { column: "3", row: "1 / span 2" },
      },
    },
  }),
  defineTemplate({
    id: "bottomPanel",
    name: "底部通栏",
    description: "终端横跨底部",
    axis: "y",
    items: ["top", "bottom"],
    group: { key: "top", members: ["left", "center", "right"], fillPriority: ["center", "right", "left"] },
    fillPriority: ["top", "bottom"],
    defaultSlots: { left: "sidebar", center: "editor", right: "chat", bottom: "terminal" },
    defaultSizes: { top: 560, bottom: 280, left: 320, center: 640, right: 384 },
    diagram: {
      columns: "1fr 2fr 1fr",
      rows: "2fr 1fr",
      cells: {
        left: { column: "1", row: "1" },
        center: { column: "2", row: "1" },
        right: { column: "3", row: "1" },
        bottom: { column: "1 / span 3", row: "2" },
      },
    },
  }),
  defineTemplate({
    id: "columns",
    name: "四列并排",
    description: "四个窗口并排，适合宽屏",
    axis: "x",
    items: ["col1", "col2", "col3", "col4"],
    fillPriority: ["col2", "col3", "col4", "col1"],
    defaultSlots: { col1: "sidebar", col2: "editor", col3: "terminal", col4: "chat" },
    defaultSizes: { col1: 260, col2: 560, col3: 420, col4: 360 },
    diagram: {
      columns: "1fr 2fr 1.5fr 1fr",
      rows: "1fr",
      cells: {
        col1: { column: "1", row: "1" },
        col2: { column: "2", row: "1" },
        col3: { column: "3", row: "1" },
        col4: { column: "4", row: "1" },
      },
    },
  }),
  defineTemplate({
    id: "sideStack",
    name: "右侧堆叠",
    description: "对话居中，编辑器与终端在右侧",
    axis: "x",
    items: ["left", "center", "right"],
    group: { key: "right", members: ["rightTop", "rightBottom"], fillPriority: ["rightBottom", "rightTop"] },
    fillPriority: ["center", "right", "left"],
    defaultSlots: { left: "sidebar", center: "chat", rightTop: "editor", rightBottom: "terminal" },
    defaultSizes: { left: 300, center: 640, right: 560, rightTop: 420, rightBottom: 280 },
    diagram: {
      columns: "1fr 2fr 1.5fr",
      rows: "1fr 1fr",
      cells: {
        left: { column: "1", row: "1 / span 2" },
        center: { column: "2", row: "1 / span 2" },
        rightTop: { column: "3", row: "1" },
        rightBottom: { column: "3", row: "2" },
      },
    },
  }),
];

const TEMPLATES_BY_ID = new Map<string, LayoutTemplate>(
  WORKBENCH_LAYOUT_TEMPLATES.map((template) => [template.id, template]),
);

export type TemplateLayoutState = {
  /** Slot id → pane id; always a permutation of the four panes. */
  slots: Readonly<Record<string, WorkbenchPaneId>>;
  /** Only customized sizes; missing keys fall back to the template defaults. */
  sizes: Readonly<Record<string, number>>;
};

export type WorkbenchLayoutState = {
  activeTemplate: LayoutTemplateId;
  /** Only presets the user has customized; the others use their defaults. */
  templates: Partial<Record<LayoutTemplateId, TemplateLayoutState>>;
};

export const DEFAULT_WORKBENCH_LAYOUT: WorkbenchLayoutState = {
  activeTemplate: "classic",
  templates: {},
};

export type SerializedWorkbenchLayout = {
  /** Legacy mirrors of the classic preset so older frontends can still read the key. */
  sidebarWidthPx: number;
  chatWidthPx: number;
  editorHeightPx: number;
  layoutVersion: typeof WORKBENCH_LAYOUT_VERSION;
  activeLayout: LayoutTemplateId;
  layouts: Partial<Record<LayoutTemplateId, { slots: Record<string, WorkbenchPaneId>; sizes: Record<string, number> }>>;
};

export type ResolvedPanePlacement = {
  slot: string;
  /** The pane takes space in the grid. */
  shown: boolean;
  /** The pane section itself is visible (equals the normal-mode `shown`, also while editing). */
  displayed: boolean;
  rail: boolean;
  railSide: RailSide;
  gridColumn: string;
  gridRow: string;
};

export type ResolvedResizerEdge = {
  key: string;
  kind: "fixed" | "fill";
  size: number;
  min: number;
};

export type ResolvedLayoutResizer = {
  id: string;
  templateId: LayoutTemplateId;
  axis: LayoutAxis;
  gridColumn: string;
  gridRow: string;
  ariaLabel: string;
  before: ResolvedResizerEdge;
  after: ResolvedResizerEdge;
  minDelta: number;
  maxDelta: number;
};

export type ResolvedWorkbenchLayout = {
  templateId: LayoutTemplateId;
  gridTemplateColumns: string;
  gridTemplateRows: string;
  panes: Record<WorkbenchPaneId, ResolvedPanePlacement>;
  resizers: ResolvedLayoutResizer[];
  hasShownPane: boolean;
};

export type ResolveWorkbenchLayoutInput = {
  layout: WorkbenchLayoutState;
  available: Readonly<Record<WorkbenchPaneId, boolean>>;
  collapsed: Readonly<Record<WorkbenchPaneId, boolean>>;
  focusedPane: FocusedWorkbenchPane;
  /** Rearrange mode: every slot takes space and nothing is a rail. */
  editing: boolean;
  /** Content box of the grid container. */
  container: { width: number; height: number };
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function isLayoutTemplateId(value: unknown): value is LayoutTemplateId {
  return typeof value === "string" && TEMPLATES_BY_ID.has(value);
}

export function isWorkbenchPaneId(value: unknown): value is WorkbenchPaneId {
  return typeof value === "string" && (WORKBENCH_PANE_IDS as readonly string[]).includes(value);
}

export function getLayoutTemplate(id: LayoutTemplateId): LayoutTemplate {
  return TEMPLATES_BY_ID.get(id) ?? WORKBENCH_LAYOUT_TEMPLATES[0];
}

/** Returns the stored arrangement merged over the template defaults. */
export function getTemplateLayout(layout: WorkbenchLayoutState, id: LayoutTemplateId): TemplateLayoutState {
  const template = getLayoutTemplate(id);
  const stored = layout.templates[id];
  return {
    slots: stored?.slots ?? template.defaultSlots,
    sizes: { ...template.defaultSizes, ...stored?.sizes },
  };
}

export function findPaneSlot(slots: Readonly<Record<string, WorkbenchPaneId>>, pane: WorkbenchPaneId): string {
  return Object.keys(slots).find((slot) => slots[slot] === pane) ?? "";
}

/** A collapsed sidebar becomes a 48px rail only in a slot that has its own column. */
export function isRailEligible(template: LayoutTemplate, slot: string): boolean {
  const isGroupMember = Boolean(template.group?.members.includes(slot));
  return template.axis === "x" ? !isGroupMember && template.items.includes(slot) : isGroupMember;
}

export function railSideFor(template: LayoutTemplate, slot: string): RailSide {
  if (!isRailEligible(template, slot)) {
    return "start";
  }
  const row = template.axis === "x" ? template.items : template.group?.members ?? [];
  return row[row.length - 1] === slot ? "end" : "start";
}

function normalizeStoredSize(value: unknown): number | undefined {
  return typeof value === "number"
    && Number.isFinite(value)
    && value >= MIN_STORED_LAYOUT_SIZE_PX
    && value <= MAX_STORED_LAYOUT_SIZE_PX
    ? value
    : undefined;
}

function normalizeTemplateEntry(template: LayoutTemplate, raw: unknown): TemplateLayoutState | undefined {
  if (!isRecord(raw) || !isRecord(raw.slots)) {
    return undefined;
  }
  const rawSlots = raw.slots;
  const slots: Record<string, WorkbenchPaneId> = {};
  for (const slot of template.slots) {
    const pane = rawSlots[slot];
    if (!isWorkbenchPaneId(pane)) {
      return undefined;
    }
    slots[slot] = pane;
  }
  if (new Set(Object.values(slots)).size !== WORKBENCH_PANE_IDS.length) {
    return undefined;
  }
  const sizes: Record<string, number> = {};
  if (isRecord(raw.sizes)) {
    for (const key of Object.keys(template.defaultSizes)) {
      const size = normalizeStoredSize(raw.sizes[key]);
      if (size !== undefined) {
        sizes[key] = size;
      }
    }
  }
  return { slots, sizes };
}

function seedClassicFromLegacy(raw: Record<string, unknown>): TemplateLayoutState | undefined {
  const classic = getLayoutTemplate("classic");
  const legacySizes: Record<string, number | undefined> = {
    left: normalizeStoredSize(raw.sidebarWidthPx) ?? normalizeStoredSize(raw.filesWidthPx),
    right: normalizeStoredSize(raw.chatWidthPx),
    centerTop: normalizeStoredSize(raw.editorHeightPx),
  };
  const sizes: Record<string, number> = {};
  for (const [key, size] of Object.entries(legacySizes)) {
    // Values equal to the defaults add nothing; skipping them keeps `layouts` limited to customized presets.
    if (size !== undefined && size !== classic.defaultSizes[key]) {
      sizes[key] = size;
    }
  }
  return Object.keys(sizes).length > 0 ? { slots: { ...classic.defaultSlots }, sizes } : undefined;
}

/** Reads the layout fields (and the legacy classic sizes) from a stored pane-state payload. */
export function normalizeWorkbenchLayout(raw: unknown): WorkbenchLayoutState {
  if (!isRecord(raw)) {
    return DEFAULT_WORKBENCH_LAYOUT;
  }
  const rawLayouts = isRecord(raw.layouts) ? raw.layouts : {};
  const templates: Partial<Record<LayoutTemplateId, TemplateLayoutState>> = {};
  for (const template of WORKBENCH_LAYOUT_TEMPLATES) {
    const entry = normalizeTemplateEntry(template, rawLayouts[template.id]);
    if (entry) {
      templates[template.id] = entry;
    }
  }
  if (!templates.classic) {
    const seeded = seedClassicFromLegacy(raw);
    if (seeded) {
      templates.classic = seeded;
    }
  }
  return {
    activeTemplate: isLayoutTemplateId(raw.activeLayout) ? raw.activeLayout : "classic",
    templates,
  };
}

export function serializeWorkbenchLayout(layout: WorkbenchLayoutState): SerializedWorkbenchLayout {
  const classic = getTemplateLayout(layout, "classic");
  const layouts: SerializedWorkbenchLayout["layouts"] = {};
  for (const template of WORKBENCH_LAYOUT_TEMPLATES) {
    const entry = layout.templates[template.id];
    if (entry) {
      layouts[template.id] = { slots: { ...entry.slots }, sizes: { ...entry.sizes } };
    }
  }
  return {
    sidebarWidthPx: classic.sizes.left,
    chatWidthPx: classic.sizes.right,
    editorHeightPx: classic.sizes.centerTop,
    layoutVersion: WORKBENCH_LAYOUT_VERSION,
    activeLayout: layout.activeTemplate,
    layouts,
  };
}

type AxisEntry = {
  key: string;
  shown: boolean;
  rail: boolean;
  min: number;
  stored: number;
  label: string;
};

type AxisSolution = {
  /** Item and gap tracks interleaved: `[i0, g0, i1, …]`. */
  tracks: string[];
  fill: AxisEntry | null;
  fillSize: number;
  fixedSizes: Map<string, number>;
  /** Indices `j` of the gap tracks (after item `j`) that are open (8px). */
  openGaps: number[];
};

function solveAxis(
  entries: AxisEntry[],
  fillPriority: readonly string[],
  containerSize: number,
  options: { spanningFallback: boolean },
): AxisSolution {
  const visible = entries.filter((entry) => entry.shown);
  const fill = fillPriority
    .map((key) => entries.find((entry) => entry.key === key))
    .find((entry): entry is AxisEntry => Boolean(entry?.shown && !entry.rail)) ?? null;
  const gapCount = Math.max(0, visible.length - 1);

  const fixedSizes = new Map<string, number>();
  for (const entry of visible) {
    if (entry !== fill) {
      fixedSizes.set(entry.key, entry.rail ? ACTIVITY_RAIL_WIDTH_PX : Math.round(Math.max(entry.min, entry.stored)));
    }
  }

  // Shrink fixed items from the last one, each down to its minimum; any rest is absorbed by the fill track.
  const budget = containerSize - PANE_RESIZER_SIZE_PX * gapCount - (fill ? fill.min : 0);
  let overflow = [...fixedSizes.values()].reduce((total, size) => total + size, 0) - budget;
  for (let index = visible.length - 1; index >= 0 && overflow > 0; index -= 1) {
    const entry = visible[index];
    if (entry === fill || entry.rail) {
      continue;
    }
    const size = fixedSizes.get(entry.key) ?? 0;
    const shrink = Math.min(Math.ceil(overflow), size - entry.min);
    if (shrink > 0) {
      fixedSizes.set(entry.key, size - shrink);
      overflow -= shrink;
    }
  }

  const fixedTotal = [...fixedSizes.values()].reduce((total, size) => total + size, 0);
  const fillSize = fill ? Math.max(0, containerSize - PANE_RESIZER_SIZE_PX * gapCount - fixedTotal) : 0;
  const lastVisibleIndex = entries.reduce((last, entry, index) => (entry.shown ? index : last), -1);
  const openGaps: number[] = [];
  const tracks: string[] = [];
  entries.forEach((entry, index) => {
    if (index > 0) {
      const gapIndex = index - 1;
      const open = entries[gapIndex].shown && gapIndex < lastVisibleIndex;
      if (open) {
        openGaps.push(gapIndex);
      }
      tracks.push(open ? `${PANE_RESIZER_SIZE_PX}px` : "0px");
    }
    tracks.push(!entry.shown ? "0px" : entry === fill ? "minmax(0, 1fr)" : `${fixedSizes.get(entry.key)}px`);
  });

  if (options.spanningFallback) {
    if (visible.length === 0) {
      // Keep items that span this axis at full size when no member takes space.
      tracks[0] = "minmax(0, 1fr)";
    } else if (!fill) {
      // Only rails take space: give the remaining room to an empty track next to them.
      const firstVisibleIndex = entries.findIndex((entry) => entry.shown);
      const spacerIndex = entries.findIndex((entry, index) => index > lastVisibleIndex && !entry.shown);
      const fallbackIndex = spacerIndex >= 0
        ? spacerIndex
        : entries.reduce((last, entry, index) => (!entry.shown && index < firstVisibleIndex ? index : last), -1);
      if (fallbackIndex >= 0) {
        tracks[fallbackIndex * 2] = "minmax(0, 1fr)";
      }
    }
  }

  return { tracks, fill, fillSize, fixedSizes, openGaps };
}

function resizerEdge(entry: AxisEntry, solution: AxisSolution): ResolvedResizerEdge {
  const isFill = entry === solution.fill;
  return {
    key: entry.key,
    kind: isFill ? "fill" : "fixed",
    size: isFill ? solution.fillSize : solution.fixedSizes.get(entry.key) ?? 0,
    min: entry.min,
  };
}

function buildAxisResizers(
  templateId: LayoutTemplateId,
  axis: LayoutAxis,
  entries: AxisEntry[],
  solution: AxisSolution,
  placeGap: (gapIndex: number) => { gridColumn: string; gridRow: string },
): ResolvedLayoutResizer[] {
  const dimension = axis === "x" ? "宽度" : "高度";
  const resizers: ResolvedLayoutResizer[] = [];
  for (const gapIndex of solution.openGaps) {
    const beforeEntry = entries[gapIndex];
    const afterEntry = entries.slice(gapIndex + 1).find((entry) => entry.shown);
    if (!afterEntry || beforeEntry.rail || afterEntry.rail) {
      continue;
    }
    const before = resizerEdge(beforeEntry, solution);
    const after = resizerEdge(afterEntry, solution);
    let minDelta: number;
    let maxDelta: number;
    let ariaLabel: string;
    if (before.kind === "fixed" && after.kind === "fill") {
      minDelta = before.min - before.size;
      maxDelta = Math.max(0, after.size - after.min);
      ariaLabel = `调整${beforeEntry.label}${dimension}`;
    } else if (before.kind === "fill" && after.kind === "fixed") {
      minDelta = Math.min(0, -(before.size - before.min));
      maxDelta = after.size - after.min;
      ariaLabel = `调整${afterEntry.label}${dimension}`;
    } else {
      minDelta = before.min - before.size;
      maxDelta = after.size - after.min;
      ariaLabel = `调整${beforeEntry.label}与${afterEntry.label}${dimension}`;
    }
    resizers.push({
      id: `${axis}:${before.key}|${after.key}`,
      templateId,
      axis,
      ...placeGap(gapIndex),
      ariaLabel,
      before,
      after,
      minDelta,
      maxDelta,
    });
  }
  return resizers;
}

function computeVisibility(
  template: LayoutTemplate,
  paneSlots: Readonly<Record<WorkbenchPaneId, string>>,
  available: Readonly<Record<WorkbenchPaneId, boolean>>,
  collapsed: Readonly<Record<WorkbenchPaneId, boolean>>,
  focusedPane: FocusedWorkbenchPane,
): Record<WorkbenchPaneId, { shown: boolean; rail: boolean }> {
  const focus = focusedPane && available[focusedPane] ? focusedPane : null;
  const result = {} as Record<WorkbenchPaneId, { shown: boolean; rail: boolean }>;
  for (const pane of WORKBENCH_PANE_IDS) {
    if (focus) {
      result[pane] = { shown: pane === focus, rail: false };
    } else if (available[pane] && !collapsed[pane]) {
      result[pane] = { shown: true, rail: false };
    } else if (pane === "sidebar" && available.sidebar && isRailEligible(template, paneSlots.sidebar)) {
      result[pane] = { shown: true, rail: true };
    } else {
      result[pane] = { shown: false, rail: false };
    }
  }
  return result;
}

export function resolveWorkbenchLayout(input: ResolveWorkbenchLayoutInput): ResolvedWorkbenchLayout {
  const template = getLayoutTemplate(input.layout.activeTemplate);
  const { slots, sizes } = getTemplateLayout(input.layout, template.id);
  const paneSlots = {} as Record<WorkbenchPaneId, string>;
  for (const pane of WORKBENCH_PANE_IDS) {
    paneSlots[pane] = findPaneSlot(slots, pane);
  }

  // While editing, focus is ignored: `displayed` reports what normal mode would display.
  const normal = computeVisibility(template, paneSlots, input.available, input.collapsed, input.editing ? null : input.focusedPane);
  const visibility = input.editing
    ? Object.fromEntries(WORKBENCH_PANE_IDS.map((pane) => [pane, { shown: true, rail: false }])) as typeof normal
    : normal;

  const crossAxis: LayoutAxis = template.axis === "x" ? "y" : "x";
  const mainDimension = template.axis === "x" ? "width" : "height";
  const crossDimension = template.axis === "x" ? "height" : "width";
  const mainContainer = template.axis === "x" ? input.container.width : input.container.height;
  const crossContainer = template.axis === "x" ? input.container.height : input.container.width;
  const group = template.group;

  const slotEntry = (slot: string, dimension: "width" | "height"): AxisEntry => {
    const pane = slots[slot];
    const { shown, rail } = visibility[pane];
    return {
      key: slot,
      shown,
      rail,
      min: rail ? ACTIVITY_RAIL_WIDTH_PX : PANE_MIN_SIZE[pane][dimension],
      stored: sizes[slot] ?? 0,
      label: PANE_LABELS[pane],
    };
  };

  const mainEntries = template.items.map((item): AxisEntry => {
    if (!group || item !== group.key) {
      return slotEntry(item, mainDimension);
    }
    const shownMembers = group.members.map((member) => slots[member]).filter((pane) => visibility[pane].shown);
    return {
      key: item,
      shown: shownMembers.length > 0,
      rail: false,
      min: Math.max(0, ...shownMembers.map((pane) => PANE_MIN_SIZE[pane][mainDimension])),
      stored: sizes[item] ?? 0,
      label: shownMembers.map((pane) => PANE_LABELS[pane]).join("/"),
    };
  });
  const main = solveAxis(mainEntries, template.fillPriority, mainContainer, { spanningFallback: false });

  const groupIndex = group ? template.items.indexOf(group.key) : -1;
  const crossEntries = group ? group.members.map((member) => slotEntry(member, crossDimension)) : [];
  const cross = group
    ? solveAxis(crossEntries, group.fillPriority, crossContainer, { spanningFallback: true })
    : null;

  const place = (mainTrack: string, crossTrack: string) => (
    template.axis === "x"
      ? { gridColumn: mainTrack, gridRow: crossTrack }
      : { gridColumn: crossTrack, gridRow: mainTrack }
  );

  const panes = {} as Record<WorkbenchPaneId, ResolvedPanePlacement>;
  template.items.forEach((item, itemIndex) => {
    const mainTrack = String(itemIndex * 2 + 1);
    const itemSlots = group && item === group.key ? group.members : [item];
    itemSlots.forEach((slot, memberIndex) => {
      const pane = slots[slot];
      const crossTrack = group && item === group.key ? String(memberIndex * 2 + 1) : "1 / -1";
      panes[pane] = {
        slot,
        shown: visibility[pane].shown,
        displayed: normal[pane].shown,
        rail: visibility[pane].rail,
        railSide: railSideFor(template, slot),
        ...place(mainTrack, crossTrack),
      };
    });
  });

  const resizers = input.editing
    ? []
    : [
        ...buildAxisResizers(template.id, template.axis, mainEntries, main, (gapIndex) => place(String(gapIndex * 2 + 2), "1 / -1")),
        ...(cross
          ? buildAxisResizers(template.id, crossAxis, crossEntries, cross, (gapIndex) => place(String(groupIndex * 2 + 1), String(gapIndex * 2 + 2)))
          : []),
      ];

  const crossTracks = cross ? cross.tracks : ["minmax(0, 1fr)"];
  return {
    templateId: template.id,
    gridTemplateColumns: (template.axis === "x" ? main.tracks : crossTracks).join(" "),
    gridTemplateRows: (template.axis === "x" ? crossTracks : main.tracks).join(" "),
    panes,
    resizers,
    hasShownPane: WORKBENCH_PANE_IDS.some((pane) => visibility[pane].shown),
  };
}

function withTemplateEntry(
  layout: WorkbenchLayoutState,
  id: LayoutTemplateId,
  update: (entry: TemplateLayoutState) => TemplateLayoutState,
): WorkbenchLayoutState {
  const template = getLayoutTemplate(id);
  const current = layout.templates[id] ?? { slots: { ...template.defaultSlots }, sizes: {} };
  return {
    ...layout,
    templates: { ...layout.templates, [id]: update(current) },
  };
}

/** Applies a divider drag. `resizer` must be the descriptor captured at drag start; `delta` is measured from there. */
export function applyLayoutResize(
  layout: WorkbenchLayoutState,
  resizer: ResolvedLayoutResizer,
  delta: number,
): WorkbenchLayoutState {
  const clamped = Math.min(resizer.maxDelta, Math.max(resizer.minDelta, delta));
  const updates: Record<string, number> = {};
  if (resizer.before.kind === "fixed") {
    updates[resizer.before.key] = Math.round(resizer.before.size + clamped);
  }
  if (resizer.after.kind === "fixed") {
    updates[resizer.after.key] = Math.round(resizer.after.size - clamped);
  }
  const stored = layout.templates[resizer.templateId];
  if (stored && Object.entries(updates).every(([key, size]) => stored.sizes[key] === size)) {
    return layout;
  }
  return withTemplateEntry(layout, resizer.templateId, (entry) => ({
    slots: entry.slots,
    sizes: { ...entry.sizes, ...updates },
  }));
}

/** Exchanges the slots of two panes in the active preset; sizes stay with the slots. */
export function swapLayoutPanes(layout: WorkbenchLayoutState, a: WorkbenchPaneId, b: WorkbenchPaneId): WorkbenchLayoutState {
  if (a === b) {
    return layout;
  }
  return withTemplateEntry(layout, layout.activeTemplate, (entry) => {
    const slotA = findPaneSlot(entry.slots, a);
    const slotB = findPaneSlot(entry.slots, b);
    if (!slotA || !slotB) {
      return entry;
    }
    return {
      slots: { ...entry.slots, [slotA]: b, [slotB]: a },
      sizes: entry.sizes,
    };
  });
}

export function selectLayoutTemplate(layout: WorkbenchLayoutState, id: LayoutTemplateId): WorkbenchLayoutState {
  return layout.activeTemplate === id || !isLayoutTemplateId(id) ? layout : { ...layout, activeTemplate: id };
}

/** Restores the active preset's default arrangement and sizes. */
export function resetLayoutTemplate(layout: WorkbenchLayoutState): WorkbenchLayoutState {
  if (!layout.templates[layout.activeTemplate]) {
    return layout;
  }
  const templates = { ...layout.templates };
  delete templates[layout.activeTemplate];
  return { ...layout, templates };
}
