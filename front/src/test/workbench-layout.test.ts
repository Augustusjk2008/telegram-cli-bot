import { describe, expect, test } from "vitest";
import {
  applyLayoutResize,
  DEFAULT_WORKBENCH_LAYOUT,
  getTemplateLayout,
  normalizeWorkbenchLayout,
  resetLayoutTemplate,
  resolveWorkbenchLayout,
  selectLayoutTemplate,
  serializeWorkbenchLayout,
  swapLayoutPanes,
  WORKBENCH_PANE_IDS,
  type LayoutTemplateId,
  type ResolveWorkbenchLayoutInput,
  type WorkbenchLayoutState,
  type WorkbenchPaneId,
} from "../workbench/workbenchLayout";
import { DEFAULT_DESKTOP_PANE_STATE } from "../workbench/workbenchTypes";

const ALL_AVAILABLE = { sidebar: true, editor: true, terminal: true, chat: true };
const NONE_COLLAPSED = { sidebar: false, editor: false, terminal: false, chat: false };

function layoutFor(
  activeTemplate: LayoutTemplateId,
  entry?: { slots?: Record<string, WorkbenchPaneId>; sizes?: Record<string, number> },
): WorkbenchLayoutState {
  if (!entry) {
    return { activeTemplate, templates: {} };
  }
  const defaults = getTemplateLayout(DEFAULT_WORKBENCH_LAYOUT, activeTemplate);
  return {
    activeTemplate,
    templates: { [activeTemplate]: { slots: entry.slots ?? defaults.slots, sizes: entry.sizes ?? {} } },
  };
}

function resolve(input: Partial<ResolveWorkbenchLayoutInput> = {}) {
  return resolveWorkbenchLayout({
    layout: DEFAULT_WORKBENCH_LAYOUT,
    available: ALL_AVAILABLE,
    collapsed: NONE_COLLAPSED,
    focusedPane: null,
    editing: false,
    container: { width: 1440, height: 900 },
    ...input,
  });
}

function placements(resolved: ReturnType<typeof resolve>) {
  return Object.fromEntries(
    WORKBENCH_PANE_IDS.map((pane) => [pane, `${resolved.panes[pane].gridColumn}/${resolved.panes[pane].gridRow}`]),
  );
}

describe("resolveWorkbenchLayout", () => {
  test("classic defaults reproduce today's workbench", () => {
    const resolved = resolve();

    expect(resolved.templateId).toBe("classic");
    expect(resolved.gridTemplateColumns).toBe("320px 8px minmax(0, 1fr) 8px 384px");
    expect(resolved.gridTemplateRows).toBe("420px 8px minmax(0, 1fr)");
    expect(placements(resolved)).toEqual({
      sidebar: "1/1 / -1",
      editor: "3/1",
      terminal: "3/3",
      chat: "5/1 / -1",
    });
    expect(resolved.resizers.map(({ id, ariaLabel, axis, gridColumn, gridRow }) => ({ id, ariaLabel, axis, gridColumn, gridRow }))).toEqual([
      { id: "x:left|center", ariaLabel: "调整侧边栏宽度", axis: "x", gridColumn: "2", gridRow: "1 / -1" },
      { id: "x:center|right", ariaLabel: "调整聊天宽度", axis: "x", gridColumn: "4", gridRow: "1 / -1" },
      { id: "y:centerTop|centerBottom", ariaLabel: "调整编辑器高度", axis: "y", gridColumn: "3", gridRow: "2" },
    ]);
    expect(resolved.hasShownPane).toBe(true);
  });

  test.each([
    {
      name: "bottomPanel default",
      input: { layout: layoutFor("bottomPanel") },
      columns: "320px 8px minmax(0, 1fr) 8px 384px",
      rows: "minmax(0, 1fr) 8px 280px",
      placements: { sidebar: "1/1", editor: "3/1", terminal: "1 / -1/3", chat: "5/1" },
      resizers: ["y:top|bottom 调整终端高度", "x:left|center 调整侧边栏宽度", "x:center|right 调整聊天宽度"],
    },
    {
      name: "columns default (104px overflow: col4 360→260, col3 420→416)",
      input: { layout: layoutFor("columns") },
      columns: "260px 8px minmax(0, 1fr) 8px 416px 8px 260px",
      rows: "minmax(0, 1fr)",
      placements: { sidebar: "1/1 / -1", editor: "3/1 / -1", terminal: "5/1 / -1", chat: "7/1 / -1" },
      resizers: ["x:col1|col2 调整侧边栏宽度", "x:col2|col3 调整终端宽度", "x:col3|col4 调整终端与聊天宽度"],
    },
    {
      name: "sideStack default",
      input: { layout: layoutFor("sideStack") },
      columns: "300px 8px minmax(0, 1fr) 8px 560px",
      rows: "420px 8px minmax(0, 1fr)",
      placements: { sidebar: "1/1 / -1", editor: "5/1", terminal: "5/3", chat: "3/1 / -1" },
      resizers: ["x:left|center 调整侧边栏宽度", "x:center|right 调整编辑器/终端宽度", "y:rightTop|rightBottom 调整编辑器高度"],
    },
    {
      name: "classic, chat collapsed",
      input: { collapsed: { ...NONE_COLLAPSED, chat: true } },
      columns: "320px 8px minmax(0, 1fr) 0px 0px",
      rows: "420px 8px minmax(0, 1fr)",
      resizers: ["x:left|center 调整侧边栏宽度", "y:centerTop|centerBottom 调整编辑器高度"],
    },
    {
      name: "classic, editor and terminal collapsed (chat fills)",
      input: { collapsed: { ...NONE_COLLAPSED, editor: true, terminal: true } },
      columns: "320px 8px 0px 0px minmax(0, 1fr)",
      rows: "minmax(0, 1fr) 0px 0px",
      resizers: ["x:left|right 调整侧边栏宽度"],
    },
    {
      name: "classic, sidebar collapsed (no resizer next to the rail)",
      input: { collapsed: { ...NONE_COLLAPSED, sidebar: true } },
      columns: "48px 8px minmax(0, 1fr) 8px 384px",
      rows: "420px 8px minmax(0, 1fr)",
      resizers: ["x:center|right 调整聊天宽度", "y:centerTop|centerBottom 调整编辑器高度"],
    },
    {
      name: "classic, focus on terminal",
      input: { focusedPane: "terminal" as const },
      columns: "0px 0px minmax(0, 1fr) 0px 0px",
      rows: "0px 0px minmax(0, 1fr)",
      resizers: [],
    },
    {
      name: "classic, focus on sidebar",
      input: { focusedPane: "sidebar" as const },
      columns: "minmax(0, 1fr) 0px 0px 0px 0px",
      rows: "minmax(0, 1fr) 0px 0px",
      resizers: [],
    },
    {
      name: "classic, structure-only",
      input: { available: { ...ALL_AVAILABLE, editor: false, terminal: false } },
      columns: "320px 8px 0px 0px minmax(0, 1fr)",
      rows: "minmax(0, 1fr) 0px 0px",
      resizers: ["x:left|right 调整侧边栏宽度"],
    },
    {
      name: "classic, focus on an unavailable pane is ignored",
      input: { available: { ...ALL_AVAILABLE, editor: false, terminal: false }, focusedPane: "editor" as const },
      columns: "320px 8px 0px 0px minmax(0, 1fr)",
      rows: "minmax(0, 1fr) 0px 0px",
      resizers: ["x:left|right 调整侧边栏宽度"],
    },
    {
      name: "classic, only the rail left",
      input: { collapsed: { sidebar: true, editor: true, terminal: true, chat: true } },
      columns: "48px 0px 0px 0px 0px",
      rows: "minmax(0, 1fr) 0px 0px",
      resizers: [],
    },
    {
      name: "classic, sidebar↔editor swapped, sidebar collapsed (editor minimum applies in left)",
      input: {
        layout: layoutFor("classic", { slots: { left: "editor", centerTop: "sidebar", centerBottom: "terminal", right: "chat" } }),
        collapsed: { ...NONE_COLLAPSED, sidebar: true },
      },
      columns: "480px 8px minmax(0, 1fr) 8px 384px",
      rows: "0px 0px minmax(0, 1fr)",
      resizers: ["x:left|center 调整编辑器宽度", "x:center|right 调整聊天宽度"],
    },
    {
      name: "classic at width 1100 with stored left 320 / right 700 (chat shrinks first)",
      input: {
        layout: layoutFor("classic", { sizes: { left: 320, right: 700 } }),
        container: { width: 1100, height: 900 },
      },
      columns: "320px 8px minmax(0, 1fr) 8px 284px",
      rows: "420px 8px minmax(0, 1fr)",
    },
    {
      name: "bottomPanel with only the sidebar rail in the top row keeps the spanning terminal full width",
      input: {
        layout: layoutFor("bottomPanel"),
        collapsed: { sidebar: true, editor: true, terminal: false, chat: true },
      },
      columns: "48px 0px minmax(0, 1fr) 0px 0px",
      rows: "minmax(0, 1fr) 8px 280px",
      resizers: ["y:top|bottom 调整终端高度"],
    },
  ])("$name", ({ input, columns, rows, placements: expectedPlacements, resizers }) => {
    const resolved = resolve(input);

    expect(resolved.gridTemplateColumns).toBe(columns);
    expect(resolved.gridTemplateRows).toBe(rows);
    if (expectedPlacements) {
      expect(placements(resolved)).toEqual(expectedPlacements);
    }
    if (resizers) {
      expect(resolved.resizers.map((resizer) => `${resizer.id} ${resizer.ariaLabel}`)).toEqual(resizers);
    }
  });

  test("a collapsed sidebar is a rail only in a slot with its own column, drawn at the right edge when right-most", () => {
    const rightRail = resolve({
      layout: layoutFor("classic", { slots: { left: "chat", centerTop: "editor", centerBottom: "terminal", right: "sidebar" } }),
      collapsed: { ...NONE_COLLAPSED, sidebar: true },
    });
    expect(rightRail.panes.sidebar).toMatchObject({ slot: "right", shown: true, rail: true, railSide: "end" });
    expect(rightRail.gridTemplateColumns).toBe("320px 8px minmax(0, 1fr) 8px 48px");

    const bottomPanelRight = resolve({
      layout: layoutFor("bottomPanel", { slots: { left: "chat", center: "editor", right: "sidebar", bottom: "terminal" } }),
      collapsed: { ...NONE_COLLAPSED, sidebar: true },
    });
    expect(bottomPanelRight.panes.sidebar).toMatchObject({ rail: true, railSide: "end" });
    expect(bottomPanelRight.gridTemplateColumns).toBe("320px 8px minmax(0, 1fr) 8px 48px");

    const stacked = resolve({ layout: layoutFor("sideStack", { slots: { left: "chat", center: "terminal", rightTop: "sidebar", rightBottom: "editor" } }), collapsed: { ...NONE_COLLAPSED, sidebar: true } });
    expect(stacked.panes.sidebar).toMatchObject({ slot: "rightTop", shown: false, displayed: false, rail: false, railSide: "start" });
    expect(stacked.gridTemplateRows).toBe("0px 0px minmax(0, 1fr)");

    const bottomSlot = resolve({ layout: layoutFor("bottomPanel", { slots: { left: "terminal", center: "editor", right: "chat", bottom: "sidebar" } }), collapsed: { ...NONE_COLLAPSED, sidebar: true } });
    expect(bottomSlot.panes.sidebar).toMatchObject({ shown: false, rail: false });
    expect(bottomSlot.gridTemplateRows).toBe("minmax(0, 1fr) 0px 0px");
  });

  test("no pane shown reports an empty workbench", () => {
    const resolved = resolve({
      layout: layoutFor("sideStack", { slots: { left: "chat", center: "terminal", rightTop: "sidebar", rightBottom: "editor" } }),
      collapsed: { sidebar: true, editor: true, terminal: true, chat: true },
    });

    expect(resolved.hasShownPane).toBe(false);
    expect(resolved.resizers).toEqual([]);
  });

  test("editing shows every slot without rails or resizers while displayed keeps real visibility", () => {
    const resolved = resolve({
      editing: true,
      available: { ...ALL_AVAILABLE, editor: false, terminal: false },
      collapsed: { ...NONE_COLLAPSED, sidebar: true, chat: true },
      focusedPane: "sidebar",
    });

    expect(resolved.gridTemplateColumns).toBe("320px 8px minmax(0, 1fr) 8px 384px");
    expect(resolved.gridTemplateRows).toBe("420px 8px minmax(0, 1fr)");
    expect(resolved.resizers).toEqual([]);
    expect(resolved.hasShownPane).toBe(true);
    expect(Object.fromEntries(WORKBENCH_PANE_IDS.map((pane) => [pane, [resolved.panes[pane].shown, resolved.panes[pane].rail, resolved.panes[pane].displayed]]))).toEqual({
      sidebar: [true, false, true],
      editor: [true, false, false],
      terminal: [true, false, false],
      chat: [true, false, false],
    });
  });
});

describe("layout operations", () => {
  function resizerOf(resolved: ReturnType<typeof resolve>, id: string) {
    const resizer = resolved.resizers.find((item) => item.id === id);
    expect(resizer).toBeDefined();
    return resizer!;
  }

  test.each([
    { name: "column-2 divider +40", id: "x:left|center", delta: 40, sizes: { left: 360 } },
    { name: "column-4 divider +40", id: "x:center|right", delta: 40, sizes: { right: 344 } },
    { name: "row divider −100", id: "y:centerTop|centerBottom", delta: -100, sizes: { centerTop: 320 } },
    { name: "column-2 divider −500 clamps to the minimum", id: "x:left|center", delta: -500, sizes: { left: 220 } },
  ])("classic default, $name", ({ id, delta, sizes }) => {
    const next = applyLayoutResize(DEFAULT_WORKBENCH_LAYOUT, resizerOf(resolve(), id), delta);

    expect(next.templates.classic).toEqual({ slots: getTemplateLayout(DEFAULT_WORKBENCH_LAYOUT, "classic").slots, sizes });
  });

  test("columns at 1920×1080, col3/col4 divider +50 resizes both neighbours", () => {
    const layout = layoutFor("columns");
    const resolved = resolve({ layout, container: { width: 1920, height: 1080 } });

    const next = applyLayoutResize(layout, resizerOf(resolved, "x:col3|col4"), 50);

    expect(next.templates.columns?.sizes).toEqual({ col3: 470, col4: 310 });
  });

  test("resizing uses the descriptor captured at drag start", () => {
    const resizer = resizerOf(resolve(), "x:left|center");
    const first = applyLayoutResize(DEFAULT_WORKBENCH_LAYOUT, resizer, 20);
    const second = applyLayoutResize(first, resizer, 40);

    expect(second.templates.classic?.sizes).toEqual({ left: 360 });
    expect(applyLayoutResize(second, resizer, 40)).toBe(second);
  });

  test("swapping keeps a permutation, keeps sizes with slots and leaves other presets alone", () => {
    const bottomPanel = { slots: { left: "chat", center: "editor", right: "sidebar", bottom: "terminal" } as Record<string, WorkbenchPaneId>, sizes: { bottom: 300 } };
    const layout: WorkbenchLayoutState = {
      activeTemplate: "classic",
      templates: { classic: { slots: getTemplateLayout(DEFAULT_WORKBENCH_LAYOUT, "classic").slots, sizes: { left: 360 } }, bottomPanel },
    };

    const swapped = swapLayoutPanes(layout, "sidebar", "chat");

    expect(swapped.templates.classic).toEqual({
      slots: { left: "chat", centerTop: "editor", centerBottom: "terminal", right: "sidebar" },
      sizes: { left: 360 },
    });
    expect(new Set(Object.values(swapped.templates.classic!.slots))).toEqual(new Set(WORKBENCH_PANE_IDS));
    expect(swapped.templates.bottomPanel).toBe(bottomPanel);
    expect(swapLayoutPanes(layout, "chat", "chat")).toBe(layout);
    expect(resolve({ layout: swapped }).gridTemplateColumns).toBe("360px 8px minmax(0, 1fr) 8px 384px");
  });

  test("selecting only changes the active preset and reset only clears the active preset", () => {
    const layout = swapLayoutPanes(selectLayoutTemplate(swapLayoutPanes(DEFAULT_WORKBENCH_LAYOUT, "sidebar", "chat"), "columns"), "editor", "terminal");

    expect(layout.activeTemplate).toBe("columns");
    expect(Object.keys(layout.templates).sort()).toEqual(["classic", "columns"]);
    expect(selectLayoutTemplate(layout, "columns")).toBe(layout);

    const reset = resetLayoutTemplate(layout);
    expect(reset.activeTemplate).toBe("columns");
    expect(reset.templates).toEqual({ classic: layout.templates.classic });
    expect(resetLayoutTemplate(reset)).toBe(reset);
  });
});

describe("stored layout", () => {
  test("missing or non-object payloads give the defaults", () => {
    expect(normalizeWorkbenchLayout(undefined)).toEqual(DEFAULT_WORKBENCH_LAYOUT);
    expect(normalizeWorkbenchLayout(null)).toEqual(DEFAULT_WORKBENCH_LAYOUT);
    expect(normalizeWorkbenchLayout("classic")).toEqual(DEFAULT_WORKBENCH_LAYOUT);
    expect(DEFAULT_DESKTOP_PANE_STATE.layout).toEqual(DEFAULT_WORKBENCH_LAYOUT);
  });

  test("an unknown active preset falls back to classic", () => {
    expect(normalizeWorkbenchLayout({ layoutVersion: 1, activeLayout: "floating", layouts: {} }).activeTemplate).toBe("classic");
    expect(normalizeWorkbenchLayout({ layoutVersion: 1, activeLayout: "sideStack" }).activeTemplate).toBe("sideStack");
  });

  test("an entry that is not a permutation of the four panes falls back to the preset defaults", () => {
    const layout = normalizeWorkbenchLayout({
      layoutVersion: 1,
      activeLayout: "columns",
      layouts: {
        columns: { slots: { col1: "sidebar", col2: "editor", col3: "editor", col4: "chat" }, sizes: { col1: 300 } },
        sideStack: { slots: { left: "sidebar", center: "chat", rightTop: "editor" }, sizes: {} },
        bottomPanel: { slots: { left: "sidebar", center: "editor", right: "chat", bottom: "browser" } },
      },
    });

    expect(layout.templates).toEqual({});
    expect(getTemplateLayout(layout, "columns")).toEqual(getTemplateLayout(DEFAULT_WORKBENCH_LAYOUT, "columns"));
  });

  test("sizes keep only known keys with finite values in [48, 4096]", () => {
    const layout = normalizeWorkbenchLayout({
      layoutVersion: 1,
      activeLayout: "classic",
      layouts: {
        classic: {
          slots: { left: "chat", centerTop: "editor", centerBottom: "terminal", right: "sidebar" },
          sizes: { left: 300, right: 9000, centerTop: 30, centerBottom: null, center: "640", unknown: 500 },
        },
      },
    });

    expect(layout.templates.classic).toEqual({
      slots: { left: "chat", centerTop: "editor", centerBottom: "terminal", right: "sidebar" },
      sizes: { left: 300 },
    });
    expect(getTemplateLayout(layout, "classic").sizes).toMatchObject({ left: 300, right: 384, centerTop: 420 });
  });

  test("a legacy-only payload seeds the classic preset", () => {
    expect(normalizeWorkbenchLayout({ sidebarWidthPx: 300, chatWidthPx: 400, editorHeightPx: 380, chatCollapsed: true }).templates).toEqual({
      classic: {
        slots: { left: "sidebar", centerTop: "editor", centerBottom: "terminal", right: "chat" },
        sizes: { left: 300, right: 400, centerTop: 380 },
      },
    });
    expect(normalizeWorkbenchLayout({ filesWidthPx: 280, chatWidthPx: 384 }).templates.classic?.sizes).toEqual({ left: 280 });
    expect(normalizeWorkbenchLayout({ sidebarWidthPx: 320, chatWidthPx: 384, editorHeightPx: 420 }).templates).toEqual({});
  });

  test("serializing writes the layout plus legacy mirrors of classic and round-trips", () => {
    const layout: WorkbenchLayoutState = {
      activeTemplate: "bottomPanel",
      templates: {
        classic: { slots: { left: "chat", centerTop: "editor", centerBottom: "terminal", right: "sidebar" }, sizes: { left: 300, centerTop: 380 } },
        bottomPanel: { slots: { left: "sidebar", center: "editor", right: "chat", bottom: "terminal" }, sizes: { bottom: 320 } },
      },
    };

    const serialized = serializeWorkbenchLayout(layout);

    expect(serialized).toEqual({
      sidebarWidthPx: 300,
      chatWidthPx: 384,
      editorHeightPx: 380,
      layoutVersion: 1,
      activeLayout: "bottomPanel",
      layouts: layout.templates,
    });
    expect(normalizeWorkbenchLayout(JSON.parse(JSON.stringify(serialized)))).toEqual(layout);
    expect(normalizeWorkbenchLayout(JSON.parse(JSON.stringify(serializeWorkbenchLayout(DEFAULT_WORKBENCH_LAYOUT))))).toEqual(DEFAULT_WORKBENCH_LAYOUT);
  });
});
