export type GuideSectionTone = "primary" | "green" | "amber" | "cyan";

export type GuideChapterId =
  | "model-capability"
  | "overview"
  | "chat"
  | "agents"
  | "workspace"
  | "desktop-workbench"
  | "terminal"
  | "debug"
  | "git"
  | "plugins"
  | "assistant-ops"
  | "settings"
  | "bot-management"
  | "admin-center"
  | "global"
  | "updates";

export type GuideArticle = {
  title: string;
  entry: string;
  scenario: string;
  actions: string[];
  notes: string[];
};

export type GuideChapter = {
  id: GuideChapterId;
  title: string;
  description: string;
  tone: GuideSectionTone;
  items: GuideArticle[];
};

export const aiCapabilityGuideUpdatedAt = "2026-05-27";

export const guideTitle = "智能体协作开发指南";

export const guideLead =
  "本页是项目模块用法指南，覆盖登录、聊天、文件、终端、Git、插件、运维、设置和管理入口。";

export const guideRoute = ["提升模型能力", "按模块找入口", "按权限和 Bot 模式排查"];

export const guideChapters: GuideChapter[] = [
  {
    id: "model-capability",
    title: "提升模型能力",
    description: "用更清楚的目标、上下文、工具和验收方式，让智能体更像可靠协作者。",
    tone: "cyan",
    items: [
      {
        title: "把任务讲清",
        entry: "聊天输入框、方案执行消息、prompt preset。",
        scenario: "适合需求容易被误解、任务跨多个模块、需要稳定交付时。",
        actions: [
          "说明目标、成功标准、禁止范围、相关路径和验收命令。",
          "把必须保留、允许调整、需要新增的内容分开写。",
          "边界不确定时，要求智能体先停下说明冲突。",
        ],
        notes: [
          "避免一次混入多个无关目标。",
          "不要只说“优化一下”，要说明你接受什么结果。",
          "边界冲突时先澄清，再实施。",
        ],
      },
      {
        title: "给足上下文",
        entry: "聊天附件、文件引用、文件树、搜索、trace。",
        scenario: "适合智能体需要理解真实代码、日志、截图、diff 时。",
        actions: [
          "给出相关路径、报错、复现步骤、相关提交或截图说明。",
          "要求先读文件、搜索引用、看 trace，再给判断。",
          "把你已确认的事实和仍不确定的猜测分开。",
        ],
        notes: [
          "不要只描述印象。",
          "截图、日志、diff 要说明来源和触发动作。",
          "结论应能追溯到文件、命令或对话证据。",
        ],
      },
      {
        title: "让工具补强判断",
        entry: "文件、搜索、大纲、终端、Git、插件、调试。",
        scenario: "适合降低猜测、验证事实、复核风险时。",
        actions: [
          "要求搜索引用、阅读实现、运行测试、查看 diff。",
          "需要专用视图时打开插件预览或调试面板。",
          "让智能体把结论绑定到命令、文件、diff 或视图证据。",
        ],
        notes: [
          "工具输出比口头判断更可靠。",
          "失败命令也要保留关键输出。",
          "没有验证时，应明确标成风险。",
        ],
      },
      {
        title: "分步迭代和验收",
        entry: "聊天、计划模式、子 Agent、Cluster、Git。",
        scenario: "适合任务较大、结果需合并、需要 reviewer 视角时。",
        actions: [
          "先分析，再实施，再验证。",
          "复杂任务拆给子 Agent，由主线合并和验收。",
          "最终列出改动、验证、剩余风险。",
        ],
        notes: [
          "不要要求泛泛重做。",
          "反馈时说明保留、调整、新增和验证项。",
          "多个 Agent 不应写同一文件或重复同件事。",
        ],
      },
    ],
  },
  {
    id: "overview",
    title: "总览",
    description: "先判断当前端、权限、Bot 模式，再找功能入口。",
    tone: "primary",
    items: [
      {
        title: "入口和显示规则",
        entry: "桌面端用左侧活动栏、顶部 Bot 切换器和状态栏；移动端用底部导航和 Bot 面板。",
        scenario: "适合刚进入系统、找不到入口、或同个账号在不同设备看到不同功能时。",
        actions: [
          "切换横屏版可进入桌面工作台。",
          "用 Bot 切换器进入智能体管理或管理中心。",
          "左侧活动栏按文件、搜索、大纲、指南、调试、Git、运维、插件、设置组织。",
        ],
        notes: [
          "移动端不显示指南和 Assistant 运维。",
          "访客和只读用户只看到已授权入口。",
          "入口隐藏通常由权限、Bot 模式、插件权限或当前布局决定。",
        ],
      },
      {
        title: "权限和 Bot 模式",
        entry: "登录后系统按 session capabilities、当前 Bot 模式和 Bot 授权裁剪页面。",
        scenario: "适合判断为什么不能发送、不能编辑文件、不能打开 Git/终端/设置。",
        actions: [
          "检查当前账号是否有文件、聊天、终端、Git、插件或 admin ops 权限。",
          "确认当前 Bot 是 cli 还是 assistant。",
          "无权操作的 Bot 可只读进入，发送和写入动作会禁用。",
        ],
        notes: [
          "cluster 仅 CLI Bot 支持。",
          "Assistant 运维仅 assistant Bot、桌面端、admin ops 权限下出现。",
          "系统最多允许 1 个 assistant Bot profile。",
        ],
      },
    ],
  },
  {
    id: "chat",
    title: "聊天和会话",
    description: "处理 CLI/assistant 对话、会话、附件、计划模式和任务终止。",
    tone: "green",
    items: [
      {
        title: "聊天",
        entry: "移动端底部“聊天”；桌面端右侧聊天栏。",
        scenario: "适合向 CLI Bot 或 assistant Bot 发送任务、追问、查看历史回复。",
        actions: [
          "发送普通消息后等待流式回复完成。",
          "长回复会分段流式展示，完成后转为可阅读 Markdown。",
          "需要发送 CLI 斜杠命令时输入 `//cmd`，系统会转成 `/cmd`。",
          "用 trace 查看过程信息，用终止任务中断当前处理。",
        ],
        notes: [
          "无 chat_send 权限时发送按钮不可用。",
          "CLI 和 assistant 走不同后端流程，能力受当前 Bot 模式影响。",
          "任务运行中切换 Bot，完成后会在 Bot 切换器显示未读。",
        ],
      },
      {
        title: "会话、附件和计划模式",
        entry: "聊天页顶部、输入区工具按钮、消息里的方案卡片。",
        scenario: "适合多轮上下文、带文件说明、或先产出方案再执行。",
        actions: [
          "切换会话，保留不同任务上下文。",
          "添加附件或引用文件，让智能体先读事实。",
          "使用 prompt preset 快速填入常用指令。",
          "收到计划草稿后可按方案执行。",
        ],
        notes: [
          "完整聊天历史主要保存在运行内存中。",
          "CLI session id 会持久化，历史正文不会完整落盘。",
          "执行方案前仍应确认方案路径和验证命令。",
        ],
      },
    ],
  },
  {
    id: "agents",
    title: "子 Agent 和 Cluster",
    description: "管理 active agent、@agent_id、cluster run/task、模板和 MCP 配置。",
    tone: "cyan",
    items: [
      {
        title: "子 Agent",
        entry: "聊天页 agent 选择区、Bot 管理里的 child agents 配置。",
        scenario: "适合把同个 CLI Bot 下的不同角色、目录或参数分开使用。",
        actions: [
          "非 cluster 聊天一次只激活 1 个 active agent。",
          "切换 active agent 后，后续消息发给该 agent。",
          "在 Bot 管理里新增、编辑、删除 child agents。",
        ],
        notes: [
          "agent 归属当前 Bot，不是全局共享。",
          "agent 忙碌状态会反馈到 Bot 活动状态。",
          "只读用户可查看但不能管理配置。",
        ],
      },
      {
        title: "Cluster",
        entry: "CLI Bot 的聊天页 cluster 控件、Bot 管理 cluster 模板/JSON 配置。",
        scenario: "适合复杂任务并发查上下文、测试、复核风险。",
        actions: [
          "用 `@agent_id` 指派子 agent。",
          "查看 run、task、progress 和 final 回告。",
          "配置 model tier、MCP server 和 cluster 模板。",
        ],
        notes: [
          "cluster 仅 CLI Bot 支持，assistant Bot 不显示。",
          "多个 agent 不应写同一文件或重复做同件事。",
          "主线负责汇总和验收，子 agent 结果只是证据来源。",
        ],
      },
    ],
  },
  {
    id: "workspace",
    title: "文件和工作区",
    description: "使用文件树、预览、编辑、搜索、大纲、definition 和工作目录。",
    tone: "primary",
    items: [
      {
        title: "文件",
        entry: "移动端底部“文件”；桌面端左侧活动栏“文件”。",
        scenario: "适合浏览工作区、打开代码、编辑保存、上传下载和管理文件。",
        actions: [
          "用文件树展开目录并打开预览或编辑器。",
          "编辑后保存；可新建、上传、下载、删除、重命名。",
          "在桌面文件树右键打开 Diff 或插件视图。",
        ],
        notes: [
          "无 read_file_content 权限时不会恢复或打开编辑器标签。",
          "无 write_files 权限时写入类动作不可用。",
          "工作区根目录来自当前 Bot 的 workingDir。",
        ],
      },
      {
        title: "搜索、大纲、Definition",
        entry: "桌面端左侧活动栏“搜索”“大纲”，编辑器内 Ctrl/Command 点击符号。",
        scenario: "适合找文件、找引用、查看当前文件结构、跳到定义。",
        actions: [
          "快速打开按文件名搜索并打开结果。",
          "搜索面板按文本找匹配项。",
          "大纲展示当前文件结构。",
          "Ctrl/Command 点击符号尝试跳转定义；多个目标会弹出选择器。",
        ],
        notes: [
          "搜索和 definition 基于工作区内容，结果受权限和文件大小影响。",
          "structureOnly 模式只显示结构，不读取全文。",
          "大纲能力依赖当前文件类型和解析结果。",
        ],
      },
    ],
  },
  {
    id: "desktop-workbench",
    title: "桌面工作台",
    description: "理解左侧活动栏、中央编辑器、底部终端、右侧聊天栏和布局状态。",
    tone: "amber",
    items: [
      {
        title: "四区布局",
        entry: "登录后点“横屏版”，或本地保存为桌面模式后自动进入。",
        scenario: "适合开发时同时看文件、编辑、跑终端、和智能体对话。",
        actions: [
          "左侧活动栏切换文件、搜索、大纲、调试、Git、插件等面板。",
          "中央编辑器管理文件标签和插件/运维工作区。",
          "底部终端运行命令，右侧聊天栏持续对话。",
        ],
        notes: [
          "折叠和尺寸会按工作台状态保存。",
          "切换 Bot 时有未保存文件会提示确认。",
          "旧版 guide sidebar session 会回退到文件面板。",
        ],
      },
      {
        title: "快速打开、分栏和聚焦",
        entry: "桌面端快捷键 Ctrl/Command+P、标题栏布局按钮、各面板聚焦按钮。",
        scenario: "适合大量文件间跳转、临时放大编辑器或终端。",
        actions: [
          "用快速打开按名称搜索文件。",
          "折叠左侧栏、底部终端、右侧聊天栏。",
          "进入聚焦模式最大化当前工作区，再退出恢复布局。",
        ],
        notes: [
          "聚焦模式不会丢失编辑器标签。",
          "structureOnly 时不显示指南和编辑器工作区。",
          "桌面布局与移动底部导航相互独立。",
        ],
      },
    ],
  },
  {
    id: "terminal",
    title: "终端",
    description: "使用持久终端、普通 exec、重建、关闭和终端动作。",
    tone: "green",
    items: [
      {
        title: "持久终端",
        entry: "移动端底部“终端”；桌面端底部终端面板。",
        scenario: "适合保留 shell 会话、连续运行命令、查看长输出。",
        actions: [
          "打开终端后手动输入命令。",
          "切换页面或 Bot 后会复用共享终端实例。",
          "需要清理环境时重建终端，或关闭终端释放会话。",
        ],
        notes: [
          "无 terminal_exec 权限时终端入口隐藏或不可用。",
          "终端不会自动启动危险命令。",
          "不要通过终端重启当前 agent 宿主进程，除非用户明确指令。",
        ],
      },
      {
        title: "普通 Exec 和动作",
        entry: "文件、Git、调试、设置等页面中的命令按钮和后台 API。",
        scenario: "适合运行一次性脚本、Git 操作或系统检查。",
        actions: [
          "在相关面板点击测试、脚本、检查、下载等动作。",
          "失败时查看页面错误、日志或通知。",
          "需要交付时记录命令和结果。",
        ],
        notes: [
          "普通 exec 和持久终端不是同个会话。",
          "后台动作可能受 admin ops、git_ops、debug_exec 等权限限制。",
          "长任务应等状态完成再切页面复核。",
        ],
      },
    ],
  },
  {
    id: "debug",
    title: "调试",
    description: "使用 profile、launch、断点、continue/pause/step、变量和 evaluate。",
    tone: "cyan",
    items: [
      {
        title: "调试面板",
        entry: "桌面端活动栏“调试”，移动端有对应调试入口时从导航进入。",
        scenario: "适合按 profile 启动调试、观察断点和变量。",
        actions: [
          "选择 profile 后 launch。",
          "添加或移除断点。",
          "使用 continue、pause、step over、step in、step out 控制执行。",
          "查看变量并执行 evaluate。",
        ],
        notes: [
          "调试能力受 debug_exec 权限和 profile capabilities 限制。",
          "按钮会按 profile 能力禁用。",
          "调试会话异常时先看 profile 和后端错误。",
        ],
      },
    ],
  },
  {
    id: "git",
    title: "Git",
    description: "处理状态、diff、stage、commit、fetch/pull/push、branch、stash 和 blame。",
    tone: "amber",
    items: [
      {
        title: "Git 工作流",
        entry: "移动端底部“Git”；桌面端活动栏“Git”或文件树右键 Diff。",
        scenario: "适合查看改动、暂存提交、同步远端和定位风险。",
        actions: [
          "查看 overview、文件状态和 diff。",
          "stage/unstage 单文件或全部暂存。",
          "填写提交信息并 commit。",
          "执行 fetch、pull、push、branch、stash/pop、blame。",
        ],
        notes: [
          "需要 git_ops 权限。",
          "smart commit 会辅助生成或执行提交，但仍需复核 diff。",
          "危险操作会有提示；不要夹带无关改动。",
        ],
      },
    ],
  },
  {
    id: "plugins",
    title: "插件",
    description: "安装、启停、配置、卸载、打开文件视图和下载 artifact。",
    tone: "primary",
    items: [
      {
        title: "插件管理",
        entry: "移动端底部“插件”；桌面端活动栏“插件”。",
        scenario: "适合安装文件查看器、配置插件、刷新插件运行时。",
        actions: [
          "安装插件，可默认覆盖同名插件。",
          "启用或停用插件。",
          "编辑插件 config，或卸载插件。",
          "刷新插件页会重新扫描 manifest 并重启运行时。",
        ],
        notes: [
          "需要 view_plugins 权限。",
          "插件默认在用户目录 `.tcb/plugins`，示例插件在 examples 下。",
          "更新插件会清理视图 session 并关闭旧 runtime。",
        ],
      },
      {
        title: "文件视图",
        entry: "文件预览或文件树右键的插件视图入口。",
        scenario: "适合查看 VCD 波形等普通文本预览不友好的文件。",
        actions: [
          "打开 snapshot 或 session 视图。",
          "heavy 数据会创建会话并按需加载窗口。",
          "可下载插件产出的 artifact。",
        ],
        notes: [
          "snapshot 适合轻量一次性视图，session 适合重型交互。",
          "light/heavy 由插件 manifest 声明。",
          "VCD LOD 压缩不能隐藏信号活动。",
        ],
      },
    ],
  },
  {
    id: "assistant-ops",
    title: "Assistant 运维",
    description: "使用 proposals、patch、memory、diagnostics、audit、queue、cron 和 runs。",
    tone: "cyan",
    items: [
      {
        title: "运维台",
        entry: "桌面端 assistant Bot 的活动栏“运维”。",
        scenario: "适合管理 API-backed assistant 的提案、补丁和运行任务。",
        actions: [
          "查看 proposals 并生成 patch。",
          "应用或复核 patch。",
          "管理 memory、diagnostics、audit。",
          "查看 Automation queue、cron、runs。",
        ],
        notes: [
          "仅 assistant Bot、桌面端、admin ops 权限下显示。",
          "CLI Bot 不显示运维入口。",
          "权限变化后会从运维工作区回退。",
        ],
      },
    ],
  },
  {
    id: "settings",
    title: "设置",
    description: "调整主题、阅读排版、头像、通知、工作目录、CLI、Git 代理、Tunnel 和终止任务。",
    tone: "green",
    items: [
      {
        title: "个人和界面设置",
        entry: "移动端底部“设置”；桌面端活动栏“设置”。",
        scenario: "适合调整阅读体验、头像、网页通知和常用偏好。",
        actions: [
          "切换主题。",
          "设置聊天字体、字号、行距、段距。",
          "更新头像。",
          "开启聊天完成网页通知并请求浏览器权限。",
        ],
        notes: [
          "访客通常看不到设置入口。",
          "通知还受浏览器权限限制。",
          "界面偏好保存在本地浏览器。",
        ],
      },
      {
        title: "运行配置",
        entry: "设置页的工作目录、CLI 配置、Git 代理、Tunnel 和任务控制区域。",
        scenario: "适合调整当前 Bot 的运行路径和本机连接能力。",
        actions: [
          "修改工作目录。",
          "编辑 CLI 路径或参数。",
          "配置 Git 代理。",
          "查看 Tunnel 状态。",
          "终止当前任务。",
        ],
        notes: [
          "运行配置通常需要 admin ops。",
          "工作目录改动会影响文件、终端、Git 和聊天上下文。",
          "终止任务只中断当前处理，不等于重启 Bot。",
        ],
      },
    ],
  },
  {
    id: "bot-management",
    title: "Bot 管理",
    description: "创建、编辑、启动、停止、删除 Bot，管理头像、CLI 参数、child agents 和 cluster。",
    tone: "amber",
    items: [
      {
        title: "智能体管理",
        entry: "Bot 切换器里的“智能体管理”，桌面端也可从顶部 Bot 菜单进入。",
        scenario: "适合维护 main Bot 之外的 managed bots。",
        actions: [
          "创建、编辑、启动、停止、删除 Bot。",
          "设置头像、CLI 类型、CLI 路径、工作目录和参数。",
          "管理 child agents。",
          "编辑 cluster 模板、JSON 配置、MCP 和 model tier。",
        ],
        notes: [
          "真实 managed_bots.json 不应提交。",
          "新建 webcli 会被拒绝，旧 webcli profile 会降级到 cli。",
          "最多 1 个 assistant Bot。",
        ],
      },
    ],
  },
  {
    id: "admin-center",
    title: "管理中心",
    description: "管理用户权限、邀请码、升级、公告、联机聊天和环境配置。",
    tone: "primary",
    items: [
      {
        title: "管理中心",
        entry: "Bot 切换器里的“管理中心”。",
        scenario: "适合管理员维护用户、权限、邀请码、公告和更新。",
        actions: [
          "配置用户权限和 Bot 授权。",
          "管理邀请码。",
          "发布、查看、删除公告。",
          "查看更新和离线包。",
          "使用联机聊天和环境配置入口。",
        ],
        notes: [
          "需要 admin ops；邀请码页还可能受 manage_register_codes 限制。",
          "公告内容支持受限的安全内联 HTML。",
          "升级动作通常在下次启动时生效。",
        ],
      },
    ],
  },
  {
    id: "global",
    title: "全局能力",
    description: "登录/注册/访客、公告、通知中心、Bot 切换器、布局切换和 LAN Chat。",
    tone: "cyan",
    items: [
      {
        title: "登录和注册",
        entry: "打开 Web UI 后的登录页。",
        scenario: "适合用口令登录、邀请码注册或以访客身份进入。",
        actions: [
          "输入访问口令登录。",
          "使用邀请码注册。",
          "点访客入口进入只读体验。",
        ],
        notes: [
          "登录态保存在浏览器 storage。",
          "访客导航会裁剪成员功能。",
          "账号权限由管理中心配置。",
        ],
      },
      {
        title: "公告、通知、Bot 切换器和 LAN Chat",
        entry: "顶部/状态栏公告按钮、通知中心、Bot 名称按钮、桌面状态栏成员聊天。",
        scenario: "适合查看系统消息、未读回复、切换 Bot 或局域网协作聊天。",
        actions: [
          "有新公告时登录后自动弹出公告。",
          "通知中心查看聊天完成和系统通知。",
          "Bot 切换器显示运行中、离线、忙碌和未读状态。",
          "桌面状态栏打开 LAN Chat。",
        ],
        notes: [
          "离线 Bot 不可切换进入。",
          "LAN Chat 仅桌面状态栏暴露。",
          "浏览器通知需用户授权。",
        ],
      },
    ],
  },
  {
    id: "updates",
    title: "更新",
    description: "检查、下载、离线包和下次启动生效的更新流程。",
    tone: "amber",
    items: [
      {
        title: "版本更新",
        entry: "管理中心“更新”页，或设置/管理入口里的版本更新区域。",
        scenario: "适合管理员检查 GitHub Release、下载联网包或准备离线包。",
        actions: [
          "检查联网更新。",
          "下载更新包。",
          "查看离线包列表。",
          "按需启用自动下载更新。",
        ],
        notes: [
          "自动更新只检查 GitHub Releases。",
          "下载的更新会在下次启动时应用。",
          "docs 和 release notes 不应提交到仓库。",
        ],
      },
    ],
  },
];
