// Scenes for `npm run tutorial:shots`. Each scene drives the mock app to one state:
//   { chapter, shot, fresh?, run(page), hotspots: { name: (page) => locator | locator[] } }
// Scenes of a chapter share one page in order; `fresh: true` starts from a newly opened workbench.
// Only mock data may appear: never point this at a real host.

/** Every scene sees this wall-clock time, so timestamps in the screenshots are stable. */
export const FIXED_TIME = new Date("2026-03-18T10:24:00+08:00");

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

const DEMO_PRESETS = [
  { title: "代码审查", content: "审查当前改动，按严重程度列出问题，并给出修改建议。" },
  { title: "补充测试", content: "为刚才的改动补充单元测试，运行并报告结果。" },
];

async function fillDemoQuestion(page) {
  await composer(page).locator('textarea[name="message"]').fill(DEMO_QUESTION);
}

const lastAssistantRow = (page) => chatPane(page).getByTestId("chat-message-row").last();

export const SCENES = [
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
