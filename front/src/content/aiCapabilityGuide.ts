import type { LucideIcon } from "lucide-react";
import {
  BookOpenCheck,
  Bot,
  Braces,
  CheckCircle2,
  ClipboardCheck,
  Code2,
  FileSearch,
  GitBranch,
  GitPullRequest,
  ListChecks,
  MessageSquareText,
  Network,
  PanelsTopLeft,
  Search,
  ShieldCheck,
  Split,
  SquareTerminal,
  TestTube2,
  Workflow,
  Wrench,
} from "lucide-react";

export type GuideTone = "blue" | "green" | "orange" | "cyan" | "violet";

export type GuideQuickEntry = {
  id: string;
  label: string;
  description: string;
  icon: LucideIcon;
  tone: GuideTone;
};

export type GuidePathStep = {
  title: string;
  text: string;
  say: string;
  agent: string;
  accept: string;
  icon: LucideIcon;
  tone: GuideTone;
};

export type GuideCapability = {
  title: string;
  text: string;
  icon: LucideIcon;
  tone: GuideTone;
};

export type GuideTool = {
  title: string;
  text: string;
  icon: LucideIcon;
  tone: GuideTone;
};

export type GuidePromptTemplate = {
  title: string;
  purpose: string;
  prompt: string;
  tone: GuideTone;
};

export type GuideReference = {
  title: string;
  url: string;
};

export const aiCapabilityGuideUpdatedAt = "2026-05-27";

export const guideQuickEntries: GuideQuickEntry[] = [
  {
    id: "path",
    label: "新手路径",
    description: "从一句需求走到可验收结果。",
    icon: Workflow,
    tone: "blue",
  },
  {
    id: "toolbox",
    label: "工具箱",
    description: "文件、终端、Git、插件都能提供事实。",
    icon: Wrench,
    tone: "green",
  },
  {
    id: "cluster",
    label: "集群分工",
    description: "复杂任务拆给多个 agent 并行查证。",
    icon: Network,
    tone: "cyan",
  },
  {
    id: "acceptance",
    label: "验收闭环",
    description: "用测试、构建、diff、reviewer 收口。",
    icon: ClipboardCheck,
    tone: "orange",
  },
];

export const guidePathSteps: GuidePathStep[] = [
  {
    title: "第一步：告诉智能体你要做什么",
    text: "先说目标、成功标准、不能碰的文件和风险边界。需求越像任务单，智能体越少猜。",
    say: "我要修复登录页在窄屏错位。请先确认影响文件，不要改后端接口。",
    agent: "会把目标拆成范围、约束、风险和待查文件，必要时先问缺口。",
    accept: "你能看到明确改动范围、不会碰的区域和验收命令。",
    icon: MessageSquareText,
    tone: "blue",
  },
  {
    title: "第二步：让智能体先看真实文件",
    text: "不要只描述代码。给路径、日志、截图、diff，让智能体先读再判断。",
    say: "请先阅读 `front/src/app/App.tsx` 和相关测试，列事实后再改。",
    agent: "会打开文件、搜索引用、梳理状态流和已有测试保护。",
    accept: "结论里有文件路径、组件名、现有行为，而不是凭印象猜。",
    icon: FileSearch,
    tone: "blue",
  },
  {
    title: "第三步：用终端、Git、插件拿事实",
    text: "遇到环境、构建、波形、diff、版本问题，让工具给证据。",
    say: "请跑相关测试和 `git diff`，把失败输出和风险点列出来。",
    agent: "会运行命令、读取 Git 状态、打开专用插件视图或文件预览。",
    accept: "有命令、输出摘要、来源链接或插件视图结果支撑判断。",
    icon: SquareTerminal,
    tone: "green",
  },
  {
    title: "第四步：复杂任务拆给多个 agent",
    text: "大任务让 reader、implementer、tester、reviewer 分工，避免单线程漏看。",
    say: "主 agent 控边界；reader 只读查上下文；reviewer 只审 diff 和风险。",
    agent: "会并行收集事实、分配文件边界、合并结论，减少重复劳动。",
    accept: "每个 agent 有清楚职责，不抢同一文件，最终由主线汇总。",
    icon: Split,
    tone: "cyan",
  },
  {
    title: "第五步：用测试、构建、diff、reviewer 验收",
    text: "完成不等于说完成。让智能体拿出能复核的证据。",
    say: "请给验收表：检查项、命令、实际结果、剩余风险。",
    agent: "会跑测试、构建、检查 diff，并用 review 视角找回归。",
    accept: "你能用测试结果、diff 和风险清单决定是否合并。",
    icon: BookOpenCheck,
    tone: "orange",
  },
];

export const guideCapabilities: GuideCapability[] = [
  {
    title: "文件和代码阅读",
    text: "让智能体打开真实文件、搜索引用、对照测试，先建立事实地图。",
    icon: Code2,
    tone: "blue",
  },
  {
    title: "终端和验证",
    text: "运行测试、构建、脚本、搜索命令，失败时保留关键输出。",
    icon: TestTube2,
    tone: "green",
  },
  {
    title: "Git 和风险复核",
    text: "检查 diff、分支、暂存区和提交面，避免夹带无关改动。",
    icon: GitBranch,
    tone: "orange",
  },
  {
    title: "集群多 agent",
    text: "用多个 agent 并行读代码、验证、审查，主 agent 负责合并。",
    icon: Network,
    tone: "cyan",
  },
  {
    title: "插件视图",
    text: "把专用文件转成可读界面，例如 VCD 波形预览和重型数据窗口。",
    icon: PanelsTopLeft,
    tone: "violet",
  },
  {
    title: "结构化交付",
    text: "用清单、表格、JSON、验收表固定输出，便于复制和复核。",
    icon: Braces,
    tone: "green",
  },
];

export const guideTools: GuideTool[] = [
  { title: "聊天", text: "下达任务、迭代方案、拿总结。", icon: Bot, tone: "blue" },
  { title: "文件", text: "读代码、配置、日志、资料。", icon: FileSearch, tone: "blue" },
  { title: "搜索", text: "找引用、入口、旧实现。", icon: Search, tone: "cyan" },
  { title: "终端", text: "跑测试、构建、脚本。", icon: SquareTerminal, tone: "green" },
  { title: "Git", text: "看 diff、分支、提交风险。", icon: GitPullRequest, tone: "orange" },
  { title: "插件", text: "查看专用文件和重型视图。", icon: PanelsTopLeft, tone: "violet" },
  { title: "集群", text: "拆分 reader、tester、reviewer。", icon: Network, tone: "cyan" },
  { title: "验收", text: "测试、构建、review 闭环。", icon: CheckCircle2, tone: "orange" },
];

export const guidePromptTemplates: GuidePromptTemplate[] = [
  {
    title: "新手任务模板",
    purpose: "把目标、边界、验收一次说清。",
    prompt: "我要完成：<目标>。请先阅读相关文件，再给影响面和改动计划。不要改：<禁止范围>。完成后运行：<验证命令>，并给 diff 风险清单。",
    tone: "blue",
  },
  {
    title: "先读代码模板",
    purpose: "防止跳过真实上下文。",
    prompt: "请先只读分析：搜索相关入口、阅读现有实现和测试，列出事实、疑点、准备修改的文件。确认后再实施。",
    tone: "blue",
  },
  {
    title: "终端验证模板",
    purpose: "让命令输出成为证据。",
    prompt: "请运行必要测试/构建。若失败，先记录失败命令、关键输出、初步原因，再决定是否修复。",
    tone: "green",
  },
  {
    title: "集群分工模板",
    purpose: "多 agent 不重复、不抢文件。",
    prompt: "主 agent 控制方案和合并；reader 只读上下文；implementer 只改指定文件；tester 只跑验证；reviewer 只审 diff、风险和遗漏测试。",
    tone: "cyan",
  },
  {
    title: "Git 复核模板",
    purpose: "提交前减少夹带和回归。",
    prompt: "请检查 `git diff`：按文件列出改动目的、潜在回归、是否有无关变更、是否需要补测试。",
    tone: "orange",
  },
  {
    title: "验收表模板",
    purpose: "把完成定义写死。",
    prompt: "请给验收表：检查项、命令或证据、预期结果、实际结果、是否通过。不要使用未验证表述。",
    tone: "orange",
  },
];

export const guideCollaborationFlow = [
  { label: "给任务", icon: MessageSquareText, tone: "blue" as const },
  { label: "读文件", icon: FileSearch, tone: "blue" as const },
  { label: "用工具", icon: Wrench, tone: "green" as const },
  { label: "拆 agent", icon: Network, tone: "cyan" as const },
  { label: "跑验证", icon: TestTube2, tone: "green" as const },
  { label: "审 diff", icon: ShieldCheck, tone: "orange" as const },
];

export const guideClusterRoles = [
  { role: "主 agent", task: "定边界、分工、合并结果", tone: "violet" as const },
  { role: "reader", task: "只读代码、资料、日志", tone: "blue" as const },
  { role: "implementer", task: "只改指定文件", tone: "green" as const },
  { role: "tester", task: "跑测试、构建、复现", tone: "orange" as const },
  { role: "reviewer", task: "审 diff、风险、遗漏测试", tone: "cyan" as const },
];

export const guideAcceptanceLoop = [
  { label: "测试", text: "单测/组件测试/端到端", icon: TestTube2, tone: "green" as const },
  { label: "构建", text: "类型检查和打包", icon: SquareTerminal, tone: "green" as const },
  { label: "Diff", text: "只包含目标改动", icon: GitPullRequest, tone: "orange" as const },
  { label: "Review", text: "严重问题优先", icon: ShieldCheck, tone: "cyan" as const },
  { label: "交付", text: "说明结果和剩余风险", icon: ListChecks, tone: "blue" as const },
];

export const guideReferences: GuideReference[] = [
  {
    title: "Anthropic Building effective agents",
    url: "https://www.anthropic.com/engineering/building-effective-agents",
  },
  {
    title: "OpenAI Tools",
    url: "https://developers.openai.com/api/docs/guides/tools",
  },
  {
    title: "OpenAI Structured Outputs",
    url: "https://developers.openai.com/api/docs/guides/structured-outputs",
  },
  {
    title: "MCP Intro",
    url: "https://modelcontextprotocol.io/docs/getting-started/intro",
  },
  {
    title: "LangChain multi-agent handoffs",
    url: "https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs",
  },
  {
    title: "Microsoft AutoGen Agents",
    url: "https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/agents.html",
  },
  {
    title: "Anthropic Contextual Retrieval",
    url: "https://www.anthropic.com/engineering/contextual-retrieval",
  },
];

export const guideWelcomeTitle = "欢迎使用面向协作开发的智能体操作系统";
export const guideWelcomeLead = "本页面是 AI 协作开发入门指南。它会帮助你学会如何给智能体任务、提供上下文、调用工具、拆分子任务、验证结果。";
export const guideWelcomeSummary = "你不需要记复杂概念，只要按新手路径把目标、事实、工具、分工、验收说清，智能体就能像协作开发成员一样读代码、改代码、跑验证、做 Git 复核。";
