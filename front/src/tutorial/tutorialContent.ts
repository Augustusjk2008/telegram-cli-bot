import {
  Boxes,
  FolderTree,
  GitBranch,
  LayoutDashboard,
  Lightbulb,
  MessageSquare,
  MessagesSquare,
  Network,
  Rocket,
  Settings2,
  SquareTerminal,
  Target,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { withPublicBase } from "../utils/publicBase";
import type { HotspotRect } from "./tutorialMotion";
import generatedShots from "./shots.generated.json";

export type TutorialStep = {
  id: string;
  /** At most 14 Chinese characters. */
  title: string;
  /** One to three short sentences; `code` in backticks, UI labels in 「」. */
  body: string[];
  /** Optional short bullets (commands, limits). */
  points?: string[];
  /** Only when it saves time or prevents a mistake. */
  tip?: string;
  /** Key caps, for example ["Ctrl", "P"]. */
  keys?: string[];
  /** Screenshot id within the chapter. */
  shot: string;
  /** Named hotspot of that screenshot. */
  hotspot?: string;
  /** 1–1.8; the stage scales towards the hotspot. */
  zoom?: number;
  /** Describes the screenshot. */
  alt: string;
};

export type TutorialChapter = {
  id: string;
  title: string;
  summary: string;
  icon: LucideIcon;
  steps: TutorialStep[];
};

type GeneratedShots = Record<string, { hotspots: Record<string, HotspotRect> }>;

/** Hotspot rectangles recorded by `npm run tutorial:shots`; never edit the JSON by hand. */
export const TUTORIAL_SHOTS: GeneratedShots = generatedShots;

export function tutorialShotKey(chapterId: string, shot: string): string {
  return `${chapterId}/${shot}`;
}

export function tutorialShotUrl(chapterId: string, shot: string): string {
  // Unhashed public asset: the version query refreshes it after an upgrade.
  return `${withPublicBase(`/assets/tutorial/${chapterId}/${shot}.webp`)}?v=${encodeURIComponent(__APP_VERSION__)}`;
}

export function tutorialHotspot(chapterId: string, shot: string, name: string | undefined): HotspotRect | undefined {
  return name ? TUTORIAL_SHOTS[tutorialShotKey(chapterId, shot)]?.hotspots[name] : undefined;
}

export function findTutorialChapter(chapterId: string): TutorialChapter | undefined {
  return TUTORIAL_CHAPTERS.find((chapter) => chapter.id === chapterId);
}

/** Chapters in cover order. */
export const TUTORIAL_CHAPTERS: TutorialChapter[] = [
  {
    id: "overview",
    title: "项目概览",
    summary: "从项目接入到交付，把 Agent 能力放进一条完整工作流。",
    icon: Workflow,
    steps: [
      {
        id: "architecture",
        title: "整体架构",
        body: [
          "Orbit Safe Claw 位于浏览器、项目工作区和 AI 执行引擎之间，把文件、终端、聊天、Git 与协作能力放在同一个入口。",
          "你可以为每个项目绑定一个智能体，按自己的 CLI、工作目录和权限边界运行任务。",
        ],
        shot: "architecture",
        alt: "Orbit Safe Claw 架构图：浏览器工作台连接项目工作区、AI 执行引擎、Git、消息网关和集群协作",
      },
      {
        id: "login",
        title: "从登录开始",
        body: [
          "登录页负责账号接入和主题预览。注册、登录和 guest 只读访问都从这里进入。",
          "进入工作台后，当前账号能看到的智能体、文件、终端和管理入口会按权限呈现。",
        ],
        points: [
          "主题预览只保存在当前浏览器。",
          "注册码和账号权限由服务端管理。",
        ],
        shot: "login",
        alt: "Orbit Safe Claw 完整登录页：左侧品牌介绍和右侧登录表单",
      },
      {
        id: "workbench",
        title: "一个完整工作台",
        body: [
          "主页面把文件、编辑器、终端和聊天放在一张工作台里，任务可以从阅读代码一直推进到验证和交付。",
          "聊天中的过程详情、工具调用、上下文用量和历史会话，让每一次执行都能被查看和接续。",
        ],
        points: [
          "本地和远程 SSH 工作区使用一致的主流程。",
          "布局、窗口位置和主题可以按使用习惯调整。",
        ],
        shot: "workbench",
        alt: "Orbit Safe Claw 完整主页面：左侧文件区、中间编辑器和终端、右侧聊天窗口",
      },
      {
        id: "agents",
        title: "一套智能体管理",
        body: [
          "智能体管理页集中维护本地与远程工作区的 Agent，查看它们的类型、状态、工作目录和连接信息。",
          "从这里新增智能体、进入项目或编辑配置，把不同项目和不同执行引擎分开管理。",
        ],
        points: [
          "支持 Codex、Claude、Antigravity 和 DeepSeek Harness。",
          "管理员可以进一步配置账号权限、插件、网关和更新。",
        ],
        shot: "manager",
        alt: "Orbit Safe Claw 完整智能体管理页：统计卡片、智能体列表和详情面板",
      },
    ],
  },
  {
    id: "start",
    title: "快速上手",
    summary: "登录、切换 Bot、创建智能体，认识界面的各个区域。",
    icon: Rocket,
    steps: [
      {
        id: "login",
        title: "登录",
        body: [
          "用账号和密码登录。没有账号时切换到「注册」，注册需要注册码。",
          "「以 guest 进入」是只读访问。",
        ],
        tip: "右上角可以预览主题，这个选择只保存在当前浏览器。",
        shot: "login",
        hotspot: "form",
        zoom: 1.5,
        alt: "登录页：右侧是登录表单，包含用户名、密码、记住登录和以 guest 进入",
      },
      {
        id: "header",
        title: "顶部栏",
        body: [
          "登录后进入工作台。左上角依次是智能体名称、工作目录和 Git 分支。",
          "点击智能体名称切换智能体；点击最左边的图标可以再次打开本教程。",
        ],
        shot: "workbench",
        hotspot: "context",
        zoom: 1.7,
        alt: "工作台左上角：图标、智能体名称 main、工作目录 orbit-safe-claw 和分支 main",
      },
      {
        id: "rail",
        title: "活动栏与状态栏",
        body: [
          "左侧活动栏切换侧边栏的内容：文件、搜索、大纲、调试、Git、插件和设置。",
          "底部状态栏显示当前文件及其保存状态、调试和终端的状态、终端所在目录，以及 AI 是否空闲。",
        ],
        points: ["远程工作区的活动栏只有文件、Git 和设置。"],
        shot: "workbench",
        hotspot: "rail",
        zoom: 1.5,
        alt: "工作台左侧的活动栏，从上到下是文件、搜索、大纲、调试、Git、插件和设置",
      },
      {
        id: "switch",
        title: "切换智能体",
        body: [
          "点击左上角的智能体名称打开切换面板。可以搜索，也可以按「未读」「空闲」「处理中」「离线」筛选，点击条目切换。",
          "右侧显示所选智能体的工作目录和状态；有管理权限的账号还会看到「智能体管理」和「管理中心」两个入口。",
          "列表会列出正在处理任务的主会话、命名会话和子 Agent。打开聊天窗口的会话选择器，可以逐个查看会话是否空闲。",
        ],
        shot: "switcher",
        hotspot: "panel",
        zoom: 1.3,
        alt: "智能体切换面板显示 main 的「代码审查」会话正在使用 claude，team2 的主会话也在处理中",
      },
      {
        id: "manager",
        title: "智能体管理",
        body: [
          "「智能体管理」列出本机与远程工作区里的智能体，显示状态、类型和工作目录。",
          "选中一行后，右侧可以「进入」该智能体，或「编辑」它的配置。",
        ],
        points: ["这个页面和下一步的「新增智能体」需要管理智能体的权限。"],
        shot: "manager",
        hotspot: "list",
        zoom: 1.2,
        alt: "智能体管理页面：统计卡片、智能体表格和右侧的概览面板",
      },
      {
        id: "create",
        title: "新增智能体",
        body: [
          "点击「新增智能体」，填写别名，选择 CLI 类型和工作目录，然后点击「创建智能体」。",
          "CLI 类型有 codex、codex server、claude、Antigravity CLI 和 DeepSeek Harness。",
        ],
        points: [
          "别名以字母或数字开头，由字母、数字、`_` 或 `-` 组成，2–32 位，保存时转为小写。",
          "工作目录需为已存在的目录；留空使用服务的默认工作目录。",
        ],
        shot: "create",
        hotspot: "form",
        zoom: 1.2,
        alt: "新增智能体表单：别名 team3、CLI 类型、CLI 路径、位置和工作目录",
      },
      {
        id: "chat-tool",
        title: "选择聊天工具",
        body: [
          "在本地智能体的聊天窗口顶部打开会话选择器，选择「新建聊天会话」。输入名称并选择这段聊天使用的 AI 工具。",
          "例如，用 Codex 写代码，再创建一个用 Claude 的「代码审查」会话。两者共享工作区，各自保留记录和原生线程。",
          "以后从选择器切回会话，名称旁会显示它的工具。标有「Bot 默认」的会话跟随智能体当前的工具。",
        ],
        shot: "chat-tool",
        hotspot: "dialog",
        zoom: 1.5,
        alt: "新建聊天会话窗口，名称为代码审查，AI 工具选中了 claude",
      },
    ],
  },
  {
    id: "chat",
    title: "对话",
    summary: "发送消息、查看执行过程、停止与继续、管理会话。",
    icon: MessageSquare,
    steps: [
      {
        id: "send",
        title: "发送消息",
        body: [
          "在聊天窗口底部的输入框里写下要做的事，点击「发送」或按 `Enter` 提交。",
          "按 `Shift+Enter` 换行。",
        ],
        tip: "有管理权限的账号可以在管理中心的「全局配置」里关闭「Enter 键发送消息」，之后 `Enter` 只换行；这个设置只保存在当前浏览器。",
        shot: "composer",
        hotspot: "composer",
        zoom: 1.7,
        alt: "桌面工作台，右侧聊天窗口底部的输入框里已经写好一条任务",
      },
      {
        id: "model",
        title: "模型与附件",
        body: [
          "输入框下方的工具栏用来选择「模型」和「思考深度」；DeepSeek 还会显示 Provider。",
          "点击左侧的加号「上传附件」；剪贴板里的图片可以直接粘贴进输入框。",
        ],
        shot: "composer",
        hotspot: "toolbar",
        zoom: 1.8,
        alt: "聊天输入框下方的工具栏：上传附件、模型、思考深度和发送按钮",
      },
      {
        id: "details",
        title: "查看执行过程",
        body: [
          "带有执行过程的回答上方有一行「过程详情」，写明过程条数和工具调用次数，点击展开。",
          "展开后按顺序列出 Agent 的说明、调用的工具和返回结果。",
          "回答下方的 `ctx` 标记是上下文窗口的剩余比例，点击可以查看用量明细。",
        ],
        points: ["账号没有查看执行过程的权限时，不会显示「过程详情」。"],
        shot: "answer",
        hotspot: "answer",
        zoom: 1.6,
        alt: "一条回答展开了过程详情：两段过程、shell 工具调用及其结果，下方是 ctx 82% 标记",
      },
      {
        id: "stop",
        title: "终止任务",
        body: [
          "任务运行且输入框为空时，输入框右下角的「发送」会变成「终止任务」。",
          "点击后确认一次，当前任务随即停止。",
        ],
        shot: "running",
        hotspot: "stop",
        zoom: 1.8,
        alt: "任务运行中，聊天窗口显示正在输出，输入框右下角是红色的终止按钮",
      },
      {
        id: "continue",
        title: "继续与无尽模式",
        body: [
          "回答没有做完时，点击回答下方的「继续」，会向 Agent 发送一条 `Continue`。",
          "旁边的扬声器按钮用于「朗读回答」，播放后可暂停、继续朗读或停止；使用浏览器语音，无需配置 API 密钥。",
          "回答以错误结束时，旁边会多出「无尽模式」：确认后立即发送一条 `Continue`，此后遇到可重试的未完成或错误结果，会按间隔自动发送。",
        ],
        points: [
          "默认间隔 120 秒，可用环境变量 `ENDLESS_CONTINUE_DELAY_SECONDS` 调整。",
          "得到正常回答、终止任务，或遇到不可重试的错误时，自动续接结束。",
        ],
        shot: "answer",
        hotspot: "continue",
        zoom: 1.8,
        alt: "回答下方的操作按钮：ctx 标记、朗读回答、收藏回答、继续和复制",
      },
      {
        id: "history",
        title: "历史会话",
        body: [
          "点击聊天窗口顶部的「会话」打开历史会话，可以搜索、切换或删除会话。",
          "「新会话」开始一段新的对话，之前的会话留在列表里；「收藏」页列出收藏过的回答。",
        ],
        shot: "history",
        hotspot: "panel",
        zoom: 1.5,
        alt: "历史会话面板：清空和新会话按钮，历史与收藏两个标签，搜索框和两条会话",
      },
      {
        id: "presets",
        title: "提示词预设与 // 命令",
        body: [
          "点击「发送」左侧的箭头打开提示词预设，选中的预设会插入输入框。",
          "预设在侧边栏「设置」的「提示词预设」里添加，只对当前智能体生效；全局预设在管理中心维护。",
        ],
        points: ["以 `//` 开头的消息会改写成以 `/` 开头再交给 CLI，例如 `//compact` 会作为 `/compact` 发送。"],
        shot: "presets",
        hotspot: "menu",
        zoom: 1.6,
        alt: "提示词预设菜单列出当前 Bot 的两条预设，下方是管理全局预设和管理当前智能体预设",
      },
    ],
  },
  {
    id: "layout",
    title: "工作台布局",
    summary: "显示或隐藏窗口、切换布局、聚焦与快捷键。",
    icon: LayoutDashboard,
    steps: [
      {
        id: "panes",
        title: "四个窗口",
        body: [
          "工作台由侧边栏、编辑/预览区、终端和聊天四个窗口组成。",
          "顶部的四个开关依次显示或隐藏这四个窗口。",
        ],
        shot: "overview",
        hotspot: "toggles",
        zoom: 1.6,
        alt: "桌面工作台全貌：左侧文件树，中间是编辑器和终端，右侧是聊天，顶部有四个布局开关",
      },
      {
        id: "presets",
        title: "切换布局预设",
        body: ["点击顶部的「窗口布局」，在「经典」「底部通栏」「四列并排」「右侧堆叠」四种预设之间切换。"],
        tip: "布局设置按浏览器保存，换一个浏览器或设备需要重新选择。",
        shot: "menu",
        hotspot: "menu",
        zoom: 1.5,
        alt: "窗口布局菜单：四种布局预设、调整窗口位置和恢复默认",
      },
      {
        id: "rearrange",
        title: "拖动交换位置",
        body: [
          "在「窗口布局」里选择「调整窗口位置…」，把一个窗口拖到另一个窗口上，两者交换位置；也可以直接点窗口里的交换按钮。",
          "点击「完成」或按 `Esc` 退出；「恢复默认」把当前预设的窗口位置和尺寸恢复为默认。",
        ],
        shot: "rearrange",
        hotspot: "banner",
        zoom: 1.3,
        alt: "调整窗口位置模式：四个窗口显示为可拖动的占位块，顶部是提示条和完成按钮",
      },
      {
        id: "focus",
        title: "聚焦一个窗口",
        body: [
          "文件区、编辑器和终端的标题栏上各有一个聚焦按钮（编辑器需先打开文件）。点击后这个窗口铺满工作区，其他窗口暂时隐藏。",
          "再点一次同一个按钮退出聚焦。",
        ],
        shot: "focus",
        hotspot: "button",
        zoom: 1.6,
        alt: "编辑器处于聚焦状态，铺满整个工作区，右上角是退出聚焦按钮",
      },
      {
        id: "quick-open",
        title: "快速打开与搜索",
        body: [
          "按 `Ctrl+P`（macOS 上是 `Cmd+P`）打开命令面板，输入文件名后选择结果即可打开文件。",
          "`Ctrl+Shift+F` 切换到侧边栏的全文搜索。",
        ],
        points: ["远程工作区里这两个快捷键不可用。"],
        tip: "教程打开期间这两个快捷键不会生效，关闭教程后再试。",
        keys: ["Ctrl", "P"],
        shot: "palette",
        hotspot: "palette",
        zoom: 1.3,
        alt: "命令面板里输入 read，结果列出 README.md",
      },
      {
        id: "view-mode",
        title: "横屏版与竖屏版",
        body: [
          "右上角的视图模式开关有三档：「Auto」是自动，「竖」是竖屏版，「横」是横屏版。",
          "自动模式下，窗口宽度不小于 1280 像素时使用横屏版，否则使用竖屏版。",
        ],
        tip: "本教程的入口只在横屏版左上角的图标上。",
        shot: "overview",
        hotspot: "viewMode",
        zoom: 1.8,
        alt: "工作台右上角的视图模式开关：Auto、竖、横",
      },
    ],
  },
  {
    id: "files",
    title: "文件与编辑",
    summary: "文件树、标签页与分栏、预览、搜索和大纲。",
    icon: FolderTree,
    steps: [
      {
        id: "tree",
        title: "文件树",
        body: [
          "侧边栏的「文件」显示工作目录。顶部按钮依次是新建文件、新建文件夹、刷新文件树和聚焦文件区。",
          "「更多文件操作」里有上传文件、返回工作目录和显示条目信息。",
        ],
        shot: "tree",
        hotspot: "actions",
        zoom: 1.6,
        alt: "文件树展开了 docs 和 src 两个目录，顶部是一排操作按钮",
      },
      {
        id: "menu",
        title: "右键操作",
        body: ["在文件上点右键，可以预览、在右侧打开、改名、复制路径、复制、下载或删除。"],
        shot: "menu",
        hotspot: "menu",
        zoom: 1.5,
        alt: "README.md 的右键菜单：预览、在右侧打开、改名、复制路径、复制、下载、删除",
      },
      {
        id: "split",
        title: "标签页与分栏",
        body: [
          "点击文件在编辑器里打开，每个文件一个标签页。",
          "右键选择「在右侧打开」，或点击编辑器右上角的「在右侧打开」，可以并排查看两个文件。",
        ],
        tip: "编辑后按 `Ctrl+S` 保存，状态栏会显示「已保存」。",
        shot: "split",
        hotspot: "editor",
        zoom: 1.3,
        alt: "编辑器分成左右两栏：左边是 README.md，右边是 src/server.ts",
      },
      {
        id: "preview",
        title: "预览",
        body: [
          "Markdown 文件点击「预览」查看渲染后的页面，点击「编辑」回到源码。",
          "本地工作区的 HTML 文件可以交互预览；安装了对应插件时，PDF、DOCX、PPTX、CSV 等由插件视图打开。",
        ],
        points: ["HTML 文件上限 1 MiB，其他单个资源上限 16 MiB。"],
        shot: "preview",
        hotspot: "preview",
        zoom: 1.3,
        alt: "README.md 的预览标签页显示渲染后的标题、段落和列表",
      },
      {
        id: "search",
        title: "搜索与大纲",
        body: [
          "活动栏的「搜索」做全文搜索：输入关键词后自动列出结果，点击结果打开文件并跳到对应行。",
          "「大纲」列出当前文件里的类、函数、方法和标题，点击跳到所在行。",
        ],
        keys: ["Ctrl", "Shift", "F"],
        shot: "search",
        hotspot: "search",
        zoom: 1.4,
        alt: "侧边栏的搜索视图：关键词 install 命中 README.md 第 7 行",
      },
      {
        id: "navigation",
        title: "代码导航与补全",
        body: [
          "语言服务为 Python、TypeScript / JavaScript 和 C / C++ 提供语义代码导航，状态栏显示当前文件的语言服务状态。",
          "编辑器的 AI 行内补全在管理中心的「补全」里配置。",
        ],
        points: ["远程工作区不提供语言服务，也没有搜索和大纲。"],
        shot: "split",
        hotspot: "statusbar",
        zoom: 1.6,
        alt: "状态栏右侧显示 TS/JS 语言服务就绪",
      },
    ],
  },
  {
    id: "terminal",
    title: "终端",
    summary: "多标签终端与快捷命令。",
    icon: SquareTerminal,
    steps: [
      {
        id: "tabs",
        title: "多标签终端",
        body: [
          "终端窗口顶部是标签栏，点击加号新建终端。",
          "每个标签使用独立的 shell，互不影响。",
        ],
        shot: "tabs",
        hotspot: "strip",
        zoom: 1.5,
        alt: "终端窗口有终端 1、构建、终端 2 三个标签，当前标签里是 git status 的输出",
      },
      {
        id: "actions",
        title: "快捷命令",
        body: [
          "终端下方是快捷命令，点击后在以该命令命名的标签里执行；再次点击会复用这个标签。",
          "点击齿轮「编辑快捷命令」可以新增或修改命令。",
        ],
        shot: "tabs",
        hotspot: "actions",
        zoom: 1.6,
        alt: "终端下方的快捷命令栏：构建、测试和编辑快捷命令按钮",
      },
      {
        id: "edit",
        title: "编辑快捷命令",
        body: [
          "每条快捷命令有名称、图标和工作目录，并可以为 Windows、Linux、macOS 分别填写命令。",
          "勾选「执行前确认」后，点击时会先询问；含 `sudo`、`restart`、`shutdown` 等的命令始终会询问。",
        ],
        points: ["配置保存在工作目录下的 `scripts/terminal-actions.json`。"],
        shot: "actions",
        hotspot: "dialog",
        zoom: 1.2,
        alt: "终端快捷命令对话框：左侧是构建和测试两条命令，右侧是所选命令的各项设置",
      },
      {
        id: "close",
        title: "关闭与聚焦",
        body: [
          "点击标签上的叉号关闭终端，对应的 shell 会一并结束。",
          "右上角的按钮聚焦终端，让它铺满工作区。",
        ],
        points: ["远程工作区的终端是独立的 SSH 终端标签，没有快捷命令。"],
        shot: "tabs",
        hotspot: "close",
        zoom: 1.7,
        alt: "终端标签上的关闭按钮",
      },
    ],
  },
  {
    id: "git",
    title: "Git 与 GitHub",
    summary: "查看改动、提交、分支、远端与 GitHub 账号。",
    icon: GitBranch,
    steps: [
      {
        id: "status",
        title: "查看改动",
        body: [
          "活动栏的「Git」显示当前分支和改动。改动按「已暂存」「未跟踪」等分组，并标出增删行数。",
          "点击文件打开它的 diff。",
        ],
        shot: "overview",
        hotspot: "changes",
        zoom: 1.5,
        alt: "Git 视图的变更分组：已暂存的 server.py 和未跟踪的 GitScreen.tsx",
      },
      {
        id: "diff",
        title: "查看 diff",
        body: ["diff 在编辑器区域以只读方式打开，可以在「并排」「全文」和「仅差异」之间切换。"],
        shot: "diff",
        hotspot: "diff",
        zoom: 1.3,
        alt: "编辑器区域显示 bot/web/server.py 的已暂存 diff",
      },
      {
        id: "commit",
        title: "暂存与提交",
        body: [
          "逐个文件暂存，或点击「暂存全部」。填写提交说明后点击「提交更改」，也可以按 `Ctrl+Enter`。",
          "说明框右上角的按钮根据改动生成 commit message；「智能提交」会暂存全部改动，由 AI 生成提交说明后提交。",
        ],
        shot: "overview",
        hotspot: "commit",
        zoom: 1.6,
        alt: "提交说明输入框和下方的提交更改、智能提交按钮",
      },
      {
        id: "graph",
        title: "提交图",
        body: [
          "「提交图」可以切换「全部」和「当前分支」。沿线找到「分叉点」，点击它可查看每条线从这里接出的第一条提交。",
          "选中一个提交后，可以从它新建分支，或以 soft、mixed、hard 模式重置到该提交。",
        ],
        shot: "branches",
        hotspot: "graph",
        zoom: 1.5,
        alt: "提交图列出四个提交，下方是新分支名输入框和重置模式选择",
      },
      {
        id: "branches",
        title: "分支与 Stash",
        body: [
          "「分支」分区切换分支，或输入名称新建分支。",
          "「STASH」分区保存当前改动，并可以应用或删除已有的 stash。",
        ],
        points: ["远程工作区暂不支持创建 stash。"],
        shot: "remotes",
        hotspot: "branches",
        zoom: 1.5,
        alt: "分支分区显示 main 和 feature/git-panel 两个分支",
      },
      {
        id: "sync",
        title: "远端与同步",
        body: [
          "顶部的按钮依次是 Fetch、Pull、Push 和 Merge。Pull 只做快进；本地和远端各有新提交时使用 Merge。",
          "「远端」分区可以添加、修改和移除远端，并把当前分支发布到指定远端。",
        ],
        shot: "overview",
        hotspot: "sync",
        zoom: 1.7,
        alt: "Git 视图顶部的 Fetch、Pull、Push、Merge 和刷新按钮",
      },
      {
        id: "github",
        title: "关联 GitHub",
        body: [
          "在「远端」里点击「关联 GitHub 仓库」。GitHub 账号按 Orbit 登录账号分别连接，可以用个人访问令牌；管理员配置 `GITHUB_OAUTH_CLIENT_ID` 后，还可以用浏览器授权。",
          "连接后可以创建空仓库或选择已有仓库，并在关联后直接发布当前分支。",
        ],
        points: ["令牌加密保存在服务端，不会返回浏览器。"],
        shot: "github",
        hotspot: "panel",
        zoom: 1.5,
        alt: "关联 GitHub 仓库面板：通过浏览器登录 GitHub 按钮和个人访问令牌说明",
      },
    ],
  },
  {
    id: "cluster",
    title: "集群协作",
    summary: "让主 Agent 组建团队，把任务分给多个子 Agent。",
    icon: Network,
    steps: [
      {
        id: "enable",
        title: "开启集群模式",
        body: [
          "点击聊天窗口顶部的「集群」开启集群模式。",
          "开启后，主 Agent 可以通过 `tcb-cluster` 工具把任务委派给子 Agent。",
        ],
        shot: "toggle",
        hotspot: "toggle",
        zoom: 1.7,
        alt: "聊天窗口顶部的计划、集群、会话三个按钮，集群处于开启状态",
      },
      {
        id: "team",
        title: "查看编组",
        body: [
          "主 Agent 组建团队后，输入框上方出现「集群编组」，显示已分配的角色数和集群规模。",
          "展开后可以看到每个角色是「处理中」还是「待命」，以及它的模型档位；点击「查看」进入该子 Agent 的对话，那里只能查看。",
        ],
        shot: "team",
        hotspot: "team",
        zoom: 1.5,
        alt: "集群编组展开后列出实现、测试、审查三个角色，各有状态、模型档位和查看按钮",
      },
      {
        id: "settings",
        title: "并发、写入与超时",
        body: [
          "侧边栏「设置」的「集群」里配置并发规模（1–20）、子 Agent 写入策略和默认超时。",
          "写入策略有「仅主 Agent 可写」和「允许子 Agent 写入」两种。",
        ],
        shot: "settings",
        hotspot: "mode",
        zoom: 1.5,
        alt: "设置里的集群模式分区：并发规模、子 Agent 写入策略和默认超时",
      },
      {
        id: "tiers",
        title: "四档模型",
        body: [
          "低档、中档、高档和专业档各自可以选择执行 CLI、模型和思考深度；执行 CLI 留空时继承主 Bot 的 CLI，模型和思考深度留空时继承所选 CLI 的配置。",
          "专业档用于特殊工作；主 Agent 按约定只在用户明确提出时选用。",
        ],
        points: ["档位只作用于子任务；已入队的任务保留入队时的配置。"],
        shot: "tiers",
        hotspot: "tiers",
        zoom: 1.3,
        alt: "集群模型档位分区，从上到下是低档、中档、高档和专业档",
      },
      {
        id: "limits",
        title: "取消与限制",
        body: [
          "主 Agent 可以按任务单独取消一个子任务，同一次编组里的其他子任务继续运行。",
          "集群任务和进度保存在内存里，宿主重启后不会恢复正在执行的子任务。",
        ],
        points: [
          "远程工作区上的 Antigravity 暂不支持集群。",
          "DeepSeek Harness 的集群限于本地 CLI 模式。",
        ],
        shot: "team",
        alt: "聊天窗口里的集群编组面板",
      },
    ],
  },
  {
    id: "practice",
    title: "用好 Agent",
    summary: "管好工作区，写清需求，先计划再分步执行，用好集群和长期记忆。",
    icon: Target,
    steps: [
      {
        id: "workspace",
        title: "一个项目一个智能体",
        body: [
          "新增智能体时，把工作目录设为项目的根目录。Agent 从这里读写文件、运行命令，也从这里读取项目说明文件。",
          "不同的项目各建一个智能体，会话和历史互不混杂。开始较大的任务前先提交或新建分支，出了问题可以对比和回退。",
        ],
        points: [
          "工作目录过大（例如整个用户目录）时，Agent 要花更多时间找文件，也更容易改到无关的地方。",
          "同一个仓库要并行做两件事时，可以用 `git worktree` 准备第二个目录，再为它新建一个智能体。",
        ],
        shot: "workspace",
        hotspot: "workdir",
        zoom: 1.5,
        alt: "新增智能体表单，工作目录填写为项目根目录 /Users/demo/projects/shop-web",
      },
      {
        id: "prompt",
        title: "把需求写清楚",
        body: [
          "一条好的任务说明写清：要达到什么结果、涉及哪些文件、有哪些限制、怎样算完成。报错、日志和截图直接粘贴或上传，比转述更准确。",
          "排查疑难问题、设计较大的改动时，在输入框下方调高「思考深度」；简单修改用较低的档位，回答更快。",
        ],
        points: [
          "目标：现在的现象和期望的结果。",
          "范围：相关的文件、目录或函数，以及不能改动的部分。",
          "完成标准：要通过的测试或命令，例如 `npm test`，并要求它报告结果。",
        ],
        tip: "反复使用的要求可以存成提示词预设，点击「发送」左侧的箭头插入。",
        shot: "prompt",
        hotspot: "composer",
        zoom: 1.6,
        alt: "聊天输入框里写好了一条分为目标、范围和完成标准三行的任务说明，下方是模型和思考深度",
      },
      {
        id: "plan",
        title: "先出方案再动手",
        body: [
          "复杂或有风险的任务，先点亮聊天窗口顶部的「计划」再描述需求。计划模式下 Agent 只读代码、分析和提问，不修改文件。",
          "方案满意后点击「执行方案」：方案保存到工作目录的 `docs/plan/`，并在一个新会话里按方案执行。",
        ],
        points: [
          "方案不完整时，在原会话里继续追问，让它重新给出方案；也可以点击「修改方案」直接编辑。",
          "执行时的新会话不带规划时的讨论，所以背景、范围和验证方法都要写进方案。",
        ],
        shot: "plan",
        hotspot: "card",
        zoom: 1.4,
        alt: "计划模式已开启，回答下方是方案草稿卡片，带有修改方案和执行方案两个按钮",
      },
      {
        id: "pace",
        title: "拆成小步逐步执行",
        body: [
          "大任务拆成几步，每一步都能单独验证，例如先补测试、再改实现、最后清理。",
          "需要逐步把关时，在方案里写上「逐步执行，每完成一步运行验证、汇报结果并暂停」，确认后再让它继续下一步。",
        ],
        points: [
          "某一步做错时，只需重做这一步，不用推倒整个任务。",
          "每一步完成后，在「Git」面板查看 diff，结合「过程详情」里运行过的命令和测试结果，确认无误再提交。",
        ],
        shot: "pace",
        hotspot: "editor",
        zoom: 1.4,
        alt: "修改方案的编辑框：目标、三个步骤和逐步执行的要求",
      },
      {
        id: "cluster",
        title: "并行的任务交给集群",
        body: [
          "任务能拆成互不依赖的几块时，开启「集群」，由主 Agent 分给子 Agent 同时处理，例如分别调研几个模块，或按实现、测试、审查分工。",
          "小任务、前后依赖的步骤，或要改同一个文件的工作，交给一个 Agent 更快也更稳。",
        ],
        points: [
          "计划模式可以和集群一起使用：主 Agent 会等子任务都结束后再给出方案。",
          "允许子 Agent 写入时，让每个子任务负责不同的文件，避免互相覆盖。",
        ],
        shot: "cluster",
        hotspot: "team",
        zoom: 1.5,
        alt: "计划和集群都已开启，集群编组列出实现、测试、审查三个角色",
      },
      {
        id: "context",
        title: "一个话题一个会话",
        body: [
          "同一会话里的往来都会占用上下文。换一个不相关的任务时，在「会话」里点击「新会话」，旧会话仍可找回。",
          "回答下方的 `ctx` 是上下文的剩余比例。剩得不多时，先让 Agent 总结进展再开新会话接着做；支持压缩的 CLI 也可以发送 `//compact`。",
        ],
        shot: "context",
        hotspot: "ctx",
        zoom: 1.8,
        alt: "回答下方的 ctx 82% 标记和上下文用量明细",
      },
      {
        id: "memory",
        title: "长期记忆写进文件",
        body: [
          "新会话不记得以前的对话。需要长期遵守的约定，写进工作目录根部的说明文件：Codex 读取 `AGENTS.md`，Claude 读取 `CLAUDE.md`，每次会话开始时自动加载。",
          "内容保持简短具体：常用命令、代码约定、目录用途和不能做的事。",
        ],
        points: [
          "纠正过 Agent 的错误后，让它把这条规则写进说明文件，之后的会话也会遵守。",
          "同时使用 Codex 和 Claude 时，让两个文件保持一致。",
          "`docs/plan/` 里保存的方案也可以作为后续任务的背景资料。",
        ],
        shot: "memory",
        hotspot: "file",
        zoom: 1.3,
        alt: "编辑器里打开的 AGENTS.md：常用命令、代码约定和注意事项",
      },
    ],
  },
  {
    id: "remote",
    title: "远程工作区",
    summary: "通过 SSH 在远程主机的目录里工作。",
    icon: Boxes,
    steps: [
      {
        id: "create",
        title: "选择远程 SSH",
        body: [
          "新增智能体时把「位置」选为「远程 SSH」。",
          "智能体仍在运行 Orbit 的电脑上执行，通过 SSH 读写远程目录。",
        ],
        points: [
          "远程主机需要 SSH 和 SFTP。",
          "DeepSeek Harness 只支持本地工作区。",
        ],
        shot: "form",
        hotspot: "location",
        zoom: 1.6,
        alt: "新增智能体表单的位置开关：本地和远程 SSH，已选中远程 SSH",
      },
      {
        id: "connect",
        title: "连接与主机指纹",
        body: [
          "选择目标系统（Linux / POSIX 或 Windows），填写 SSH 主机、端口和用户名，然后点击「测试并连接 SSH」。",
          "首次连接要核对主机密钥指纹，确认后浏览并选择远程目录。",
        ],
        shot: "form",
        hotspot: "connection",
        zoom: 1.5,
        alt: "连接信息：目标系统 Linux / POSIX、SSH 主机 build.example.com、端口 22、用户名 deploy",
      },
      {
        id: "auth",
        title: "认证与记住密码",
        body: [
          "认证方式有密码、本地私钥文件和 SSH agent / 默认密钥。私钥文件路径指运行 Orbit 的电脑上的路径。",
          "勾选「记住密码」后，密码加密保存在服务端，服务重启后可以自动恢复连接。",
        ],
        tip: "需要重新登录时，点击工作台顶部的 SSH 连接标签，在弹出的菜单里点击「SSH 重新登录」；密码留空会使用已保存的密码。",
        shot: "auth",
        hotspot: "auth",
        zoom: 1.5,
        alt: "身份验证：认证方式选择密码，下方是 SSH 密码输入框和记住密码选项",
      },
      {
        id: "limits",
        title: "可用范围",
        body: [
          "远程工作区支持聊天、文件树、文本读写、文件上传、SSH 终端和 Git 面板。",
          "不提供语言服务、插件和调试，也没有全文搜索、大纲和快速打开；文本文件上限为 2 MiB。",
        ],
        points: [
          "远程 Git 要求所选目录是仓库顶层目录，并且远程账号能执行 `git`。",
          "要使用另一个远程目录，需要新建智能体。",
        ],
        shot: "auth",
        hotspot: "connect",
        zoom: 1.4,
        alt: "新增智能体表单底部的测试并连接 SSH 按钮",
      },
    ],
  },
  {
    id: "gateways",
    title: "消息网关",
    summary: "在 Telegram 和微信里继续同一个会话。",
    icon: MessagesSquare,
    steps: [
      {
        id: "page",
        title: "消息网关页面",
        body: [
          "在管理中心打开「消息网关」，这里配置 Telegram 接入，并完成个人微信的扫码绑定和连接状态查看。",
          "保存 Telegram 配置或扫码绑定微信后，需要重启应用才会生效。",
        ],
        shot: "page",
        hotspot: "tab",
        zoom: 1.4,
        alt: "管理中心左侧导航里选中了消息分组下的消息网关",
      },
      {
        id: "telegram",
        title: "接入 Telegram",
        body: [
          "打开「启用 Telegram」，填入 BotFather 创建的 Bot Token 和用户白名单。",
          "白名单填 Telegram 数字用户 ID，用逗号分隔；留空时接入关闭。",
        ],
        points: [
          "`to dev 帮我分析这个问题`：向 `dev` 的当前会话发消息。",
          "`to dev /new`：新建并切换会话。",
          "`/start`、`/help`：显示智能体列表和快捷操作。",
        ],
        shot: "telegram",
        hotspot: "telegram",
        zoom: 1.2,
        alt: "Telegram 配置：启用开关、Bot Token、用户白名单和最终回复广播",
      },
      {
        id: "weixin-scan",
        title: "微信扫码绑定",
        body: [
          "点击「开始扫码」，用个人微信扫码绑定。成功后账号 ID、Token 和 API 地址会自动保存，无需手动填写。",
          "私聊白名单为空时，扫码用户会自动加入白名单。网关只接收白名单用户的私聊文本，不支持微信群、图片、语音和文件。",
        ],
        points: ["Token 不会显示在页面和服务日志里。"],
        shot: "page",
        hotspot: "weixin",
        zoom: 1.4,
        alt: "消息网关顶部的微信状态：是否启用、绑定的账号、连接状态和开始扫码按钮",
      },
      {
        id: "shared",
        title: "共用会话",
        body: [
          "Telegram、微信和 Web 共用同一个智能体的会话和历史，可以在任意一端继续。",
          "网关只推送最终答复，执行过程、状态预览和集群子任务不会推送。",
        ],
        shot: "page",
        alt: "管理中心的消息网关页面",
      },
    ],
  },
  {
    id: "admin",
    title: "管理与扩展",
    summary: "用户与权限、主题、插件、更新和公网访问。",
    icon: Settings2,
    steps: [
      {
        id: "home",
        title: "管理中心",
        body: [
          "从智能体切换面板进入「管理中心」。左侧导航分为系统、成员、智能与服务、消息和诊断五组。",
          "「管理中心」入口需要管理权限，其中「邀请」还需要单独的邀请码权限。",
        ],
        points: ["「智能与服务」里的「定时任务」可以按计划新建会话，并向智能体发送固定指令。"],
        shot: "home",
        hotspot: "nav",
        zoom: 1.3,
        alt: "管理中心左侧导航：系统、成员、智能与服务、消息、诊断五个分组",
      },
      {
        id: "users",
        title: "用户与权限",
        body: [
          "「用户」里可以为非管理员账号开关各项能力，例如聊天、读文件、写文件、终端和 Git；管理员拥有全部能力。",
          "每个账号下方的「可操作 Bot」决定它能使用哪些智能体。",
        ],
        shot: "users",
        hotspot: "users",
        zoom: 1.3,
        alt: "用户权限列表：账号 alice 的各项能力开关和可操作 Bot",
      },
      {
        id: "invites",
        title: "邀请码",
        body: [
          "「邀请」里设置可用次数后点击「生成邀请码」，把邀请码交给需要注册的人。",
          "已有的邀请码可以增减次数、停用或删除。",
        ],
        shot: "invites",
        hotspot: "invites",
        zoom: 1.3,
        alt: "邀请页面：可用次数输入框、生成邀请码按钮和邀请码列表",
      },
      {
        id: "theme",
        title: "选择主题",
        body: [
          "「全局配置」里的「界面主题」从八套预置主题中选择，选择按账户分别保存。",
          "主题库随版本发布，所有账户都只能选择和应用，不能编辑、导入或删除主题。",
        ],
        shot: "home",
        hotspot: "theme",
        zoom: 1.5,
        alt: "全局配置的界面主题一行，当前主题是阿波罗计划",
      },
      {
        id: "plugins",
        title: "插件",
        body: [
          "工作台活动栏的「插件」里可以安装、启用、禁用和卸载插件。",
          "点击「安装插件」并选择插件父目录后，会递归查找并安装其中的 `plugin.json`。",
        ],
        points: ["远程工作区不提供插件。"],
        shot: "plugins",
        hotspot: "plugins",
        zoom: 1.3,
        alt: "侧边栏的插件视图列出 HDL Workbench、Vivado Waveform、Timing Report 等插件",
      },
      {
        id: "network",
        title: "更新与公网访问",
        body: [
          "「网络与升级」上方是公网访问状态；使用 Quick Tunnel 时可以启动、停止或重启 Tunnel。",
          "下方检查并准备更新；准备完成后仍需要手动确认才会应用。",
        ],
        points: ["Quick Tunnel 是临时地址，重启 Tunnel 后会更换。"],
        shot: "network",
        hotspot: "update",
        zoom: 1.2,
        alt: "网络与升级页面：公网访问卡片和程序版本卡片",
      },
    ],
  },
  {
    id: "tips",
    title: "技巧速查",
    summary: "常用快捷键和省时间的用法。",
    icon: Lightbulb,
    steps: [
      {
        id: "shortcuts",
        title: "常用快捷键",
        body: ["没有打开文件时，编辑器区域会列出快速打开文件和全文搜索两个快捷键；远程工作区里这两个快捷键不可用。"],
        points: [
          "`Ctrl+P`：快速打开文件。",
          "`Ctrl+Shift+F`：全文搜索。",
          "`Enter` 发送消息，`Shift+Enter` 换行。",
          "`Ctrl+S` 保存文件；在提交说明输入框里按 `Ctrl+Enter` 提交 Git 更改。",
          "`Esc`：退出本教程，或退出「调整窗口位置…」模式。",
        ],
        shot: "shortcuts",
        hotspot: "card",
        zoom: 1.6,
        alt: "编辑器区域的提示卡片：快速打开文件 Ctrl+P，全文搜索 Ctrl+Shift+F",
      },
      {
        id: "slash",
        title: "// 命令",
        body: [
          "想把 `/compact` 这类斜杠命令交给 CLI，可以写成 `//compact`。",
          "以 `//` 开头的消息会改写成以 `/` 开头再发送。",
        ],
        shot: "slash",
        hotspot: "composer",
        zoom: 1.6,
        alt: "聊天输入框里输入了 //compact",
      },
      {
        id: "endless",
        title: "继续与无尽模式",
        body: [
          "任务一次没做完时，点击回答下方的「继续」让 Agent 接着做。",
          "回答以错误结束时改用「无尽模式」：确认后先发送一条 `Continue`，之后遇到可重试的结果会按间隔自动发送。",
        ],
        tip: "运行期间可以随时终止任务，自动续接随之结束。",
        shot: "answer",
        hotspot: "continue",
        zoom: 1.8,
        alt: "回答下方的操作按钮，其中三角图标是继续任务，扬声器图标是朗读回答",
      },
      {
        id: "focus",
        title: "聚焦与收起窗口",
        body: [
          "需要更大的空间时，用窗口标题栏上的聚焦按钮让它铺满工作区，再点一次恢复。",
          "只想暂时收起某个窗口时，用顶部的四个布局开关。",
        ],
        shot: "shortcuts",
        hotspot: "focus",
        zoom: 1.6,
        alt: "终端窗口右上角的聚焦按钮",
      },
      {
        id: "elsewhere",
        title: "在手机上继续",
        body: [
          "配置消息网关后，可以在 Telegram 或微信里向同一个智能体发消息，会话和历史与 Web 共用。",
          "发送 `to <alias> <正文>` 指定智能体，`to <alias> /new` 新建会话。",
        ],
        shot: "gateway",
        alt: "管理中心的消息网关页面",
      },
    ],
  },
];
