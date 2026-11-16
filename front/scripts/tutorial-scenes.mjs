// Scenes for `npm run tutorial:shots`. Each scene drives the mock app to one state:
//   { chapter, shot, fresh?, user?, loggedOut?, run(page), hotspots: { name: (page) => locator | locator[] } }
// Scenes of a chapter share one page in order; `fresh: true` starts from a newly opened workbench.
// `user` logs in under another name (the mock treats "127.0.0.1" as the local administrator) and
// `loggedOut` stays on the login page. Only mock data may appear: never point this at a real host.

/** Every scene sees this wall-clock time, so timestamps in the screenshots are stable. */
export const FIXED_TIME = new Date("2026-03-18T10:24:00+08:00");

/** All screenshots use one theme preset: 阿波罗计划 (light). The id comes from bot/web/theme_presets.json. */
export const CAPTURE_THEME_ID = "theme_0f2e4a8c1d6b4f90a3c7e5b2d8f1046a";

const PROMPT = "\x1b[32mdemo@orbit\x1b[0m:\x1b[34m~/orbit-safe-claw\x1b[0m$ ";

/** Canned output for terminal tabs, in the order the tabs are started (the mock has no shell). */
export const TERMINAL_OUTPUTS = [
  `${PROMPT}npm run build\r\n\r\n> orbit-safe-claw@3.1.2 build\r\n> vite build\r\n\r\nvite v6.4.2 building for production...\r\n\x1b[32m✓\x1b[0m 1284 modules transformed.\r\n\x1b[32m✓ built in 12.6s\x1b[0m\r\n${PROMPT}`,
  `${PROMPT}git status --short\r\n M bot/web/server.py\r\n?? front/src/screens/GitScreen.tsx\r\n${PROMPT}`,
];

const chatPane = (page) => page.getByTestId("desktop-pane-chat");
const composer = (page) => chatPane(page).locator("form").filter({ has: page.locator('textarea[name="message"]') });

const DEMO_QUESTION = "帮我检查 README 里的安装步骤是否完整";

// Scripted mock turn (see src/mocks/chatScript.ts): a reply with tool calls, results and context usage.
const DEMO_CHAT_SCRIPT = {
  chunks: [
    "安装步骤缺少 Node.js 版本要求。",
    "我在「快速开始」一节补充了 Node.js 22.13+ 的说明，其余三条启动命令核对无误。",
  ],
  trace: [
    { id: "demo-1", sequence: 1, kind: "commentary", summary: "先阅读 README.md 的安装部分。", source: "codex" },
    {
      id: "demo-2",
      sequence: 2,
      kind: "tool_call",
      toolName: "shell",
      summary: "sed -n '60,120p' README.md",
      callId: "demo-call-1",
      source: "codex",
      payload: { command: "sed -n '60,120p' README.md" },
    },
    {
      id: "demo-3",
      sequence: 3,
      kind: "tool_result",
      summary: "## 快速开始",
      callId: "demo-call-1",
      source: "codex",
      payload: { output: "## 快速开始\n\nbash install.sh\nbash start.sh\npython -m bot" },
    },
    { id: "demo-4", sequence: 4, kind: "commentary", summary: "安装步骤没有写 Node.js 版本，补充一行说明。", source: "codex" },
    {
      id: "demo-5",
      sequence: 5,
      kind: "tool_call",
      toolName: "apply_patch",
      summary: "更新 README.md",
      callId: "demo-call-2",
      source: "codex",
      payload: { input: "*** Update File: README.md\n+前端依赖需要 Node.js 22.13+。" },
    },
    {
      id: "demo-6",
      sequence: 6,
      kind: "tool_result",
      summary: "Success. Updated README.md",
      callId: "demo-call-2",
      source: "codex",
      payload: { output: "Success. Updated the following files:\nM README.md" },
    },
  ],
  contextUsage: {
    provider: "codex",
    usedTokens: 48200,
    contextWindow: 272000,
    contextLeftPercent: 82,
    contextUsedPercent: 18,
    usedDisplay: "48.2k",
    windowDisplay: "272k",
  },
};

const DEMO_CLUSTER_TEAM = {
  version: 1,
  assignments: [
    { agentId: "implementer", name: "实现", responsibility: "修改代码并自测", assignmentRevision: 1 },
    { agentId: "tester", name: "测试", responsibility: "补充并运行测试", assignmentRevision: 1 },
    { agentId: "reviewer", name: "审查", responsibility: "检查改动的风险", assignmentRevision: 1 },
  ],
};

const DEMO_PRESETS = [
  { title: "代码审查", content: "审查当前改动，按严重程度列出问题，并给出修改建议。" },
  { title: "补充测试", content: "为刚才的改动补充单元测试，运行并报告结果。" },
];

// The "用好 Agent" chapter: a task description written the recommended way, and the plan it leads to.
const PRACTICE_PROMPT = [
  "目标：登录后应回到登录前打开的页面，现在总是跳回首页。",
  "范围：front/src/screens/LoginScreen.tsx 和路由守卫，不改后端接口。",
  "完成标准：补一个回归测试，运行 npm test 并报告结果。",
].join("\n");

const PRACTICE_PLAN_REQUEST = "登录后回到原页面：先给出修改方案";

const PRACTICE_PLAN = `# 登录后回到原页面

## 目标
登录后回到原页面，不再跳回首页。

## 步骤
1. 补一个回归测试复现问题。
2. 路由守卫记录原页面并跳回。
3. 运行 npm test，清理无用代码。

## 执行方式
逐步执行：每完成一步运行验证、汇报结果并暂停，等我确认后再继续。
`;

const PRACTICE_AGENTS_MD = `# 项目约定

## 常用命令
- 安装依赖：npm ci
- 运行测试：npm test
- 构建：npm run build

## 代码约定
- 页面组件放在 front/src/screens/，测试放在 front/src/test/。
- 修改接口时同步更新 docs/api.md。

## 注意
- 不要修改 .env 和 data/ 下的文件。
- 完成后运行测试并报告结果。
`;

async function fillDemoQuestion(page) {
  await composer(page).locator('textarea[name="message"]').fill(DEMO_QUESTION);
}

async function sendDemoQuestion(page) {
  await page.evaluate((script) => {
    window.__ORBIT_MOCK_CHAT_SCRIPT__ = script;
  }, DEMO_CHAT_SCRIPT);
  await fillDemoQuestion(page);
  await chatPane(page).getByRole("button", { name: "发送", exact: true }).click();
}

const lastAssistantRow = (page) => chatPane(page).getByTestId("chat-message-row").last();

const sidebar = (page) => page.getByTestId("desktop-pane-files");
const editorPane = (page) => page.getByTestId("desktop-pane-editor");
const terminalPane = (page) => page.getByTestId("desktop-pane-terminal");
const exact = (page, name) => page.getByRole("button", { name, exact: true });

const DEMO_README = `# Orbit Safe Claw

在浏览器里使用本机的 Codex、Claude 等 CLI。

## 快速开始

1. 运行 \`bash install.sh\`
2. 运行 \`bash start.sh\`
3. 打开 http://127.0.0.1:8765

## 目录

- \`bot/\`：后端与 Web API
- \`front/\`：React 前端
- \`tests/\`：后端测试
`;

/** Replaces the active editor's text (the mock files only hold placeholder lines) and saves it. */
async function writeEditorText(page, text) {
  await editorPane(page).locator(".cm-content").first().click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.insertText(text);
  await page.keyboard.press("ControlOrMeta+S");
}

async function openBotSwitcher(page) {
  await page.getByRole("button", { name: "切换 Bot: main" }).click();
  await exact(page, "关闭智能体切换").waitFor();
}

async function openAgentManager(page) {
  await openBotSwitcher(page);
  await exact(page, "智能体管理").click();
  await exact(page, "新增智能体").waitFor();
}

async function openAdminCenter(page, tab) {
  await openBotSwitcher(page);
  await exact(page, "管理中心").click();
  await page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
}

export const SCENES = [
  // ----------------------------------------------------------------- start
  {
    chapter: "start",
    shot: "login",
    loggedOut: true,
    async run() {},
    hotspots: {
      form: (page) => [page.getByText("接入控制台", { exact: true }), exact(page, "以 guest 进入")],
    },
  },
  {
    chapter: "start",
    shot: "workbench",
    async run(page) {
      await exact(page, "打开 README.md").click();
      await editorPane(page).getByText("README.md").first().waitFor();
    },
    hotspots: {
      context: (page) => [exact(page, "使用教程"), page.getByRole("navigation", { name: "工作区位置" })],
      rail: (page) => [sidebar(page).getByRole("button", { name: "文件", exact: true }), sidebar(page).getByRole("button", { name: "设置", exact: true })],
      statusbar: (page) => page.getByTestId("desktop-workbench-statusbar"),
    },
  },
  {
    chapter: "start",
    shot: "switcher",
    async run(page) {
      await openBotSwitcher(page);
    },
    hotspots: {
      panel: (page) => [page.getByPlaceholder("搜索智能体、目录、agent"), exact(page, "关闭智能体切换"), exact(page, "管理中心")],
    },
  },
  {
    chapter: "start",
    shot: "manager",
    async run(page) {
      await exact(page, "智能体管理").click();
      await exact(page, "新增智能体").waitFor();
    },
    hotspots: {
      list: (page) => page.getByTestId("desktop-bot-manager-list"),
    },
  },
  {
    chapter: "start",
    shot: "create",
    async run(page) {
      await exact(page, "新增智能体").click();
      await page.getByLabel("新智能体别名", { exact: true }).fill("team3");
      await page.getByLabel("新智能体工作目录", { exact: true }).fill("/Users/demo/orbit-safe-claw/docs");
    },
    hotspots: {
      form: (page) => [exact(page, "取消新增智能体"), exact(page, "创建智能体"), page.getByLabel("新智能体别名", { exact: true })],
    },
  },

  // ------------------------------------------------------------------ chat
  {
    chapter: "chat",
    shot: "composer",
    fresh: true,
    async run(page) {
      await fillDemoQuestion(page);
    },
    hotspots: {
      composer: (page) => composer(page),
      toolbar: (page) => page.getByTestId("chat-composer-toolbar"),
    },
  },
  {
    chapter: "chat",
    shot: "running",
    async run(page) {
      await page.evaluate((script) => {
        window.__ORBIT_MOCK_CHAT_SCRIPT__ = script;
      }, DEMO_CHAT_SCRIPT);
      // Freeze timers so the mock turn stays in the running state, then let the first tool call arrive.
      await page.clock.install({ time: FIXED_TIME });
      await page.clock.pauseAt(new Date(FIXED_TIME.getTime() + 1000));
      await chatPane(page).getByRole("button", { name: "发送", exact: true }).click();
      await page.clock.runFor(400);
      await chatPane(page).getByRole("button", { name: "终止任务", exact: true }).waitFor();
    },
    hotspots: {
      stop: (page) => chatPane(page).getByRole("button", { name: "终止任务", exact: true }),
    },
  },
  {
    chapter: "chat",
    shot: "answer",
    async run(page) {
      await page.clock.resume();
      await page.clock.setFixedTime(new Date(FIXED_TIME.getTime() + 60_000));
      // The context badge appears once the turn has finished.
      await chatPane(page).getByRole("button", { name: /^View context details/ }).waitFor();
      await chatPane(page).getByRole("button", { name: "展开过程详情" }).click();
      await lastAssistantRow(page).getByText("过程 1", { exact: true }).click();
    },
    hotspots: {
      answer: (page) => lastAssistantRow(page),
      continue: (page) => lastAssistantRow(page).getByRole("button", { name: "继续", exact: true }),
    },
  },
  {
    chapter: "chat",
    shot: "history",
    async run(page) {
      const openHistory = () => chatPane(page).getByRole("button", { name: "历史会话", exact: true }).click();
      // Start a second conversation first, so the list shows that the earlier one is kept.
      await openHistory();
      await page.getByRole("button", { name: "新会话", exact: true }).click();
      await chatPane(page).getByText("暂无消息，开始聊天吧").waitFor();
      await openHistory();
      await page.getByRole("button", { name: "清空", exact: true }).waitFor();
    },
    hotspots: {
      panel: (page) => [
        page.getByText("历史会话", { exact: true }),
        page.getByRole("button", { name: "关闭历史会话" }).first(),
        page.getByRole("button", { name: /^当前会话/ }),
      ],
    },
  },
  {
    chapter: "chat",
    shot: "presets",
    async run(page) {
      const closeHistory = page.getByRole("button", { name: "关闭历史会话" }).first();
      if (await closeHistory.isVisible()) {
        await closeHistory.click();
      }
      // The mock starts without presets: add two in the sidebar settings, as a user would.
      const sidebar = page.getByTestId("desktop-pane-files");
      await page.getByRole("button", { name: "设置", exact: true }).click();
      for (const [index, preset] of DEMO_PRESETS.entries()) {
        await sidebar.getByRole("button", { name: "新增预设", exact: true }).click();
        await sidebar.getByLabel(`当前智能体预设标题 ${index + 1}`, { exact: true }).fill(preset.title);
        await sidebar.getByLabel(`当前智能体预设内容 ${index + 1}`, { exact: true }).fill(preset.content);
      }
      await sidebar.getByRole("button", { name: "保存当前预设", exact: true }).click();
      await sidebar.getByRole("button", { name: "保存当前预设", exact: true }).waitFor({ state: "detached" });
      await page.getByRole("button", { name: "文件", exact: true }).click();
      await chatPane(page).getByRole("button", { name: "打开提示词预设", exact: true }).click();
      await page.getByRole("listbox", { name: "提示词预设" }).getByRole("option").first().waitFor();
    },
    hotspots: {
      menu: (page) => page.getByRole("listbox", { name: "提示词预设" }),
    },
  },

  // ----------------------------------------------------------------- files
  {
    chapter: "files",
    shot: "tree",
    fresh: true,
    async run(page) {
      await exact(page, "展开 docs").click();
      await exact(page, "展开 src").click();
      await exact(page, "打开 src/server.ts").waitFor();
    },
    hotspots: {
      actions: (page) => [exact(page, "新建文件"), exact(page, "更多文件操作")],
      tree: (page) => [exact(page, "收起 docs"), exact(page, "打开 package.json")],
    },
  },
  {
    chapter: "files",
    shot: "menu",
    async run(page) {
      await exact(page, "打开 README.md").click({ button: "right" });
      await page.getByRole("menu").waitFor();
    },
    hotspots: {
      menu: (page) => page.getByRole("menu"),
    },
  },
  {
    chapter: "files",
    shot: "split",
    async run(page) {
      await page.keyboard.press("Escape");
      await exact(page, "打开 README.md").click();
      await editorPane(page).getByText("README.md").first().waitFor();
      await writeEditorText(page, DEMO_README);
      // Reopen the tab: the editor keeps a "已保存" notice over the first line after a save.
      await editorPane(page).getByText("已保存", { exact: true }).waitFor();
      await exact(page, "关闭 README.md").click();
      await exact(page, "打开 README.md").click();
      await editorPane(page).getByText("# Orbit Safe Claw").first().waitFor();
      await exact(page, "打开 src/server.ts").click({ button: "right" });
      await page.getByRole("menu").getByText("在右侧打开", { exact: true }).click();
      await editorPane(page).getByText("server.ts").first().waitFor();
    },
    hotspots: {
      editor: (page) => editorPane(page),
      statusbar: (page) => page.getByTestId("desktop-workbench-statusbar"),
    },
  },
  {
    chapter: "files",
    shot: "preview",
    async run(page) {
      await editorPane(page).getByRole("button", { name: "切换到预览", exact: true }).first().click();
      await editorPane(page).getByRole("heading", { name: "快速开始" }).waitFor();
    },
    hotspots: {
      preview: (page) => editorPane(page),
    },
  },
  {
    chapter: "files",
    shot: "search",
    async run(page) {
      await sidebar(page).getByRole("button", { name: "搜索", exact: true }).click();
      await sidebar(page).getByLabel("全文搜索", { exact: true }).fill("install");
      await sidebar(page).getByRole("button", { name: /^打开 .+ 第 \d+ 行$/ }).first().waitFor();
    },
    hotspots: {
      search: (page) => sidebar(page),
    },
  },

  // -------------------------------------------------------------- terminal
  {
    chapter: "terminal",
    shot: "tabs",
    fresh: true,
    async run(page) {
      await terminalPane(page).getByRole("button", { name: "构建", exact: true }).last().click();
      await exact(page, "关闭构建").waitFor();
      await exact(page, "新建终端").click();
      await exact(page, "关闭终端 2").waitFor();
      await terminalPane(page).getByText("git status --short").waitFor();
    },
    hotspots: {
      strip: (page) => [terminalPane(page).getByText("终端 1", { exact: true }), exact(page, "新建终端")],
      close: (page) => exact(page, "关闭终端 2"),
      actions: (page) => [terminalPane(page).getByRole("button", { name: "构建", exact: true }).last(), exact(page, "编辑快捷命令")],
    },
  },
  {
    chapter: "terminal",
    shot: "actions",
    async run(page) {
      await exact(page, "编辑快捷命令").click();
      await exact(page, "保存快捷命令").waitFor();
    },
    hotspots: {
      dialog: (page) => [page.getByText("终端快捷命令", { exact: true }), exact(page, "新增快捷命令"), exact(page, "保存快捷命令")],
    },
  },

  // ------------------------------------------------------------------- git
  {
    chapter: "git",
    shot: "overview",
    fresh: true,
    async run(page) {
      await sidebar(page).getByRole("button", { name: "Git", exact: true }).click();
      await exact(page, "提交更改").waitFor();
    },
    hotspots: {
      sync: (page) => [exact(page, "Fetch"), exact(page, "刷新 Git 状态")],
      commit: (page) => [exact(page, "生成 commit message"), exact(page, "提交更改"), exact(page, "智能提交")],
      changes: (page) => [exact(page, "暂存全部"), exact(page, "丢弃 front/src/screens/GitScreen.tsx"), exact(page, "打开 diff bot/web/server.py")],
    },
  },
  {
    chapter: "git",
    shot: "diff",
    async run(page) {
      await exact(page, "打开 diff bot/web/server.py").click();
      await editorPane(page).getByText("server.py").first().waitFor();
    },
    hotspots: {
      diff: (page) => editorPane(page),
    },
  },
  {
    chapter: "git",
    shot: "branches",
    async run(page) {
      await exact(page, "刷新分支").scrollIntoViewIfNeeded();
      await exact(page, "收起提交图").scrollIntoViewIfNeeded();
    },
    hotspots: {
      graph: (page) => [exact(page, "收起提交图"), exact(page, "重置到此提交")],
    },
  },
  {
    chapter: "git",
    shot: "remotes",
    async run(page) {
      await exact(page, "收起分支").evaluate((element) => element.scrollIntoView({ block: "start" }));
    },
    hotspots: {
      branches: (page) => [exact(page, "收起分支"), page.getByRole("button", { name: /^feature\/git-panel def5678/ })],
      remotes: (page) => [exact(page, "收起远端"), exact(page, "添加远端")],
      stash: (page) => [exact(page, "收起Stash"), exact(page, "删除 stash@{0}")],
    },
  },
  {
    chapter: "git",
    shot: "github",
    async run(page) {
      await exact(page, "关联 GitHub 仓库").first().click();
      const login = exact(page, "通过浏览器登录 GitHub");
      await login.waitFor();
      await login.evaluate((element) => element.scrollIntoView({ block: "center" }));
    },
    hotspots: {
      panel: (page) => [
        sidebar(page).getByText("关联 GitHub 仓库", { exact: true }).last(),
        exact(page, "通过浏览器登录 GitHub"),
        sidebar(page).getByText(/^令牌按当前 Orbit 账号加密保存/),
      ],
    },
  },

  // --------------------------------------------------------------- cluster
  {
    chapter: "cluster",
    shot: "toggle",
    fresh: true,
    async run(page) {
      await exact(page, "开启集群模式").click();
      await exact(page, "关闭集群模式").waitFor();
    },
    hotspots: {
      toggle: (page) => exact(page, "关闭集群模式"),
    },
  },
  {
    chapter: "cluster",
    shot: "team",
    async run(page) {
      // The mock reports this team for conversations created while the script is set.
      await page.evaluate((script) => {
        window.__ORBIT_MOCK_CHAT_SCRIPT__ = script;
      }, { ...DEMO_CHAT_SCRIPT, clusterTeam: DEMO_CLUSTER_TEAM });
      await exact(page, "历史会话").click();
      await exact(page, "新会话").first().click();
      await exact(page, "展开集群编组").click();
      await page.getByTestId("cluster-team-assignment").first().waitFor();
    },
    hotspots: {
      team: (page) => page.getByTestId("cluster-team-panel"),
    },
  },
  {
    chapter: "cluster",
    shot: "settings",
    async run(page) {
      await sidebar(page).getByRole("button", { name: "设置", exact: true }).click();
      await sidebar(page).getByRole("button", { name: "集群", exact: true }).click();
      await exact(page, "保存集群配置").waitFor();
    },
    hotspots: {
      mode: (page) => [
        sidebar(page).getByRole("heading", { name: "集群模式", exact: true }),
        sidebar(page).getByText("默认超时（秒）", { exact: true }).locator("xpath=.."),
      ],
    },
  },
  {
    chapter: "cluster",
    shot: "tiers",
    async run(page) {
      await sidebar(page).getByRole("heading", { name: "集群模型档位", exact: true }).evaluate((element) => element.scrollIntoView({ block: "start" }));
    },
    hotspots: {
      tiers: (page) => sidebar(page).getByRole("heading", { name: "集群模型档位", exact: true }).locator("xpath=.."),
    },
  },

  // -------------------------------------------------------------- practice
  {
    chapter: "practice",
    shot: "workspace",
    fresh: true,
    async run(page) {
      await openAgentManager(page);
      await exact(page, "新增智能体").click();
      await page.getByLabel("新智能体别名", { exact: true }).fill("shop-web");
      await page.getByLabel("新智能体工作目录", { exact: true }).fill("/Users/demo/projects/shop-web");
    },
    hotspots: {
      workdir: (page) => page.getByLabel("新智能体工作目录", { exact: true }).locator("xpath=ancestor::div[contains(@class, 'am-create-row')][1]"),
    },
  },
  {
    chapter: "practice",
    shot: "prompt",
    fresh: true,
    async run(page) {
      await composer(page).locator('textarea[name="message"]').fill(PRACTICE_PROMPT);
    },
    hotspots: {
      composer: (page) => composer(page),
    },
  },
  {
    chapter: "practice",
    shot: "plan",
    async run(page) {
      await composer(page).locator('textarea[name="message"]').fill(PRACTICE_PLAN_REQUEST);
      await chatPane(page).getByRole("button", { name: "计划模式", exact: true }).click();
      await chatPane(page).getByRole("button", { name: "发送", exact: true }).click();
      await chatPane(page).getByRole("button", { name: "执行方案", exact: true }).waitFor();
    },
    hotspots: {
      card: (page) => lastAssistantRow(page),
    },
  },
  {
    chapter: "practice",
    shot: "pace",
    async run(page) {
      await chatPane(page).getByRole("button", { name: "修改方案", exact: true }).click();
      const editor = chatPane(page).getByLabel("方案内容", { exact: true });
      await editor.fill(PRACTICE_PLAN);
      await editor.blur();
      // As if the user dragged the resize handle: the whole plan is visible instead of its last lines.
      await editor.evaluate((element) => {
        element.style.height = `${element.scrollHeight + 4}px`;
        element.scrollTop = 0;
        element.scrollIntoView({ block: "end" });
      });
    },
    hotspots: {
      editor: (page) => chatPane(page).getByLabel("方案内容", { exact: true }),
    },
  },
  {
    chapter: "practice",
    shot: "cluster",
    fresh: true,
    async run(page) {
      await page.evaluate((script) => {
        window.__ORBIT_MOCK_CHAT_SCRIPT__ = script;
      }, { ...DEMO_CHAT_SCRIPT, clusterTeam: DEMO_CLUSTER_TEAM });
      await exact(page, "开启集群模式").click();
      await exact(page, "关闭集群模式").waitFor();
      await chatPane(page).getByRole("button", { name: "计划模式", exact: true }).click();
      await exact(page, "历史会话").click();
      await exact(page, "新会话").first().click();
      await exact(page, "展开集群编组").click();
      await page.getByTestId("cluster-team-assignment").first().waitFor();
    },
    hotspots: {
      team: (page) => page.getByTestId("cluster-team-panel"),
    },
  },
  {
    chapter: "practice",
    shot: "context",
    fresh: true,
    async run(page) {
      await sendDemoQuestion(page);
      const ctx = chatPane(page).getByRole("button", { name: /^View context details/ });
      await ctx.waitFor();
      await ctx.focus();
      await page.getByRole("tooltip").waitFor();
    },
    hotspots: {
      ctx: (page) => [chatPane(page).getByRole("button", { name: /^View context details/ }), page.getByRole("tooltip")],
    },
  },
  {
    chapter: "practice",
    shot: "memory",
    fresh: true,
    async run(page) {
      await exact(page, "新建文件").click();
      await page.getByRole("dialog").getByRole("textbox").fill("AGENTS.md");
      await page.getByRole("dialog").getByRole("button", { name: "创建", exact: true }).click();
      await exact(page, "打开 AGENTS.md").waitFor();
      await exact(page, "打开 AGENTS.md").click();
      await editorPane(page).getByText("AGENTS.md").first().waitFor();
      await writeEditorText(page, PRACTICE_AGENTS_MD);
      // Reopen the tab: the editor keeps a "已保存" notice over the first line after a save.
      await editorPane(page).getByText("已保存", { exact: true }).waitFor();
      await exact(page, "关闭 AGENTS.md").click();
      await exact(page, "打开 AGENTS.md").click();
      await editorPane(page).getByText("# 项目约定").first().waitFor();
    },
    hotspots: {
      file: (page) => editorPane(page),
    },
  },

  // ---------------------------------------------------------------- remote
  {
    chapter: "remote",
    shot: "form",
    fresh: true,
    async run(page) {
      await openAgentManager(page);
      await exact(page, "新增智能体").click();
      await page.getByLabel("新智能体别名", { exact: true }).fill("build-box");
      await exact(page, "远程 SSH").click();
      await page.getByPlaceholder("主机名或 IP 地址").fill("build.example.com");
      await page.getByPlaceholder("远程登录用户名").fill("deploy");
      await exact(page, "远程 SSH").evaluate((element) => element.scrollIntoView({ block: "start" }));
    },
    hotspots: {
      location: (page) => [exact(page, "本地"), exact(page, "远程 SSH")],
      connection: (page) => [page.getByText("连接信息", { exact: true }), page.getByPlaceholder("远程登录用户名"), page.getByPlaceholder("主机名或 IP 地址")],
    },
  },
  {
    chapter: "remote",
    shot: "auth",
    async run(page) {
      await exact(page, "测试并连接 SSH").evaluate((element) => element.scrollIntoView({ block: "end" }));
    },
    hotspots: {
      auth: (page) => [page.getByText("身份验证", { exact: true }), page.getByText("加密保存在服务端，重启后仍可连接。", { exact: true })],
      connect: (page) => exact(page, "测试并连接 SSH"),
    },
  },

  // -------------------------------------------------------------- gateways
  {
    chapter: "gateways",
    shot: "page",
    fresh: true,
    user: "127.0.0.1",
    async run(page) {
      await openAdminCenter(page, "消息网关");
      await exact(page, "开始扫码").waitFor();
    },
    hotspots: {
      tab: (page) => page.getByRole("tab", { name: /^消息网关/ }),
      weixin: (page) => [page.getByText("微信启用：否", { exact: false }).first(), exact(page, "开始扫码"), page.getByText("微信白名单用户", { exact: false }).first()],
    },
  },
  {
    chapter: "gateways",
    shot: "telegram",
    user: "127.0.0.1",
    async run(page) {
      await page.getByText("Telegram 配置", { exact: true }).evaluate((element) => element.scrollIntoView({ block: "start" }));
    },
    hotspots: {
      telegram: (page) => page.getByText("Telegram 配置", { exact: true }).locator("xpath=.."),
    },
  },

  // ----------------------------------------------------------------- admin
  {
    chapter: "admin",
    shot: "home",
    fresh: true,
    user: "127.0.0.1",
    async run(page) {
      await openAdminCenter(page, "全局配置");
      await page.getByText("界面与通知", { exact: true }).waitFor();
    },
    hotspots: {
      nav: (page) => page.getByRole("navigation", { name: "管理中心导航" }),
      theme: (page) => [page.getByText("界面主题", { exact: true }), page.getByText("Enter 键发送消息", { exact: true })],
    },
  },
  {
    chapter: "admin",
    shot: "users",
    user: "127.0.0.1",
    async run(page) {
      await page.getByRole("tab", { name: /^用户/ }).click();
      await page.getByText("用户权限", { exact: true }).waitFor();
    },
    hotspots: {
      users: (page) => [page.getByText("用户权限", { exact: true }), page.getByText("可操作 Bot", { exact: true }).first()],
    },
  },
  {
    chapter: "admin",
    shot: "invites",
    user: "127.0.0.1",
    async run(page) {
      await page.getByRole("tab", { name: /^邀请/ }).click();
      await exact(page, "生成邀请码").waitFor();
    },
    hotspots: {
      invites: (page) => [exact(page, "生成邀请码"), page.getByText("邀请码列表", { exact: true }), exact(page, "删除")],
    },
  },
  {
    chapter: "admin",
    shot: "network",
    user: "127.0.0.1",
    async run(page) {
      await page.getByRole("tab", { name: /^网络与升级/ }).click();
      await exact(page, "检查更新").waitFor();
    },
    hotspots: {
      tunnel: (page) => [page.getByText("公网访问", { exact: true }).first(), exact(page, "重启 Tunnel")],
      update: (page) => [page.getByText("程序版本", { exact: true }), exact(page, "检查更新")],
    },
  },
  {
    chapter: "admin",
    shot: "plugins",
    user: "127.0.0.1",
    async run(page) {
      await exact(page, "返回").click();
      await sidebar(page).getByRole("button", { name: "插件", exact: true }).click();
      await exact(page, "安装插件").waitFor();
    },
    hotspots: {
      plugins: (page) => sidebar(page),
    },
  },

  // ------------------------------------------------------------------ tips
  {
    chapter: "tips",
    shot: "shortcuts",
    fresh: true,
    async run(page) {
      await editorPane(page).getByText("快速打开文件", { exact: true }).waitFor();
    },
    hotspots: {
      card: (page) => [editorPane(page).getByText("未打开文件", { exact: true }), editorPane(page).getByText("Ctrl+Shift+F", { exact: true })],
      focus: (page) => exact(page, "聚焦终端"),
    },
  },
  {
    chapter: "tips",
    shot: "slash",
    async run(page) {
      await composer(page).locator('textarea[name="message"]').fill("//compact");
    },
    hotspots: {
      composer: (page) => composer(page),
    },
  },
  {
    chapter: "tips",
    shot: "answer",
    async run(page) {
      await sendDemoQuestion(page);
      await chatPane(page).getByRole("button", { name: /^View context details/ }).waitFor();
    },
    hotspots: {
      continue: (page) => lastAssistantRow(page).getByRole("button", { name: "继续", exact: true }),
    },
  },
  {
    chapter: "tips",
    shot: "gateway",
    fresh: true,
    user: "127.0.0.1",
    async run(page) {
      await openAdminCenter(page, "消息网关");
      await exact(page, "开始扫码").waitFor();
    },
    hotspots: {},
  },

  // ---------------------------------------------------------------- layout
  {
    chapter: "layout",
    shot: "overview",
    fresh: true,
    async run(page) {
      await page.getByRole("button", { name: "打开 README.md", exact: true }).click();
      await page.getByTestId("desktop-pane-editor").getByText("README.md").first().waitFor();
    },
    hotspots: {
      toggles: (page) => page.getByRole("group", { name: "布局开关" }),
      viewMode: (page) => page.getByLabel("视图模式", { exact: true }),
    },
  },
  {
    chapter: "layout",
    shot: "menu",
    async run(page) {
      await page.getByRole("button", { name: "窗口布局", exact: true }).click();
      await page.getByRole("dialog", { name: "窗口布局" }).waitFor();
    },
    hotspots: {
      menu: (page) => page.getByRole("dialog", { name: "窗口布局" }),
    },
  },
  {
    chapter: "layout",
    shot: "rearrange",
    async run(page) {
      await page.getByRole("dialog", { name: "窗口布局" }).getByRole("button", { name: "调整窗口位置…", exact: true }).click();
      await page.getByRole("toolbar", { name: "窗口布局编辑" }).waitFor();
    },
    hotspots: {
      banner: (page) => page.getByRole("toolbar", { name: "窗口布局编辑" }),
    },
  },
  {
    chapter: "layout",
    shot: "focus",
    async run(page) {
      await page.getByRole("toolbar", { name: "窗口布局编辑" }).getByRole("button", { name: "完成", exact: true }).click();
      await page.getByRole("button", { name: "聚焦编辑器", exact: true }).click();
      await page.getByRole("button", { name: "退出聚焦编辑器", exact: true }).first().waitFor();
    },
    hotspots: {
      button: (page) => page.getByRole("button", { name: "退出聚焦编辑器", exact: true }).first(),
    },
  },
  {
    chapter: "layout",
    shot: "palette",
    async run(page) {
      await page.getByRole("button", { name: "退出聚焦编辑器", exact: true }).first().click();
      await page.keyboard.press("Control+P");
      const palette = page.getByRole("dialog", { name: "命令面板" });
      await palette.getByPlaceholder("输入命令或文件名").fill("read");
      await palette.getByRole("button", { name: /^打开 / }).first().waitFor();
    },
    hotspots: {
      palette: (page) => page.getByRole("dialog", { name: "命令面板" }),
    },
  },
];
