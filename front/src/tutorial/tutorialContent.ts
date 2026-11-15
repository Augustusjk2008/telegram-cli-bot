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

/** Chapters in cover order. A chapter without steps is shown as 编写中. */
export const TUTORIAL_CHAPTERS: TutorialChapter[] = [
  {
    id: "start",
    title: "快速上手",
    summary: "登录、切换 Bot、创建智能体，认识界面的各个区域。",
    icon: Rocket,
    steps: [],
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
        tip: "有管理权限的账号可以在管理中心的「全局配置」里关闭「Enter 键发送消息」，之后 `Enter` 只换行。",
        shot: "composer",
        hotspot: "composer",
        zoom: 1.7,
        alt: "桌面工作台，右侧聊天窗口底部的输入框里已经写好一条任务",
      },
      {
        id: "model",
        title: "模型与附件",
        body: [
          "输入框下方的两个下拉框用来选择「模型」和「思考深度」。",
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
          "任务运行时，输入框右下角的「发送」会变成「终止任务」。",
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
          "回答以错误结束时，旁边会多出「无尽模式」：此后遇到可重试的未完成或错误结果，会按间隔自动发送 `Continue`。",
        ],
        points: [
          "默认间隔 120 秒，可用环境变量 `ENDLESS_CONTINUE_DELAY_SECONDS` 调整。",
          "终止任务，或遇到不可重试的错误时，自动续接结束。",
        ],
        shot: "answer",
        hotspot: "continue",
        zoom: 1.8,
        alt: "回答下方的操作按钮：ctx 标记、收藏回答、继续和复制",
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
          "点击「完成」或按 `Esc` 退出，「恢复默认」撤销调整。",
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
          "文件区、编辑器和终端的标题栏上各有一个聚焦按钮。点击后这个窗口铺满工作区，其他窗口暂时隐藏。",
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
    steps: [],
  },
  {
    id: "terminal",
    title: "终端",
    summary: "多标签终端与快捷命令。",
    icon: SquareTerminal,
    steps: [],
  },
  {
    id: "git",
    title: "Git 与 GitHub",
    summary: "查看改动、提交、分支、远端与 GitHub 账号。",
    icon: GitBranch,
    steps: [],
  },
  {
    id: "cluster",
    title: "集群协作",
    summary: "让主 Agent 组建团队，把任务分给多个子 Agent。",
    icon: Network,
    steps: [],
  },
  {
    id: "remote",
    title: "远程工作区",
    summary: "通过 SSH 在远程主机的目录里工作。",
    icon: Boxes,
    steps: [],
  },
  {
    id: "gateways",
    title: "消息网关",
    summary: "在 Telegram 和微信里继续同一个会话。",
    icon: MessagesSquare,
    steps: [],
  },
  {
    id: "admin",
    title: "管理与扩展",
    summary: "用户与权限、主题、插件、更新和公网访问。",
    icon: Settings2,
    steps: [],
  },
  {
    id: "tips",
    title: "技巧速查",
    summary: "常用快捷键和省时间的用法。",
    icon: Lightbulb,
    steps: [],
  },
];
