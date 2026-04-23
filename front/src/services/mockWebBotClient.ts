import { WebApiClientError } from "./types";
import type {
  Capability,
  AppUpdateDownloadProgress,
  AppUpdateStatus,
  AssistantCronJob,
  AssistantCronRun,
  AssistantCronRunRequestResult,
  CreateAssistantCronJobInput,
  BotOverview,
  BotSummary,
  ChatAttachmentDeleteResult,
  ChatAttachmentUploadResult,
  ChatMessage,
  ChatStatusUpdate,
  ChatTraceDetails,
  ChatTraceEvent,
  CliParamsPayload,
  CreateBotInput,
  DebugProfile,
  DebugState,
  DirectoryListing,
  AvatarAsset,
  FileOpenTarget,
  FileCopyResult,
  FileCreateResult,
  FileEntry,
  GitActionResult,
  GitDiffPayload,
  GitProxySettings,
  GitOverview,
  GitTreeStatus,
  FileMoveResult,
  FileRenameResult,
  HostEffect,
  PluginAction,
  PluginActionInvokeInput,
  PluginActionResult,
  PluginViewWindowRequest,
  PluginViewWindowPayload,
  PluginRenderResult,
  PluginSummary,
  PluginUpdateInput,
  FileWriteResult,
  PublicHostInfo,
  RegisterCodeCreateResult,
  RegisterCodeItem,
  SessionState,
  SystemScript,
  SystemScriptResult,
  TunnelSnapshot,
  UpdateAssistantCronJobInput,
  UpdateBotWorkdirOptions,
  WorkspaceDefinitionResult,
  WorkspaceOutlineResult,
  WorkspaceQuickOpenResult,
  WorkspaceSearchResult,
  TableColumn,
  TableRow,
  TableViewSummary,
  TableWindowPayload,
  TreeNode,
  TreeViewSummary,
  TreeWindowPayload,
  WaveformTrack,
  WaveformViewSummary,
  WaveformWindowPayload,
} from "./types";
import { WebBotClient } from "./webBotClient";
import { mockBots } from "../mocks/bots";
import { mockChatMessages } from "../mocks/chat";
import { mockFiles } from "../mocks/files";
import {
  DEMO_MAIN_WORKDIR,
  DEMO_SYSTEM_SCRIPTS_BY_BOT,
  DEMO_TEAM_WORKDIR,
} from "../mocks/demoEnvironment";
import { APP_VERSION } from "../theme";

const MOCK_RELEASE_URL = `https://github.com/example/cli-bridge/releases/tag/v${APP_VERSION}`;
const MEMBER_CAPABILITIES: Capability[] = [
  "view_bots",
  "view_bot_status",
  "view_file_tree",
  "mutate_browse_state",
  "view_chat_history",
  "view_chat_trace",
  "read_file_content",
  "write_files",
  "chat_send",
  "terminal_exec",
  "debug_exec",
  "git_ops",
  "run_scripts",
  "manage_cli_params",
  "view_plugins",
  "run_plugins",
  "admin_ops",
];
const SUPER_ADMIN_CAPABILITIES: Capability[] = [...MEMBER_CAPABILITIES, "manage_register_codes"];
const GUEST_CAPABILITIES: Capability[] = [
  "view_bots",
  "view_bot_status",
  "view_file_tree",
  "view_chat_history",
];
const MOCK_GIT_IGNORED_ITEMS: Record<string, string[]> = {
  main: ["dist"],
};

function resolveMemberCapabilities(username: string) {
  return username.trim() === "127.0.0.1"
    ? [...SUPER_ADMIN_CAPABILITIES]
    : [...MEMBER_CAPABILITIES];
}

function buildMockWaveformTracks(): WaveformTrack[] {
  return [
    {
      signalId: "tb.clk",
      label: "tb.clk",
      width: 1,
      segments: [
        { start: 0, end: 5, value: "0" },
        { start: 5, end: 10, value: "1" },
        { start: 10, end: 15, value: "0" },
        { start: 15, end: 20, value: "1" },
        { start: 20, end: 25, value: "0" },
        { start: 25, end: 30, value: "1" },
        { start: 30, end: 35, value: "0" },
        { start: 35, end: 40, value: "1" },
        { start: 40, end: 45, value: "0" },
        { start: 45, end: 50, value: "1" },
        { start: 50, end: 55, value: "0" },
        { start: 55, end: 60, value: "1" },
        { start: 60, end: 65, value: "0" },
        { start: 65, end: 70, value: "1" },
        { start: 70, end: 75, value: "0" },
        { start: 75, end: 80, value: "1" },
        { start: 80, end: 85, value: "0" },
        { start: 85, end: 90, value: "1" },
        { start: 90, end: 95, value: "0" },
        { start: 95, end: 100, value: "1" },
        { start: 100, end: 105, value: "0" },
        { start: 105, end: 110, value: "1" },
        { start: 110, end: 115, value: "0" },
        { start: 115, end: 120, value: "1" },
      ],
    },
    {
      signalId: "tb.rst_n",
      label: "tb.rst_n",
      width: 1,
      segments: [
        { start: 0, end: 10, value: "0" },
        { start: 10, end: 120, value: "1" },
      ],
    },
    {
      signalId: "tb.counter",
      label: "tb.counter",
      width: 4,
      segments: [
        { start: 0, end: 15, value: "0000" },
        { start: 15, end: 25, value: "0001" },
        { start: 25, end: 35, value: "0010" },
        { start: 35, end: 45, value: "0011" },
        { start: 45, end: 55, value: "0100" },
        { start: 55, end: 65, value: "0101" },
        { start: 65, end: 75, value: "0110" },
        { start: 75, end: 85, value: "0111" },
        { start: 85, end: 95, value: "1000" },
        { start: 95, end: 105, value: "1001" },
        { start: 105, end: 115, value: "1010" },
        { start: 115, end: 120, value: "1011" },
      ],
    },
  ];
}

function buildMockWaveformSummary(sourcePath: string): WaveformViewSummary {
  const tracks = buildMockWaveformTracks();
  return {
    path: sourcePath,
    timescale: "1ns",
    startTime: 0,
    endTime: 120,
    display: {
      defaultZoom: 1,
      zoomLevels: [0.5, 0.75, 1, 1.5, 2, 3, 4],
      showTimeAxis: true,
      busStyle: "cross",
      labelWidth: 220,
      minWaveWidth: 840,
      pixelsPerTime: 18,
      axisHeight: 42,
      trackHeight: 64,
    },
    signals: tracks.map((track) => ({
      signalId: track.signalId,
      label: track.label,
      width: track.width,
      kind: track.width > 1 ? "bus" : "scalar",
    })),
    defaultSignalIds: tracks.map((track) => track.signalId),
  };
}

const TIMING_COLUMNS: TableColumn[] = [
  { id: "endpoint", title: "Endpoint" },
  { id: "slack", title: "Slack", kind: "number", align: "right", sortable: true },
];

const TIMING_ROWS: TableRow[] = [
  {
    id: "path-1",
    cells: { endpoint: "rx_data", slack: -0.132 },
    actions: [{ id: "export-row", label: "导出行", target: "plugin", location: "row" }],
  },
  {
    id: "path-2",
    cells: { endpoint: "tx_data", slack: -0.081 },
    actions: [{ id: "export-row", label: "导出行", target: "plugin", location: "row" }],
  },
  {
    id: "path-3",
    cells: { endpoint: "ctrl_state", slack: 0.014 },
    actions: [{ id: "export-row", label: "导出行", target: "plugin", location: "row" }],
  },
];

function clonePluginActions(actions: PluginAction[] | undefined) {
  return (actions || []).map((action) => ({
    ...action,
    payload: action.payload ? { ...action.payload } : undefined,
    confirm: action.confirm ? { ...action.confirm } : undefined,
    hostAction: action.hostAction ? { ...action.hostAction } as HostEffect : undefined,
  }));
}

function buildMockTimingRows(offset: number, limit: number, query = "", sort?: { columnId?: string; direction?: string }) {
  let rows = TIMING_ROWS.filter((row) =>
    !query.trim() || String(row.cells.endpoint || "").toLowerCase().includes(query.trim().toLowerCase()),
  );
  if (sort?.columnId === "slack") {
    rows = [...rows].sort((left, right) => {
      const diff = Number(left.cells.slack || 0) - Number(right.cells.slack || 0);
      return sort.direction === "desc" ? -diff : diff;
    });
  }
  return rows.slice(offset, offset + limit).map((row) => ({
    ...row,
    cells: { ...row.cells },
    actions: clonePluginActions(row.actions),
  }));
}

function buildMockTimingSummary(defaultPageSize = 2): TableViewSummary {
  return {
    columns: TIMING_COLUMNS.map((column) => ({ ...column })),
    totalRows: TIMING_ROWS.length,
    defaultPageSize,
    actions: [{ id: "export-all", label: "导出 CSV", target: "plugin", location: "toolbar", variant: "primary" }],
  };
}

function cloneTreeNodes(nodes: TreeNode[]): TreeNode[] {
  return nodes.map((node) => ({
    ...node,
    actions: clonePluginActions(node.actions),
    children: node.children ? cloneTreeNodes(node.children) : undefined,
  }));
}

function buildMockTreeRoots(): TreeNode[] {
  return [
    {
      id: "top",
      label: "top",
      kind: "folder",
      badges: [{ text: "root" }],
      hasChildren: true,
      expandable: true,
      actions: [{ id: "open-source", label: "打开源码", target: "plugin", location: "node" }],
    },
    {
      id: "tb_uart",
      label: "tb_uart",
      kind: "symbol",
      secondaryText: "uart block",
      expandable: false,
      actions: [{ id: "copy-name", label: "复制名", target: "host", location: "node", hostAction: { type: "copy_text", text: "tb_uart" } }],
    },
  ];
}

function buildMockTreeChildren(nodeId: string): TreeNode[] {
  if (nodeId === "top") {
    return [
      {
        id: "top.u_core",
        label: "u_core",
        kind: "symbol",
        expandable: false,
        actions: [{ id: "open-source", label: "打开源码", target: "plugin", location: "node" }],
      },
      {
        id: "top.u_mem",
        label: "u_mem",
        kind: "symbol",
        expandable: false,
        actions: [{ id: "copy-name", label: "复制名", target: "host", location: "node", hostAction: { type: "copy_text", text: "u_mem" } }],
      },
    ];
  }
  return [];
}

function buildMockTreeSummary(): TreeViewSummary {
  return {
    roots: cloneTreeNodes(buildMockTreeRoots()),
    searchable: true,
    searchPlaceholder: "搜索层级",
    actions: [
      {
        id: "open-timing",
        label: "打开 Timing",
        target: "host",
        location: "toolbar",
        hostAction: {
          type: "open_plugin_view",
          pluginId: "timing-report",
          viewId: "timing-table",
          title: "timing.rpt",
          input: { path: "reports/timing.rpt" },
        },
      },
    ],
  };
}

function buildRepoOutlineFileNode(path: string, symbolCount?: number): TreeNode {
  const parts = path.split("/");
  const label = parts[parts.length - 1] || path;
  const parent = parts.slice(0, -1).join("/");
  return {
    id: `file:${path}`,
    label,
    kind: "file",
    secondaryText: parent,
    badges: typeof symbolCount === "number" ? [{ text: `${symbolCount} symbols` }] : undefined,
    hasChildren: path === "bot/web/api_service.py",
    expandable: path === "bot/web/api_service.py",
    payload: { path, nodeType: "file" },
    actions: [
      {
        id: "open-file",
        label: "打开文件",
        target: "host",
        location: "node",
        hostAction: { type: "open_file", path },
      },
    ],
  };
}

function buildRepoOutlineDirNode(path: string): TreeNode {
  const parts = path.split("/");
  const label = parts[parts.length - 1] || path;
  const parent = parts.slice(0, -1).join("/");
  return {
    id: `dir:${path}`,
    label,
    kind: "folder",
    secondaryText: parent,
    hasChildren: true,
    expandable: true,
    payload: { path, nodeType: "directory" },
  };
}

function buildRepoOutlineSymbolNode(): TreeNode {
  return {
    id: "symbol:bot/web/api_service.py:run_cli_chat:184",
    label: "run_cli_chat",
    kind: "function",
    secondaryText: "function · line 184",
    payload: {
      path: "bot/web/api_service.py",
      line: 184,
      symbol: "run_cli_chat",
      nodeType: "symbol",
    },
    actions: [
      {
        id: "jump-definition",
        label: "跳到定义",
        target: "host",
        location: "node",
        hostAction: { type: "open_file", path: "bot/web/api_service.py", line: 184 },
      },
    ],
  };
}

function buildRepoOutlineRoots(): TreeNode[] {
  return [
    buildRepoOutlineDirNode("bot"),
    buildRepoOutlineFileNode("README.md"),
  ];
}

function buildRepoOutlineChildren(nodeId: string): TreeNode[] {
  if (nodeId === "dir:bot") {
    return [buildRepoOutlineDirNode("bot/web")];
  }
  if (nodeId === "dir:bot/web") {
    return [buildRepoOutlineFileNode("bot/web/api_service.py", 1)];
  }
  if (nodeId === "file:bot/web/api_service.py") {
    return [buildRepoOutlineSymbolNode()];
  }
  return [];
}

function buildRepoOutlineSearch(query: string): TreeWindowPayload {
  const keyword = query.trim().toLowerCase();
  if (!keyword) {
    return {
      op: "search",
      nodes: cloneTreeNodes(buildRepoOutlineRoots()),
      statsText: "2 文件 · 1 符号",
    };
  }
  const matchesApiFile = [
    "bot/web/api_service.py",
    "api_service.py",
    "web",
    "bot",
    "run_cli_chat",
  ].some((value) => value.toLowerCase().includes(keyword));
  const matchesReadme = ["readme.md", "readme"].some((value) => value.includes(keyword));

  const nodes: TreeNode[] = [];
  if (matchesApiFile) {
    const fileNode = buildRepoOutlineFileNode("bot/web/api_service.py", 1);
    fileNode.children = keyword.includes("run") || keyword.includes("chat") || keyword.includes("api") || keyword.includes("web")
      ? [buildRepoOutlineSymbolNode()]
      : [];
    nodes.push(fileNode);
  }
  if (matchesReadme) {
    nodes.push(buildRepoOutlineFileNode("README.md"));
  }
  return {
    op: "search",
    nodes: cloneTreeNodes(nodes),
    statsText: `${nodes.length} 文件 · ${nodes.some((node) => node.id.startsWith("file:bot/web/api_service.py")) ? 1 : 0} 符号`,
  };
}

function buildRepoOutlineSummary(): TreeViewSummary {
  return {
    roots: cloneTreeNodes(buildRepoOutlineRoots()),
    searchable: true,
    searchPlaceholder: "搜目录、文件、符号",
    statsText: "2 文件 · 1 符号",
    emptySearchText: "未找到匹配目录、文件、符号",
    actions: [
      { id: "refresh-tree", label: "刷新", target: "plugin", location: "toolbar" },
      { id: "collapse-all", label: "折叠全部", target: "plugin", location: "toolbar" },
    ],
  };
}

export class MockWebBotClient implements WebBotClient {
  private bots = new Map<string, BotSummary>(
    mockBots.map((item) => [
      item.alias,
      {
        ...item,
        cliPath: item.cliType,
        botMode: "cli",
        enabled: true,
        isMain: item.alias === "main",
      },
    ]),
  );
  private currentPaths = new Map<string, string>();
  private pluginSessions = new Map<
    string,
    | { pluginId: string; renderer: "waveform"; summary: WaveformViewSummary; window: WaveformWindowPayload }
    | { pluginId: string; renderer: "table"; summary: TableViewSummary; window: TableWindowPayload }
    | { pluginId: string; renderer: "tree"; summary: TreeViewSummary; window: TreeWindowPayload }
  >();
  private pluginSessionCounter = 0;
  private pluginArtifacts = new Map<string, { filename: string; content: string }>();
  private pluginArtifactCounter = 0;
  private workdirOverrides = new Map<string, string>();
  private gitOverviews = new Map<string, GitOverview>([
    [
      "main",
      {
        repoFound: true,
        canInit: false,
        workingDir: DEMO_MAIN_WORKDIR,
        repoPath: DEMO_MAIN_WORKDIR,
        repoName: "demo",
        currentBranch: "main",
        isClean: false,
        aheadCount: 1,
        behindCount: 0,
        changedFiles: [
          {
            path: "bot/web/server.py",
            status: "M ",
            staged: true,
            unstaged: false,
            untracked: false,
          },
          {
            path: "front/src/screens/GitScreen.tsx",
            status: "??",
            staged: false,
            unstaged: false,
            untracked: true,
          },
        ],
        recentCommits: [
          {
            hash: "847b894",
            shortHash: "847b894",
            authorName: "Web Bot",
            authoredAt: "2026-04-08 03:00:00 +0800",
            subject: "feat: 实现完整的Web前端与后端集成",
          },
        ],
      },
    ],
    [
      "team2",
      {
        repoFound: true,
        canInit: false,
        workingDir: DEMO_TEAM_WORKDIR,
        repoPath: DEMO_TEAM_WORKDIR,
        repoName: "plans",
        currentBranch: "feature/git-panel",
        isClean: true,
        aheadCount: 0,
        behindCount: 0,
        changedFiles: [],
        recentCommits: [
          {
            hash: "cfb8d40",
            shortHash: "cfb8d40",
            authorName: "Web Bot",
            authoredAt: "2026-04-09 13:00:00 +0800",
            subject: "docs: add web tunnel and cli settings design",
          },
        ],
      },
    ],
  ]);
  private gitProxySettings: GitProxySettings = { port: "" };
  private updateStatus: AppUpdateStatus = {
    currentVersion: APP_VERSION,
    updateEnabled: true,
    updateChannel: "release",
    lastCheckedAt: "",
    latestVersion: APP_VERSION,
    latestReleaseUrl: MOCK_RELEASE_URL,
    latestNotes: "Bugfixes",
    pendingUpdateVersion: "",
    pendingUpdatePath: "",
    pendingUpdateNotes: "",
    pendingUpdatePlatform: "",
    lastError: "",
  };
  private readonly avatarAssets: AvatarAsset[] = [
    { name: "avatar_01.png", url: "/assets/avatars/avatar_01.png" },
    { name: "avatar_02.png", url: "/assets/avatars/avatar_02.png" },
    { name: "avatar_03.png", url: "/assets/avatars/avatar_03.png" },
    { name: "avatar_04.png", url: "/assets/avatars/avatar_04.png" },
  ];
  private plugins: PluginSummary[] = [
    {
      id: "vivado-waveform",
      schemaVersion: 2,
      name: "Vivado Waveform",
      version: "0.1.0",
      description: "Vivado/HDL 波形预览，V1 支持 VCD。",
      enabled: true,
      config: { lodEnabled: true },
      configSchema: {
        title: "Waveform Settings",
        sections: [
          {
            id: "display",
            fields: [
              {
                key: "lodEnabled",
                label: "启用 LOD",
                type: "boolean",
                default: true,
                description: "缩放较大时自动降采样。",
              },
            ],
          },
        ],
      },
      views: [{ id: "waveform", title: "波形预览", renderer: "waveform", viewMode: "session", dataProfile: "heavy" }],
      fileHandlers: [{ id: "wave-vcd", label: "VCD 波形预览", extensions: [".vcd"], viewId: "waveform" }],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: {},
      },
    },
    {
      id: "timing-report",
      schemaVersion: 2,
      name: "Timing Report",
      version: "0.2.0",
      description: "结构化 timing 表格视图。",
      enabled: true,
      config: { defaultPageSize: 2 },
      configSchema: {
        title: "Timing Settings",
        sections: [
          {
            id: "display",
            fields: [
              {
                key: "defaultPageSize",
                label: "默认页大小",
                type: "integer",
                default: 2,
                minimum: 1,
              },
            ],
          },
        ],
      },
      views: [{ id: "timing-table", title: "Timing Paths", renderer: "table", viewMode: "session", dataProfile: "heavy" }],
      fileHandlers: [{ id: "timing-rpt", label: "Timing 报告", extensions: [".rpt"], viewId: "timing-table" }],
      catalogActions: [{ id: "export-all", label: "导出 CSV", target: "plugin", location: "catalog", variant: "primary" }],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: { workspaceRead: true, tempArtifacts: true },
      },
    },
    {
      id: "repo-outline",
      schemaVersion: 2,
      name: "Repo Outline",
      version: "0.1.0",
      description: "浏览仓库目录、文件和符号。",
      enabled: true,
      config: {
        includeHidden: false,
        maxFiles: 2000,
        maxSymbolsPerFile: 200,
        codeExtensions: ".py,.ts,.tsx,.js,.jsx,.go,.rs,.java,.kt,.md",
      },
      configSchema: {
        title: "仓库大纲设置",
        sections: [
          {
            id: "scan",
            fields: [
              { key: "includeHidden", label: "包含隐藏目录", type: "boolean", default: false },
              { key: "maxFiles", label: "最大扫描文件数", type: "integer", default: 2000, minimum: 200, maximum: 20000 },
              { key: "maxSymbolsPerFile", label: "单文件最大符号数", type: "integer", default: 200, minimum: 20, maximum: 1000 },
              { key: "codeExtensions", label: "代码扩展名", type: "string", default: ".py,.ts,.tsx,.js,.jsx,.go,.rs,.java,.kt,.md" },
            ],
          },
        ],
      },
      views: [{ id: "repo-tree", title: "仓库大纲", renderer: "tree", viewMode: "session", dataProfile: "light" }],
      fileHandlers: [],
      catalogActions: [
        {
          id: "open-outline",
          label: "打开仓库大纲",
          target: "host",
          location: "catalog",
          variant: "primary",
          hostAction: {
            type: "open_plugin_view",
            pluginId: "repo-outline",
            viewId: "repo-tree",
            title: "仓库大纲",
            input: {},
          },
        },
      ],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: { workspaceRead: true, workspaceList: true },
      },
    },
    {
      id: "rtl-hierarchy",
      schemaVersion: 2,
      name: "RTL Hierarchy",
      version: "0.2.0",
      description: "模块层级树视图。",
      enabled: true,
      config: {},
      views: [{ id: "module-tree", title: "Hierarchy", renderer: "tree", viewMode: "session", dataProfile: "light" }],
      fileHandlers: [{ id: "rtl-hier", label: "层级视图", extensions: [".hier"], viewId: "module-tree" }],
      catalogActions: [
        {
          id: "open-timing",
          label: "打开 Timing",
          target: "host",
          location: "catalog",
          hostAction: {
            type: "open_plugin_view",
            pluginId: "timing-report",
            viewId: "timing-table",
            title: "timing.rpt",
            input: { path: "reports/timing.rpt" },
          },
        },
      ],
      runtime: {
        type: "python",
        entry: "backend/main.py",
        protocol: "jsonrpc-stdio",
        permissions: { workspaceRead: true },
      },
    },
  ];
  private assistantCronJobs = new Map<string, AssistantCronJob[]>();
  private assistantCronRuns = new Map<string, AssistantCronRun[]>();
  private fileContents = new Map<string, string>();
  private fileVersions = new Map<string, number>();
  private registerCodes: RegisterCodeItem[] = [
    {
      codeId: "invite-demo-1",
      codePreview: "INV***001",
      disabled: false,
      maxUses: 3,
      usedCount: 1,
      remainingUses: 2,
      createdAt: "2026-04-22T01:00:00Z",
      createdBy: "127.0.0.1",
      lastUsedAt: "2026-04-22T02:00:00Z",
      usage: [{ usedAt: "2026-04-22T02:00:00Z", usedBy: "alice" }],
    },
  ];
  private session: SessionState = {
    currentBotAlias: "main",
    currentPath: "/",
    isLoggedIn: true,
    token: "mock-session-member",
    username: "demo",
    role: "member",
    capabilities: [...MEMBER_CAPABILITIES],
  };

  private moveKey<T>(map: Map<string, T>, oldKey: string, newKey: string) {
    if (!map.has(oldKey)) {
      return;
    }
    const value = map.get(oldKey) as T;
    map.delete(oldKey);
    map.set(newKey, value);
  }

  private getBotSummary(botAlias: string): BotSummary {
    const fallback = this.bots.get("main") || Array.from(this.bots.values())[0];
    const base = this.bots.get(botAlias) || fallback;
    if (!base) {
      return {
        alias: botAlias,
        cliType: "codex",
        status: "running",
        workingDir: DEMO_MAIN_WORKDIR,
        lastActiveText: "运行中",
        avatarName: "avatar_01.png",
        cliPath: "codex",
        botMode: "cli",
        enabled: true,
        isMain: false,
      };
    }
    const workingDir = this.workdirOverrides.get(base.alias) || base.workingDir;
    return {
      ...base,
      workingDir,
    };
  }

  private clonePluginSummary(plugin: PluginSummary): PluginSummary {
    return {
      ...plugin,
      config: { ...(plugin.config || {}) },
      configSchema: plugin.configSchema
        ? {
            title: plugin.configSchema.title,
            sections: plugin.configSchema.sections.map((section) => ({
              ...section,
              fields: section.fields.map((field) => ({
                ...field,
                options: "options" in field && field.options
                  ? field.options.map((option) => ({ ...option }))
                  : undefined,
              })),
            })),
          }
        : undefined,
      catalogActions: clonePluginActions(plugin.catalogActions),
      views: plugin.views.map((view) => ({ ...view })),
      fileHandlers: plugin.fileHandlers.map((handler) => ({ ...handler, extensions: [...handler.extensions] })),
      runtime: plugin.runtime
        ? {
            ...plugin.runtime,
            permissions: plugin.runtime.permissions ? { ...plugin.runtime.permissions } : undefined,
          }
        : undefined,
    };
  }

  private getBrowserPath(botAlias: string): string {
    return this.currentPaths.get(botAlias) || this.getBotSummary(botAlias).workingDir;
  }

  private resolveTargetDir(botAlias: string, parentPath?: string): string {
    const candidate = parentPath?.trim();
    return candidate && candidate.length > 0 ? candidate : this.getBrowserPath(botAlias);
  }

  private normalizeMockPath(path: string): string {
    return path.trim().replace(/\\/g, "/").replace(/\/+$/g, "") || "/";
  }

  private resolveFileTreePath(botAlias: string, path: string): string {
    const candidate = this.normalizeMockPath(path);
    if (candidate.startsWith("/")) {
      return candidate;
    }
    const root = this.normalizeMockPath(this.getBrowserPath(botAlias));
    return root === "/" ? `/${candidate}` : `${root}/${candidate}`;
  }

  private splitMockFilePath(fullPath: string) {
    const normalized = this.normalizeMockPath(fullPath);
    const lastSlash = normalized.lastIndexOf("/");
    if (lastSlash <= 0) {
      return { dir: "/", name: normalized.replace(/^\/+/, "") };
    }
    return {
      dir: normalized.slice(0, lastSlash),
      name: normalized.slice(lastSlash + 1),
    };
  }

  private relativeMockPath(botAlias: string, fullPath: string): string {
    const root = this.normalizeMockPath(this.getBrowserPath(botAlias));
    const normalized = this.normalizeMockPath(fullPath);
    if (normalized === root) {
      return "";
    }
    if (normalized.startsWith(`${root}/`)) {
      return normalized.slice(root.length + 1);
    }
    return normalized.replace(/^\/+/, "");
  }

  private buildCopyName(botFiles: Record<string, FileEntry[]>, dir: string, sourceName: string) {
    const dotIndex = sourceName.lastIndexOf(".");
    const hasExtension = dotIndex > 0 && dotIndex < sourceName.length - 1;
    const stem = hasExtension ? sourceName.slice(0, dotIndex) : sourceName;
    const suffix = hasExtension ? sourceName.slice(dotIndex) : "";
    const existing = new Set((botFiles[dir] || []).map((entry) => entry.name));
    let candidate = `${stem} 副本${suffix}`;
    let counter = 2;
    while (existing.has(candidate)) {
      candidate = `${stem} 副本 ${counter}${suffix}`;
      counter += 1;
    }
    return candidate;
  }

  private sortFileEntries(entries: Array<{ name: string; isDir: boolean }>) {
    entries.sort((left, right) => {
      if (left.isDir !== right.isDir) {
        return left.isDir ? -1 : 1;
      }
      return left.name.localeCompare(right.name, "zh-CN");
    });
  }

  private cronRunKey(botAlias: string, jobId: string): string {
    return `${botAlias}:${jobId}`;
  }

  private fileKey(botAlias: string, browserPath: string, filename: string): string {
    return `${botAlias}:${browserPath}:${filename}`;
  }

  private getFileContent(botAlias: string, browserPath: string, filename: string): string {
    const key = this.fileKey(botAlias, browserPath, filename);
    if (this.fileContents.has(key)) {
      return this.fileContents.get(key) || "";
    }
    return `Mock full content for ${filename}\n\nThis is the full file content.`;
  }

  private getFileVersion(botAlias: string, browserPath: string, filename: string): number {
    const key = this.fileKey(botAlias, browserPath, filename);
    if (!this.fileVersions.has(key)) {
      this.fileVersions.set(key, Date.now() * 1_000_000);
    }
    return this.fileVersions.get(key) || Date.now() * 1_000_000;
  }

  private setFileState(botAlias: string, browserPath: string, filename: string, content: string): number {
    const key = this.fileKey(botAlias, browserPath, filename);
    const version = Date.now() * 1_000_000 + Math.floor(Math.random() * 1_000);
    this.fileContents.set(key, content);
    this.fileVersions.set(key, version);
    return version;
  }

  private getAssistantCronJobs(botAlias: string): AssistantCronJob[] {
    return [...(this.assistantCronJobs.get(botAlias) || [])];
  }

  async getPublicHostInfo(): Promise<PublicHostInfo> {
    return {
      username: "demo",
      operatingSystem: "Windows 11",
      hardwarePlatform: "AMD64",
      hardwareSpec: "16 逻辑核心 · 32 GB 内存",
    };
  }

  async login(_input: { username: string; password: string } | string): Promise<SessionState> {
    const legacyToken = typeof _input === "string"
      ? _input
      : !_input.password
        ? _input.username.trim()
        : "";
    const username = typeof _input === "string"
      ? _input.trim() || "alice"
      : _input.username.trim() || "alice";
    this.session = {
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      token: legacyToken || "mock-session-member",
      username,
      role: "member",
      capabilities: resolveMemberCapabilities(username),
    };
    return { ...this.session };
  }

  async register(input: { username: string; password: string; registerCode: string }): Promise<SessionState> {
    this.session = {
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      token: "mock-session-member",
      username: input.username,
      role: "member",
      capabilities: resolveMemberCapabilities(input.username),
    };
    return { ...this.session };
  }

  async loginGuest(): Promise<SessionState> {
    this.session = {
      currentBotAlias: "main",
      currentPath: "/",
      isLoggedIn: true,
      token: "mock-session-guest",
      username: "guest",
      role: "guest",
      capabilities: [...GUEST_CAPABILITIES],
    };
    return { ...this.session };
  }

  async restoreSession(): Promise<SessionState> {
    return { ...this.session };
  }

  async logout(): Promise<void> {
    this.session = {
      currentBotAlias: "",
      currentPath: "",
      isLoggedIn: false,
      token: "",
      username: "",
      role: "guest",
      capabilities: [],
    };
  }

  async listRegisterCodes(): Promise<RegisterCodeItem[]> {
    return this.registerCodes.map((item) => ({ ...item, usage: [...item.usage] }));
  }

  async createRegisterCode(maxUses = 1): Promise<RegisterCodeCreateResult> {
    const created: RegisterCodeCreateResult = {
      codeId: `invite-${Date.now()}`,
      code: `INV-${String(this.registerCodes.length + 1).padStart(3, "0")}`,
      codePreview: `INV***${String(this.registerCodes.length + 1).padStart(3, "0")}`,
      disabled: false,
      maxUses,
      usedCount: 0,
      remainingUses: maxUses,
      createdAt: new Date().toISOString(),
      createdBy: "127.0.0.1",
      lastUsedAt: "",
      usage: [],
    };
    this.registerCodes = [created, ...this.registerCodes];
    return { ...created, usage: [] };
  }

  async updateRegisterCode(codeId: string, input: { maxUsesDelta?: number; disabled?: boolean }): Promise<RegisterCodeItem> {
    const index = this.registerCodes.findIndex((item) => item.codeId === codeId);
    if (index < 0) {
      throw new WebApiClientError("邀请码不存在", { status: 404, code: "register_code_not_found" });
    }
    const current = this.registerCodes[index];
    const nextMaxUses = typeof input.maxUsesDelta === "number" ? current.maxUses + input.maxUsesDelta : current.maxUses;
    if (nextMaxUses < current.usedCount || nextMaxUses <= 0) {
      throw new WebApiClientError("使用次数无效", { status: 400, code: "invalid_register_code_max_uses" });
    }
    const updated: RegisterCodeItem = {
      ...current,
      maxUses: nextMaxUses,
      remainingUses: nextMaxUses - current.usedCount,
      disabled: typeof input.disabled === "boolean" ? input.disabled : current.disabled,
    };
    this.registerCodes[index] = updated;
    return { ...updated, usage: [...updated.usage] };
  }

  async deleteRegisterCode(codeId: string): Promise<void> {
    this.registerCodes = this.registerCodes.filter((item) => item.codeId !== codeId);
  }

  async listBots(): Promise<BotSummary[]> {
    return Array.from(this.bots.values()).map((item) => this.getBotSummary(item.alias));
  }

  async listPlugins(_refresh = false): Promise<PluginSummary[]> {
    return this.plugins.map((plugin) => this.clonePluginSummary(plugin));
  }

  async updatePlugin(pluginId: string, input: PluginUpdateInput): Promise<PluginSummary> {
    const index = this.plugins.findIndex((plugin) => plugin.id === pluginId);
    if (index < 0) {
      throw new WebApiClientError("插件不存在", { status: 404, code: "plugin_not_found" });
    }
    const current = this.plugins[index];
    const updated: PluginSummary = {
      ...current,
      enabled: typeof input.enabled === "boolean" ? input.enabled : current.enabled,
      config: input.config ? { ...(current.config || {}), ...input.config } : { ...(current.config || {}) },
      views: current.views.map((view) => ({ ...view })),
      fileHandlers: current.fileHandlers.map((handler) => ({ ...handler, extensions: [...handler.extensions] })),
      configSchema: current.configSchema,
      catalogActions: clonePluginActions(current.catalogActions),
      runtime: current.runtime
        ? {
            ...current.runtime,
            permissions: current.runtime.permissions ? { ...current.runtime.permissions } : undefined,
          }
        : undefined,
    };
    this.plugins[index] = updated;
    return this.clonePluginSummary(updated);
  }

  async getBotOverview(botAlias: string): Promise<BotOverview> {
    const bot = this.getBotSummary(botAlias);
    return {
      ...bot,
      botMode: bot.botMode || "cli",
      cliPath: bot.cliPath,
      enabled: bot.enabled,
      isMain: bot.isMain,
      messageCount: mockChatMessages[bot.alias]?.length || 0,
      historyCount: mockChatMessages[bot.alias]?.length || 0,
      isProcessing: false,
    };
  }

  async listMessages(botAlias: string): Promise<ChatMessage[]> {
    return mockChatMessages[botAlias] || [];
  }

  async getMessageTrace(_botAlias: string, _messageId: string): Promise<ChatTraceDetails> {
    return {
      traceCount: 0,
      toolCallCount: 0,
      processCount: 0,
      trace: [],
    };
  }

  async getDebugProfile(_botAlias: string): Promise<DebugProfile | null> {
    return {
      configName: "(gdb) Remote Debug",
      program: "H:\\Resources\\RTLinux\\Demos\\MB_DDF\\build\\aarch64\\Debug\\MB_DDF",
      cwd: "H:\\Resources\\RTLinux\\Demos\\MB_DDF",
      miDebuggerPath: "D:\\Toolchain\\aarch64-none-linux-gnu-gdb.exe",
      compileCommands: "H:\\Resources\\RTLinux\\Demos\\MB_DDF\\.vscode\\compile_commands.json",
      prepareCommand: ".\\debug.bat",
      stopAtEntry: true,
      setupCommands: [
        "-enable-pretty-printing",
        "set print thread-events off",
        "set pagination off",
        "set sysroot H:/Resources/RTLinux/Demos/MB_DDF/build/aarch64/sysroot",
      ],
      remoteHost: "192.168.1.29",
      remoteUser: "root",
      remoteDir: "/home/sast8/tmp",
      remotePort: 1234,
    };
  }

  async getDebugState(_botAlias: string): Promise<DebugState> {
    return {
      phase: "idle",
      message: "",
      breakpoints: [],
      frames: [],
      currentFrameId: "",
      scopes: [],
      variables: {},
    };
  }

  async sendMessage(
    botAlias: string,
    text: string,
    onChunk: (chunk: string) => void,
    onStatus?: (status: ChatStatusUpdate) => void,
    onTrace?: (trace: ChatTraceEvent) => void,
  ): Promise<ChatMessage> {
    let streamed = "";
    await streamAssistantReply((chunk) => {
      streamed += chunk;
      onChunk(chunk);
      onStatus?.({
        elapsedSeconds: streamed.length > 0 ? 1 : 0,
      });
    });
    return {
      id: Date.now().toString(),
      role: "assistant",
      text: streamed || "Mock response",
      createdAt: new Date().toISOString(),
      elapsedSeconds: 1,
      state: "done"
    };
  }

  async getCurrentPath(botAlias: string): Promise<string> {
    return this.getBotSummary(botAlias).workingDir;
  }

  async resolveFileOpenTarget(_botAlias: string, path: string): Promise<FileOpenTarget> {
    const lower = path.toLowerCase();
    if (lower.endsWith(".vcd")) {
      return {
        kind: "plugin_view",
        pluginId: "vivado-waveform",
        viewId: "waveform",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    if (lower.endsWith(".rpt")) {
      return {
        kind: "plugin_view",
        pluginId: "timing-report",
        viewId: "timing-table",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    if (lower.endsWith(".hier")) {
      return {
        kind: "plugin_view",
        pluginId: "rtl-hierarchy",
        viewId: "module-tree",
        title: path.split(/[\\/]/).pop() || path,
        input: { path },
      };
    }
    return { kind: "file" };
  }

  async listFiles(botAlias: string, path?: string): Promise<DirectoryListing> {
    const currentPath = path?.trim() || this.getBrowserPath(botAlias);
    const botFiles = mockFiles[botAlias] || {};
    return {
      workingDir: currentPath,
      entries: botFiles[currentPath] || [],
    };
  }

  async changeDirectory(botAlias: string, path: string): Promise<string> {
    const currentPath = this.getBrowserPath(botAlias);
    let nextPath = currentPath;
    if (path === "..") {
      if (currentPath !== "/") {
        const parts = currentPath.split("/").filter(Boolean);
        parts.pop();
        nextPath = parts.length ? `/${parts.join("/")}` : "/";
      }
    } else if (path.startsWith("/")) {
      nextPath = path;
    } else {
      nextPath = currentPath === "/" ? `/${path}` : `${currentPath}/${path}`;
    }
    this.currentPaths.set(botAlias, nextPath);
    return nextPath;
  }

  async createDirectory(botAlias: string, name: string, parentPath?: string): Promise<void> {
    const folderName = name.trim();
    if (!folderName) {
      throw new Error("文件夹名称不能为空");
    }

    const currentPath = this.resolveTargetDir(botAlias, parentPath);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[currentPath] || [])];
    if (currentEntries.some((entry) => entry.name === folderName)) {
      throw new Error("目标已存在");
    }

    currentEntries.push({ name: folderName, isDir: true });
    currentEntries.sort((left, right) => {
      if (left.isDir !== right.isDir) {
        return left.isDir ? -1 : 1;
      }
      return left.name.localeCompare(right.name, "zh-CN");
    });
    botFiles[currentPath] = currentEntries;

    const separator = currentPath.endsWith("/") ? "" : "/";
    const childPath = currentPath === "/" ? `/${folderName}` : `${currentPath}${separator}${folderName}`;
    botFiles[childPath] = botFiles[childPath] || [];
  }

  async deletePath(botAlias: string, path: string): Promise<void> {
    const targetName = path.trim();
    if (!targetName) {
      throw new Error("路径不能为空");
    }

    const currentPath = this.getBrowserPath(botAlias);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[currentPath] || [])];
    const target = currentEntries.find((entry) => entry.name === targetName);
    if (!target) {
      throw new Error("文件或文件夹不存在");
    }

    botFiles[currentPath] = currentEntries.filter((entry) => entry.name !== targetName);
    if (!target.isDir) {
      return;
    }

    const separator = currentPath.endsWith("/") ? "" : "/";
    const targetPath = currentPath === "/" ? `/${targetName}` : `${currentPath}${separator}${targetName}`;
    for (const candidate of Object.keys(botFiles)) {
      if (candidate === targetPath || candidate.startsWith(`${targetPath}/`)) {
        delete botFiles[candidate];
      }
    }
  }

  async readFile(botAlias: string, filename: string) {
    const browserPath = this.getBrowserPath(botAlias);
    const content = this.getFileContent(botAlias, browserPath, filename);
    return {
      content,
      mode: "head" as const,
      fileSizeBytes: new TextEncoder().encode(content).length,
      isFullContent: true,
      lastModifiedNs: String(this.getFileVersion(botAlias, browserPath, filename)),
    };
  }

  async readFileFull(botAlias: string, filename: string) {
    const browserPath = this.getBrowserPath(botAlias);
    const content = this.getFileContent(botAlias, browserPath, filename);
    return {
      content,
      mode: "cat" as const,
      fileSizeBytes: new TextEncoder().encode(content).length,
      isFullContent: true,
      lastModifiedNs: String(this.getFileVersion(botAlias, browserPath, filename)),
    };
  }

  async openPluginView(
    _botAlias: string,
    pluginId: string,
    viewId: string,
    input: Record<string, unknown>,
  ): Promise<PluginRenderResult> {
    if (pluginId === "timing-report") {
      const sourcePath = typeof input.path === "string" ? input.path : "reports/timing.rpt";
      const title = sourcePath.split(/[\\/]/).pop() || "timing.rpt";
      const pageSize = Number(this.plugins.find((plugin) => plugin.id === "timing-report")?.config?.defaultPageSize || 2);
      const summary = buildMockTimingSummary(pageSize);
      const initialWindow: TableWindowPayload = {
        offset: 0,
        limit: pageSize,
        totalRows: TIMING_ROWS.length,
        rows: buildMockTimingRows(0, pageSize),
      };
      this.pluginSessionCounter += 1;
      const sessionId = `timing-session-${this.pluginSessionCounter}`;
      this.pluginSessions.set(sessionId, { pluginId, renderer: "table", summary, window: initialWindow });
      return {
        pluginId,
        viewId,
        title,
        renderer: "table",
        mode: "session",
        sessionId,
        summary,
        initialWindow,
      };
    }
    if (pluginId === "rtl-hierarchy") {
      const sourcePath = typeof input.path === "string" ? input.path : "reports/design.hier";
      const title = sourcePath.split(/[\\/]/).pop() || "design.hier";
      const summary = buildMockTreeSummary();
      const initialWindow: TreeWindowPayload = {
        op: "children",
        nodeId: null,
        nodes: cloneTreeNodes(summary.roots || []),
      };
      this.pluginSessionCounter += 1;
      const sessionId = `tree-session-${this.pluginSessionCounter}`;
      this.pluginSessions.set(sessionId, { pluginId, renderer: "tree", summary, window: initialWindow });
      return {
        pluginId,
        viewId,
        title,
        renderer: "tree",
        mode: "session",
        sessionId,
        summary,
        initialWindow,
      };
    }
    if (pluginId === "repo-outline") {
      const summary = buildRepoOutlineSummary();
      const initialWindow: TreeWindowPayload = {
        op: "children",
        nodeId: null,
        nodes: cloneTreeNodes(summary.roots || []),
        statsText: summary.statsText,
      };
      this.pluginSessionCounter += 1;
      const sessionId = `repo-tree-session-${this.pluginSessionCounter}`;
      this.pluginSessions.set(sessionId, { pluginId, renderer: "tree", summary, window: initialWindow });
      return {
        pluginId,
        viewId,
        title: "仓库大纲",
        renderer: "tree",
        mode: "session",
        sessionId,
        summary,
        initialWindow,
      };
    }

    const sourcePath = typeof input.path === "string" ? input.path : "waves/simple_counter.vcd";
    const title = sourcePath.split(/[\\/]/).pop() || "simple_counter.vcd";
    const summary = buildMockWaveformSummary(sourcePath);
    const window: WaveformWindowPayload = {
      startTime: summary.startTime,
      endTime: summary.endTime,
      tracks: buildMockWaveformTracks(),
    };
    this.pluginSessionCounter += 1;
    const sessionId = `session-${this.pluginSessionCounter}`;
    this.pluginSessions.set(sessionId, { pluginId, renderer: "waveform", summary, window });
    return {
      pluginId,
      viewId,
      title,
      renderer: "waveform",
      mode: "session",
      sessionId,
      summary,
      initialWindow: window,
    };
  }

  private ensurePluginSession(sessionId: string, pluginId: string) {
    const existing = this.pluginSessions.get(sessionId);
    if (existing) {
      return existing.pluginId === pluginId ? existing : null;
    }
    if (!/^session-\d+$/.test(sessionId)) {
      if (/^timing-session-\d+$/.test(sessionId)) {
        const summary = buildMockTimingSummary(2);
        const session = {
          pluginId,
          renderer: "table" as const,
          summary,
          window: {
            offset: 0,
            limit: 2,
            totalRows: TIMING_ROWS.length,
            rows: buildMockTimingRows(0, 2),
          },
        };
        this.pluginSessions.set(sessionId, session);
        return session;
      }
      if (/^tree-session-\d+$/.test(sessionId)) {
        const summary = buildMockTreeSummary();
        const session = {
          pluginId,
          renderer: "tree" as const,
          summary,
          window: { op: "children" as const, nodeId: null, nodes: cloneTreeNodes(summary.roots || []) },
        };
        this.pluginSessions.set(sessionId, session);
        return session;
      }
      if (/^repo-tree-session-\d+$/.test(sessionId)) {
        const summary = buildRepoOutlineSummary();
        const session = {
          pluginId,
          renderer: "tree" as const,
          summary,
          window: {
            op: "children" as const,
            nodeId: null,
            nodes: cloneTreeNodes(summary.roots || []),
            statsText: summary.statsText,
          },
        };
        this.pluginSessions.set(sessionId, session);
        return session;
      }
      return null;
    }
    const summary = buildMockWaveformSummary("waves/simple_counter.vcd");
    const session = {
      pluginId,
      renderer: "waveform" as const,
      summary,
      window: {
        startTime: summary.startTime,
        endTime: summary.endTime,
        tracks: buildMockWaveformTracks(),
      },
    };
    this.pluginSessions.set(sessionId, session);
    return session;
  }

  async queryPluginViewWindow(
    _botAlias: string,
    pluginId: string,
    sessionId: string,
    request: PluginViewWindowRequest,
    signal?: AbortSignal,
  ): Promise<PluginViewWindowPayload> {
    signal?.throwIfAborted?.();
    const session = this.ensurePluginSession(sessionId, pluginId);
    if (!session) {
      throw new Error("插件会话不存在");
    }
    if (session.renderer === "table") {
      const offset = Number(request.offset || 0);
      const limit = Number(request.limit || session.summary.defaultPageSize || 2);
      const query = typeof request.query === "string" ? request.query : "";
      const sort = request.sort as { columnId?: string; direction?: string } | undefined;
      return {
        offset,
        limit,
        totalRows: query.trim()
          ? TIMING_ROWS.filter((row) => String(row.cells.endpoint || "").toLowerCase().includes(query.trim().toLowerCase())).length
          : TIMING_ROWS.length,
        rows: buildMockTimingRows(offset, limit, query, sort),
        appliedSort: sort,
      };
    }
    if (session.renderer === "tree") {
      const op = String((request as { op?: string; kind?: string }).op || (request as { op?: string; kind?: string }).kind || "children");
      if (session.pluginId === "repo-outline") {
        if (op === "search") {
          return buildRepoOutlineSearch(String(request.query || ""));
        }
        return {
          op: "children",
          nodeId: String(request.nodeId || ""),
          nodes: cloneTreeNodes(buildRepoOutlineChildren(String(request.nodeId || ""))),
          statsText: "2 文件 · 1 符号",
        };
      }
      if (op === "search") {
        const query = String(request.query || "").trim().toLowerCase();
        const roots = buildMockTreeRoots().filter((node) =>
          !query
            || node.label.toLowerCase().includes(query)
            || String(node.secondaryText || node.description || "").toLowerCase().includes(query),
        );
        return { op: "search", nodes: cloneTreeNodes(roots) };
      }
      return {
        op: "children",
        nodeId: String(request.nodeId || ""),
        nodes: cloneTreeNodes(buildMockTreeChildren(String(request.nodeId || ""))),
      };
    }
    const waveformRequest = request as {
      startTime: number;
      endTime: number;
      signalIds: string[];
    };
    return {
      startTime: waveformRequest.startTime,
      endTime: waveformRequest.endTime,
      tracks: session.window.tracks.filter((track) => waveformRequest.signalIds.includes(track.signalId)),
    };
  }

  async disposePluginViewSession(_botAlias: string, pluginId: string, sessionId: string): Promise<void> {
    const session = this.ensurePluginSession(sessionId, pluginId);
    if (!session) {
      return;
    }
    this.pluginSessions.delete(sessionId);
  }

  async invokePluginAction(
    _botAlias: string,
    pluginId: string,
    input: PluginActionInvokeInput,
  ): Promise<PluginActionResult> {
    if (pluginId === "timing-report") {
      this.pluginArtifactCounter += 1;
      const artifactId = `artifact-${this.pluginArtifactCounter}`;
      const content = input.payload?.rowId
        ? `endpoint,slack\n${String(input.payload.rowId)},-0.132\n`
        : "endpoint,slack\nrx_data,-0.132\ntx_data,-0.081\n";
      this.pluginArtifacts.set(artifactId, { filename: "timing.csv", content });
      return {
        message: "已导出",
        refresh: "session",
        hostEffects: [{ type: "download_artifact", artifactId, filename: "timing.csv" }],
      };
    }
    if (pluginId === "rtl-hierarchy") {
      if (input.actionId === "open-source") {
        return {
          message: "已打开源码",
          hostEffects: [{ type: "open_file", path: "src/index.ts", line: 12 }],
        };
      }
      return {
        hostEffects: [{ type: "copy_text", text: String(input.payload?.nodeId || "") }],
      };
    }
    if (pluginId === "repo-outline") {
      if (input.actionId === "refresh-tree") {
        return { message: "已刷新", refresh: "session" };
      }
      return { message: "已折叠" };
    }
    return { message: "已执行" };
  }

  async downloadPluginArtifact(_botAlias: string, artifactId: string, filename: string): Promise<void> {
    const artifact = this.pluginArtifacts.get(artifactId);
    const blob = new Blob([artifact?.content || ""], { type: "text/plain" });
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = artifact?.filename || filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(downloadUrl);
  }

  async writeFile(botAlias: string, path: string, content: string, expectedMtimeNs?: string): Promise<FileWriteResult> {
    const browserPath = this.getBrowserPath(botAlias);
    const currentVersion = this.getFileVersion(botAlias, browserPath, path);
    if (expectedMtimeNs !== undefined && expectedMtimeNs !== String(currentVersion)) {
      throw new Error("文件已被修改，请重新打开后再试");
    }

    const nextVersion = this.setFileState(botAlias, browserPath, path, content);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[browserPath] || [])];
    botFiles[browserPath] = currentEntries.map((entry) =>
      entry.name === path
        ? {
            ...entry,
            size: new TextEncoder().encode(content).length,
            updatedAt: new Date().toISOString(),
          }
        : entry,
    );

    return {
      path,
      fileSizeBytes: new TextEncoder().encode(content).length,
      lastModifiedNs: String(nextVersion),
    };
  }

  async createTextFile(botAlias: string, filename: string, content = "", parentPath?: string): Promise<FileCreateResult> {
    const fileName = filename.trim();
    if (!fileName) {
      throw new Error("文件名不能为空");
    }

    const targetDir = this.resolveTargetDir(botAlias, parentPath);
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[targetDir] || [])];
    if (currentEntries.some((entry) => entry.name === fileName)) {
      throw new Error("文件已存在");
    }

    currentEntries.push({
      name: fileName,
      isDir: false,
      size: new TextEncoder().encode(content).length,
      updatedAt: new Date().toISOString(),
    });
    currentEntries.sort((left, right) => {
      if (left.isDir !== right.isDir) {
        return left.isDir ? -1 : 1;
      }
      return left.name.localeCompare(right.name, "zh-CN");
    });
    botFiles[targetDir] = currentEntries;

    const nextVersion = this.setFileState(botAlias, targetDir, fileName, content);
    const browserPath = this.getBrowserPath(botAlias);
    const normalizedTargetDir = targetDir.replace(/\\/g, "/");
    const normalizedBrowserPath = browserPath.replace(/\\/g, "/");
    const relativeDir = normalizedTargetDir === normalizedBrowserPath
      ? ""
      : normalizedTargetDir.startsWith(`${normalizedBrowserPath}/`)
        ? normalizedTargetDir.slice(normalizedBrowserPath.length + 1)
        : "";
    return {
      path: relativeDir ? `${relativeDir}/${fileName}` : fileName,
      fileSizeBytes: new TextEncoder().encode(content).length,
      lastModifiedNs: String(nextVersion),
    };
  }

  async renamePath(botAlias: string, path: string, newName: string): Promise<FileRenameResult> {
    const browserPath = this.getBrowserPath(botAlias);
    const nextName = newName.trim();
    const botFiles = (mockFiles[botAlias] ||= {});
    const currentEntries = [...(botFiles[browserPath] || [])];
    if (currentEntries.some((entry) => entry.name === nextName)) {
      throw new Error("目标已存在");
    }

    const source = currentEntries.find((entry) => entry.name === path);
    if (!source || source.isDir) {
      throw new Error("文件不存在");
    }

    botFiles[browserPath] = currentEntries.map((entry) =>
      entry.name === path
        ? {
            ...entry,
            name: nextName,
            updatedAt: new Date().toISOString(),
          }
        : entry,
    );

    const content = this.getFileContent(botAlias, browserPath, path);
    const version = this.getFileVersion(botAlias, browserPath, path);
    this.fileContents.delete(this.fileKey(botAlias, browserPath, path));
    this.fileVersions.delete(this.fileKey(botAlias, browserPath, path));
    this.fileContents.set(this.fileKey(botAlias, browserPath, nextName), content);
    this.fileVersions.set(this.fileKey(botAlias, browserPath, nextName), version);

    return {
      oldPath: path,
      path: nextName,
    };
  }

  async copyPath(botAlias: string, path: string): Promise<FileCopyResult> {
    const sourceFullPath = this.resolveFileTreePath(botAlias, path);
    const { dir: sourceDir, name: sourceName } = this.splitMockFilePath(sourceFullPath);
    const botFiles = (mockFiles[botAlias] ||= {});
    const source = (botFiles[sourceDir] || []).find((entry) => entry.name === sourceName);
    if (!source || source.isDir) {
      throw new Error("文件不存在");
    }

    const copyName = this.buildCopyName(botFiles, sourceDir, sourceName);
    const content = this.getFileContent(botAlias, sourceDir, sourceName);
    const version = this.setFileState(botAlias, sourceDir, copyName, content);
    const nextEntry = {
      ...source,
      name: copyName,
      updatedAt: new Date().toISOString(),
    };
    const entries = [...(botFiles[sourceDir] || []), nextEntry];
    this.sortFileEntries(entries);
    botFiles[sourceDir] = entries;

    const targetFullPath = sourceDir === "/" ? `/${copyName}` : `${sourceDir}/${copyName}`;
    return {
      sourcePath: this.relativeMockPath(botAlias, sourceFullPath),
      path: this.relativeMockPath(botAlias, targetFullPath),
      fileSizeBytes: source.size || new TextEncoder().encode(content).length,
      lastModifiedNs: String(version),
    };
  }

  async movePath(botAlias: string, path: string, targetParentPath: string): Promise<FileMoveResult> {
    const sourceFullPath = this.resolveFileTreePath(botAlias, path);
    const targetDir = this.resolveFileTreePath(botAlias, targetParentPath);
    const { dir: sourceDir, name: sourceName } = this.splitMockFilePath(sourceFullPath);
    const botFiles = (mockFiles[botAlias] ||= {});
    const sourceEntries = [...(botFiles[sourceDir] || [])];
    const source = sourceEntries.find((entry) => entry.name === sourceName);
    if (!source || source.isDir) {
      throw new Error("文件不存在");
    }
    if (sourceDir === targetDir) {
      throw new Error("文件已在目标文件夹中");
    }
    if (!(botFiles[targetDir] || []).some((entry) => entry.isDir) && !(targetDir in botFiles)) {
      throw new Error("目录不存在");
    }

    const targetEntries = [...(botFiles[targetDir] || [])];
    if (targetEntries.some((entry) => entry.name === sourceName)) {
      throw new Error("目标已存在");
    }

    botFiles[sourceDir] = sourceEntries.filter((entry) => entry.name !== sourceName);
    targetEntries.push({ ...source, updatedAt: new Date().toISOString() });
    this.sortFileEntries(targetEntries);
    botFiles[targetDir] = targetEntries;

    const content = this.getFileContent(botAlias, sourceDir, sourceName);
    const version = this.getFileVersion(botAlias, sourceDir, sourceName);
    this.fileContents.delete(this.fileKey(botAlias, sourceDir, sourceName));
    this.fileVersions.delete(this.fileKey(botAlias, sourceDir, sourceName));
    this.fileContents.set(this.fileKey(botAlias, targetDir, sourceName), content);
    this.fileVersions.set(this.fileKey(botAlias, targetDir, sourceName), version);

    const targetFullPath = targetDir === "/" ? `/${sourceName}` : `${targetDir}/${sourceName}`;
    return {
      oldPath: this.relativeMockPath(botAlias, sourceFullPath),
      path: this.relativeMockPath(botAlias, targetFullPath),
    };
  }

  async quickOpenWorkspace(botAlias: string, query: string, limit = 50): Promise<WorkspaceQuickOpenResult> {
    const q = query.trim().toLowerCase();
    const botFiles = mockFiles[botAlias] || {};
    const rootPath = this.getBrowserPath(botAlias).replace(/\\/g, "/");
    const items = Object.entries(botFiles)
      .flatMap(([directory, entries]) => entries
        .filter((entry) => !entry.isDir)
        .map((entry) => {
          const normalizedDir = directory.replace(/\\/g, "/");
          const relativeDir = normalizedDir === rootPath
            ? ""
            : normalizedDir.startsWith(`${rootPath}/`)
              ? normalizedDir.slice(rootPath.length + 1)
              : normalizedDir.replace(/^\/+/, "");
          const path = relativeDir ? `${relativeDir}/${entry.name}` : entry.name;
          const lowerPath = path.toLowerCase();
          const basename = entry.name.toLowerCase();
          const score = basename.includes(q) ? 1000 : lowerPath.includes(q) ? 300 : 0;
          return { path, score };
        }))
      .filter((item) => !q || item.path.toLowerCase().includes(q))
      .sort((left, right) => right.score - left.score || left.path.localeCompare(right.path, "zh-CN"))
      .slice(0, limit);
    return { items };
  }

  async searchWorkspace(botAlias: string, query: string, limit = 100): Promise<WorkspaceSearchResult> {
    const q = query.trim().toLowerCase();
    if (!q) {
      return { items: [] };
    }
    const quick = await this.quickOpenWorkspace(botAlias, "", 500);
    const root = this.getBrowserPath(botAlias);
    const items = quick.items.flatMap((item) => {
      const content = this.getFileContent(botAlias, root, item.path);
      const lines = content.split(/\r?\n/);
      return lines.flatMap((line, index) => {
        const column = line.toLowerCase().indexOf(q);
        return column >= 0
          ? [{
              path: item.path,
              line: index + 1,
              column: column + 1,
              preview: line,
            }]
          : [];
      });
    }).slice(0, limit);
    return { items };
  }

  async getWorkspaceOutline(botAlias: string, path: string): Promise<WorkspaceOutlineResult> {
    const content = this.getFileContent(botAlias, this.getBrowserPath(botAlias), path);
    const items: WorkspaceOutlineResult["items"] = [];
    content.split(/\r?\n/).forEach((line, index) => {
      const classMatch = line.match(/^\s*class\s+([A-Za-z_][\w]*)/);
      if (classMatch) {
        items.push({ name: classMatch[1], kind: "class", line: index + 1 });
        return;
      }
      const functionMatch = line.match(/^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)|^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/);
      if (functionMatch) {
        items.push({ name: functionMatch[1] || functionMatch[2], kind: "function", line: index + 1 });
        return;
      }
      const headingMatch = line.match(/^#{1,6}\s+(.+)/);
      if (headingMatch) {
        items.push({ name: headingMatch[1].trim(), kind: "heading", line: index + 1 });
      }
    });
    return { items };
  }

  async resolveWorkspaceDefinition(
    botAlias: string,
    input: { path: string; line: number; column: number; symbol?: string },
  ): Promise<WorkspaceDefinitionResult> {
    const symbol = input.symbol?.trim();
    if (symbol === "run") {
      return {
        items: [
          {
            path: "src/service.py",
            line: 12,
            matchKind: "workspace_search",
            confidence: 0.78,
          },
        ],
      };
    }
    return {
      items: [],
    };
  }

  async uploadChatAttachment(botAlias: string, file: File): Promise<ChatAttachmentUploadResult> {
    const filename = file.name || "attachment.bin";
    return {
      filename,
      savedPath: `C:\\Users\\demo\\.tcb\\chat-attachments\\${botAlias}\\1001\\${filename}`,
      size: file.size,
    };
  }

  async deleteChatAttachment(_botAlias: string, savedPath: string): Promise<ChatAttachmentDeleteResult> {
    const segments = savedPath.split(/[\\/]+/).filter(Boolean);
    return {
      filename: segments[segments.length - 1] || savedPath,
      savedPath,
      existed: true,
      deleted: true,
    };
  }

  async uploadFile(botAlias: string, file: File): Promise<void> {
    return;
  }

  async downloadFile(botAlias: string, filename: string): Promise<void> {
    return;
  }

  async resetSession(botAlias: string): Promise<void> {
    return;
  }

  async killTask(botAlias: string): Promise<string> {
    return "已发送终止任务请求";
  }

  async restartService(): Promise<void> {
    return;
  }

  async getGitProxySettings(): Promise<GitProxySettings> {
    return { ...this.gitProxySettings };
  }

  async updateGitProxySettings(port: string): Promise<GitProxySettings> {
    this.gitProxySettings = {
      port: (port || "").trim(),
    };
    return { ...this.gitProxySettings };
  }

  async getUpdateStatus(): Promise<AppUpdateStatus> {
    return { ...this.updateStatus };
  }

  async setUpdateEnabled(enabled: boolean): Promise<AppUpdateStatus> {
    this.updateStatus = {
      ...this.updateStatus,
      updateEnabled: enabled,
    };
    return { ...this.updateStatus };
  }

  async checkForUpdate(): Promise<AppUpdateStatus> {
    this.updateStatus = {
      ...this.updateStatus,
      lastCheckedAt: "2026-04-15T10:00:00+08:00",
      latestVersion: APP_VERSION,
      latestReleaseUrl: MOCK_RELEASE_URL,
      latestNotes: "Bugfixes",
      lastError: "",
    };
    return { ...this.updateStatus };
  }

  async downloadUpdate(): Promise<AppUpdateStatus> {
    this.updateStatus = {
      ...this.updateStatus,
      pendingUpdateVersion: this.updateStatus.latestVersion || APP_VERSION,
      pendingUpdatePath: ".updates/cli-bridge-windows-x64.zip",
      pendingUpdateNotes: this.updateStatus.latestNotes || "Bugfixes",
      pendingUpdatePlatform: "windows-x64",
      lastError: "",
    };
    return { ...this.updateStatus };
  }

  async downloadUpdateStream(onProgress: (event: AppUpdateDownloadProgress) => void): Promise<AppUpdateStatus> {
    onProgress({
      phase: "log",
      downloadedBytes: 0,
      message: "开始下载更新包",
    });
    await new Promise((resolve) => setTimeout(resolve, 40));
    onProgress({
      phase: "log",
      downloadedBytes: 1024,
      totalBytes: 1024,
      percent: 100,
      message: "下载完成",
    });
    return this.downloadUpdate();
  }

  async getGitOverview(botAlias: string): Promise<GitOverview> {
    const workingDir = this.workdirOverrides.get(botAlias) || this.getBotSummary(botAlias).workingDir;
    const overview = this.gitOverviews.get(botAlias);
    if (!overview) {
      return {
        repoFound: false,
        canInit: true,
        workingDir,
        repoPath: "",
        repoName: "",
        currentBranch: "",
        isClean: true,
        aheadCount: 0,
        behindCount: 0,
        changedFiles: [],
        recentCommits: [],
      };
    }
    return {
      ...overview,
      workingDir,
      repoPath: overview.repoPath || workingDir,
    };
  }

  async getGitTreeStatus(botAlias: string): Promise<GitTreeStatus> {
    const overview = await this.getGitOverview(botAlias);
    const items: GitTreeStatus["items"] = {};

    for (const item of overview.changedFiles) {
      items[item.path] = item.untracked || item.status.startsWith("A")
        ? "added"
        : "modified";
    }

    for (const path of MOCK_GIT_IGNORED_ITEMS[botAlias] || []) {
      items[path] = "ignored";
    }

    return {
      repoFound: overview.repoFound,
      workingDir: overview.workingDir,
      repoPath: overview.repoPath,
      items,
    };
  }

  async initGitRepository(botAlias: string): Promise<GitOverview> {
    const workingDir = this.workdirOverrides.get(botAlias) || this.getBotSummary(botAlias).workingDir;
    const next: GitOverview = {
      repoFound: true,
      canInit: false,
      workingDir,
      repoPath: workingDir,
      repoName: workingDir.split(/[\\/]+/).filter(Boolean).pop() || "repo",
      currentBranch: "main",
      isClean: true,
      aheadCount: 0,
      behindCount: 0,
      changedFiles: [],
      recentCommits: [],
    };
    this.gitOverviews.set(botAlias, next);
    return next;
  }

  async getGitDiff(_botAlias: string, path: string, staged = false): Promise<GitDiffPayload> {
    return {
      path,
      staged,
      diff: `diff --git a/${path} b/${path}\n@@ -1 +1 @@\n-old line\n+new line`,
    };
  }

  private async actionWithOverview(botAlias: string, message: string, mutator?: (overview: GitOverview) => GitOverview): Promise<GitActionResult> {
    const current = await this.getGitOverview(botAlias);
    const next = mutator ? mutator(current) : current;
    this.gitOverviews.set(botAlias, next);
    return {
      message,
      overview: next,
    };
  }

  async stageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已暂存所选文件", (overview) => ({
      ...overview,
      changedFiles: overview.changedFiles.map((item) =>
        paths.includes(item.path)
          ? { ...item, staged: true, untracked: false, status: item.unstaged ? "MM" : "M " }
          : item,
      ),
      isClean: false,
    }));
  }

  async unstageGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已取消暂存所选文件", (overview) => ({
      ...overview,
      changedFiles: overview.changedFiles.map((item) =>
        paths.includes(item.path)
          ? { ...item, staged: false, status: item.untracked ? "??" : " M" }
          : item,
      ),
    }));
  }

  async discardGitPaths(botAlias: string, paths: string[]): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已丢弃所选文件改动", (overview) => {
      const changedFiles = overview.changedFiles.filter((item) => !paths.includes(item.path));
      return {
        ...overview,
        changedFiles,
        isClean: changedFiles.length === 0,
      };
    });
  }

  async discardAllGitChanges(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已丢弃全部改动", (overview) => ({
      ...overview,
      isClean: true,
      changedFiles: [],
    }));
  }

  async commitGitChanges(botAlias: string, message: string): Promise<GitActionResult> {
    const subject = (message || "").trim() || "mock commit";
    return this.actionWithOverview(botAlias, "已创建提交", (overview) => ({
      ...overview,
      isClean: true,
      changedFiles: [],
      recentCommits: [
        {
          hash: `${Date.now()}`,
          shortHash: `${Date.now()}`.slice(-7),
          authorName: "Web Bot",
          authoredAt: new Date().toISOString(),
          subject,
        },
        ...overview.recentCommits,
      ],
    }));
  }

  async fetchGitRemote(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已抓取远端更新");
  }

  async pullGitRemote(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已拉取远端更新");
  }

  async pushGitRemote(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已推送本地提交");
  }

  async stashGitChanges(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已暂存当前工作区", (overview) => ({
      ...overview,
      isClean: true,
      changedFiles: [],
    }));
  }

  async popGitStash(botAlias: string): Promise<GitActionResult> {
    return this.actionWithOverview(botAlias, "已恢复最近一次暂存", (overview) => ({
      ...overview,
      isClean: false,
      changedFiles: [
        {
          path: "restored.txt",
          status: " M",
          staged: false,
          unstaged: true,
          untracked: false,
        },
      ],
    }));
  }

  async updateBotCli(botAlias: string, cliType: string, cliPath: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    const next = {
      ...current,
      cliType: cliType as BotSummary["cliType"],
      cliPath: cliPath.trim(),
    };
    this.bots.set(botAlias, next);
    return this.getBotSummary(botAlias);
  }

  async updateBotWorkdir(
    botAlias: string,
    workingDir: string,
    options: UpdateBotWorkdirOptions = {},
  ): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    if (current.botMode === "assistant") {
      throw new Error("assistant 型 Bot 不允许修改默认工作目录");
    }
    const nextDir = workingDir.trim();
    const historyCount = mockChatMessages[botAlias]?.length || 0;
    if (!options.forceReset && historyCount > 0) {
      throw new WebApiClientError("切换工作目录会丢失当前会话，确认后重试", {
        status: 409,
        code: "workdir_change_requires_reset",
        data: {
          currentWorkingDir: current.workingDir,
          requestedWorkingDir: nextDir,
          historyCount,
          messageCount: historyCount,
          botMode: current.botMode || "cli",
        },
      });
    }
    this.workdirOverrides.set(botAlias, nextDir);
    this.currentPaths.set(botAlias, nextDir);
    this.bots.set(botAlias, {
      ...current,
      workingDir: nextDir,
    });
    return this.getBotSummary(botAlias);
  }

  async updateBotAvatar(botAlias: string, avatarName: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      avatarName: avatarName.trim(),
    });
    return this.getBotSummary(botAlias);
  }

  async listAssistantCronJobs(botAlias: string): Promise<AssistantCronJob[]> {
    return this.getAssistantCronJobs(botAlias);
  }

  async createAssistantCronJob(botAlias: string, input: CreateAssistantCronJobInput): Promise<AssistantCronJob> {
    const current = this.getAssistantCronJobs(botAlias);
    const taskMode = input.task.mode || "standard";
    const job: AssistantCronJob = {
      ...input,
      task: {
        prompt: input.task.prompt,
        mode: taskMode,
        lookbackHours: input.task.lookbackHours ?? 24,
        historyLimit: input.task.historyLimit ?? 40,
        captureLimit: input.task.captureLimit ?? 20,
        deliverMode: input.task.deliverMode ?? (taskMode === "dream" ? "silent" : "chat_handoff"),
      },
      nextRunAt: input.schedule.type === "daily"
        ? "2026-04-17T09:00:00+08:00"
        : "2026-04-16T10:00:00+08:00",
      lastStatus: "",
      lastError: "",
      lastSuccessAt: "",
      pending: false,
      pendingRunId: "",
      coalescedCount: 0,
    };
    this.assistantCronJobs.set(botAlias, [...current.filter((item) => item.id !== job.id), job]);
    return job;
  }

  async updateAssistantCronJob(
    botAlias: string,
    jobId: string,
    input: UpdateAssistantCronJobInput,
  ): Promise<AssistantCronJob> {
    const current = this.getAssistantCronJobs(botAlias);
    const existing = current.find((item) => item.id === jobId);
    if (!existing) {
      throw new Error("任务不存在");
    }
    const updated: AssistantCronJob = {
      ...existing,
      ...(typeof input.enabled === "boolean" ? { enabled: input.enabled } : {}),
      ...(input.title ? { title: input.title } : {}),
      schedule: {
        ...existing.schedule,
        ...(input.schedule || {}),
      },
      task: {
        ...existing.task,
        ...(input.task || {}),
        mode: input.task?.mode || existing.task.mode || "standard",
        lookbackHours: input.task?.lookbackHours ?? existing.task.lookbackHours ?? 24,
        historyLimit: input.task?.historyLimit ?? existing.task.historyLimit ?? 40,
        captureLimit: input.task?.captureLimit ?? existing.task.captureLimit ?? 20,
        deliverMode: input.task?.deliverMode
          ?? existing.task.deliverMode
          ?? ((input.task?.mode || existing.task.mode) === "dream" ? "silent" : "chat_handoff"),
      },
      execution: {
        ...existing.execution,
        ...(input.execution || {}),
      },
    };
    this.assistantCronJobs.set(
      botAlias,
      current.map((item) => (item.id === jobId ? updated : item)),
    );
    return updated;
  }

  async deleteAssistantCronJob(botAlias: string, jobId: string): Promise<void> {
    this.assistantCronJobs.set(
      botAlias,
      this.getAssistantCronJobs(botAlias).filter((item) => item.id !== jobId),
    );
    this.assistantCronRuns.delete(this.cronRunKey(botAlias, jobId));
  }

  async runAssistantCronJob(botAlias: string, jobId: string): Promise<AssistantCronRunRequestResult> {
    const job = this.getAssistantCronJobs(botAlias).find((item) => item.id === jobId);
    const runId = `run_${Date.now()}`;
    const runs = this.assistantCronRuns.get(this.cronRunKey(botAlias, jobId)) || [];
    this.assistantCronRuns.set(this.cronRunKey(botAlias, jobId), [
      {
        runId,
        jobId,
        triggerSource: "manual",
        scheduledAt: new Date().toISOString(),
        enqueuedAt: new Date().toISOString(),
        startedAt: "",
        finishedAt: "",
        status: "queued",
        elapsedSeconds: 0,
        queueWaitSeconds: 0,
        timedOut: false,
        promptExcerpt: "",
        outputExcerpt: "",
        error: "",
      },
      ...runs,
    ]);
    this.assistantCronJobs.set(
      botAlias,
      this.getAssistantCronJobs(botAlias).map((item) =>
        item.id === jobId
          ? { ...item, pending: true, pendingRunId: runId, lastStatus: "queued" }
          : item,
      ),
    );
    return {
      runId,
      status: "queued",
      taskMode: job?.task.mode || "standard",
      deliverMode: job?.task.deliverMode || "chat_handoff",
    };
  }

  async listAssistantCronRuns(botAlias: string, jobId: string, limit = 5): Promise<AssistantCronRun[]> {
    return (this.assistantCronRuns.get(this.cronRunKey(botAlias, jobId)) || []).slice(0, limit);
  }

  async addBot(input: CreateBotInput): Promise<BotSummary> {
    const alias = input.alias.trim().toLowerCase();
    const bot: BotSummary = {
      alias,
      cliType: input.cliType,
      cliPath: input.cliPath.trim(),
      botMode: input.botMode,
      status: "running",
      workingDir: input.workingDir.trim(),
      lastActiveText: "运行中",
      avatarName: input.avatarName,
      enabled: true,
      isMain: false,
    };
    this.bots.set(alias, bot);
    this.currentPaths.set(alias, bot.workingDir);
    this.workdirOverrides.set(alias, bot.workingDir);
    if (bot.botMode === "assistant" && !this.assistantCronJobs.has(alias)) {
      this.assistantCronJobs.set(alias, []);
    }
    return this.getBotSummary(alias);
  }

  async renameBot(botAlias: string, newAlias: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    const alias = newAlias.trim().toLowerCase();
    this.bots.delete(botAlias);
    this.bots.set(alias, {
      ...current,
      alias,
    });
    this.moveKey(this.currentPaths, botAlias, alias);
    this.moveKey(this.workdirOverrides, botAlias, alias);
    this.moveKey(this.gitOverviews, botAlias, alias);
    this.moveKey(this.assistantCronJobs, botAlias, alias);
    for (const [key, value] of Array.from(this.assistantCronRuns.entries())) {
      if (!key.startsWith(`${botAlias}:`)) {
        continue;
      }
      this.assistantCronRuns.delete(key);
      this.assistantCronRuns.set(`${alias}:${key.slice(botAlias.length + 1)}`, value);
    }
    return this.getBotSummary(alias);
  }

  async removeBot(botAlias: string): Promise<void> {
    if (botAlias === "main") {
      return;
    }
    this.bots.delete(botAlias);
    this.currentPaths.delete(botAlias);
    this.workdirOverrides.delete(botAlias);
    this.gitOverviews.delete(botAlias);
    this.assistantCronJobs.delete(botAlias);
    for (const key of Array.from(this.assistantCronRuns.keys())) {
      if (key.startsWith(`${botAlias}:`)) {
        this.assistantCronRuns.delete(key);
      }
    }
  }

  async startBot(botAlias: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      status: "running",
      lastActiveText: "运行中",
      enabled: true,
    });
    return this.getBotSummary(botAlias);
  }

  async stopBot(botAlias: string): Promise<BotSummary> {
    const current = this.getBotSummary(botAlias);
    this.bots.set(botAlias, {
      ...current,
      status: "offline",
      lastActiveText: "离线",
      enabled: false,
    });
    return this.getBotSummary(botAlias);
  }

  async listAvatarAssets(): Promise<AvatarAsset[]> {
    return [...this.avatarAssets];
  }

  async getCliParams(botAlias: string): Promise<CliParamsPayload> {
    const cliType = this.getBotSummary(botAlias).cliType;
    return {
      cliType,
      params: {
        reasoning_effort: "xhigh",
        model: "gpt-5.4",
        skip_git_check: true,
        json_output: true,
        yolo: true,
        extra_args: [],
      },
      defaults: {
        reasoning_effort: "xhigh",
        model: "gpt-5.4",
        skip_git_check: true,
        json_output: true,
        yolo: true,
        extra_args: [],
      },
      schema: {
        reasoning_effort: {
          type: "string",
          enum: ["xhigh", "high", "medium", "low"],
          description: "推理努力程度",
        },
        model: {
          type: "string",
          description: "模型选择",
        },
        skip_git_check: {
          type: "boolean",
          description: "跳过 Git 仓库检查",
        },
        json_output: {
          type: "boolean",
          description: "JSON 格式输出",
        },
        yolo: {
          type: "boolean",
          description: "绕过审批和沙箱",
        },
        extra_args: {
          type: "string_list",
          description: "额外参数",
        },
      },
    };
  }

  async updateCliParam(botAlias: string, key: string, value: unknown): Promise<CliParamsPayload> {
    const payload = await this.getCliParams(botAlias);
    return {
      ...payload,
      params: {
        ...payload.params,
        [key]: value,
      },
    };
  }

  async resetCliParams(botAlias: string): Promise<CliParamsPayload> {
    return this.getCliParams(botAlias);
  }

  async getTunnelStatus(): Promise<TunnelSnapshot> {
    return {
      mode: "cloudflare_quick",
      status: "running",
      source: "quick_tunnel",
      publicUrl: "https://demo.trycloudflare.com",
      localUrl: "http://127.0.0.1:8765",
      lastError: "",
      pid: 1234,
    };
  }

  async startTunnel(): Promise<TunnelSnapshot> {
    return this.getTunnelStatus();
  }

  async stopTunnel(): Promise<TunnelSnapshot> {
    return {
      mode: "cloudflare_quick",
      status: "stopped",
      source: "quick_tunnel",
      publicUrl: "",
      localUrl: "http://127.0.0.1:8765",
      lastError: "",
      pid: null,
    };
  }

  async restartTunnel(): Promise<TunnelSnapshot> {
    return this.getTunnelStatus();
  }

  async listSystemScripts(botAlias: string): Promise<SystemScript[]> {
    return [...(DEMO_SYSTEM_SCRIPTS_BY_BOT[botAlias] || [])];
  }

  async runSystemScript(botAlias: string, scriptName: string): Promise<SystemScriptResult> {
    return {
      scriptName,
      success: true,
      output: `${botAlias}:${scriptName} 执行完成（Mock）`,
    };
  }

  async runSystemScriptStream(botAlias: string, scriptName: string, onLog: (line: string) => void): Promise<SystemScriptResult> {
    const logs = [
      "cd scripts",
      scriptName,
      "系统功能执行完成",
    ];
    for (const line of logs) {
      onLog(line);
      await new Promise((resolve) => setTimeout(resolve, 40));
    }
    return {
      scriptName,
      success: true,
      output: `${botAlias}:${scriptName} 执行完成（Mock）`,
    };
  }
}

export async function streamAssistantReply(onChunk: (chunk: string) => void) {
  const chunks = ["我先看一下问题。", "已经定位到可能原因。", "建议先检查 session 与工作目录。"];
  for (const chunk of chunks) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    onChunk(chunk);
  }
}
