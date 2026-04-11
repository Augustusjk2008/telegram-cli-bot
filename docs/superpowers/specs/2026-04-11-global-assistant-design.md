# Global Assistant Design

日期：2026-04-11

## 目标

为项目设计一套“本机唯一 assistant”的长期学习与升级方案。

该方案的目标是：

1. `assistant` 作为当前电脑唯一的长期助手存在，而不是某个项目私有助手。
2. 本项目只作为 assistant 的 Telegram/Web 入口与管理面，不承载 assistant 的记忆本体。
3. assistant 支持持续学习，但长期知识、技能、提示词和代码升级都必须经过人工审批后才生效。
4. assistant 创建后固定工作路径不可修改；如需换路径，只能删除 bot 后重建。
5. 设计保持跨平台友好，不把 assistant 的核心数据绑定到当前仓库。

## 用户确认的约束

- 整台电脑只需要一个 assistant。
- 本项目中最多允许创建一个 `assistant` bot。
- `assistant` 创建时必须设置工作路径，之后不允许修改。
- 如需更换 assistant 工作路径，只能删除该 bot 后重新创建。
- assistant 的对话历史、工作记忆、长期记忆、proposal、upgrade 不进入本项目。
- assistant 自身数据全部存放在自己的固定工作路径内。
- assistant 可自我升级知识、技能、提示词、配置。
- assistant 可生成代码升级 proposal 和 patch，但必须经人工审批后才能应用。

## 现状

- 当前运行态只有 `cli` 和 `assistant` 两种 bot mode；`assistant` 已收敛为固定工作目录的 CLI 受限变体。
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/__init__.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/handlers/__init__.py) 中 `assistant` 直接复用 CLI handler surface。
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/manager.py) 已禁止修改 `assistant` 默认工作目录。
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/sessions.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/sessions.py) 会在恢复 session 时把 `assistant` 的真实工作目录对齐回默认值。
- [C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/session_store.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/session_store.py) 当前会持久化 history、browse_dir、session_id 等会话信息；这不符合“assistant 数据自管”的目标。

当前现实是：项目里还没有真正独立的 assistant memory/runtime，只存在面向 CLI 的会话存储与固定路径约束。

## 方案比较

### 方案 A：纯文档树

- assistant 的知识全部落在固定目录文件树中。
- 不额外引入本地索引数据库。

优点：

- 最透明，最容易用 Git 或文件系统检查。
- 跨平台简单。

缺点：

- 检索、审批、提案生命周期和评测追踪较弱。

### 方案 B：文档树加本地 SQLite 索引

- 文件是知识本体。
- SQLite 只存 chunk 索引、状态、提案关系、评测记录。

优点：

- 兼顾可读性、审批流和检索效率。
- 适合“文件可审 + 状态可查”的 assistant 数据模型。

缺点：

- 比纯文件多一层元数据管理。

### 方案 C：完整 agent 平台化

- 在方案 B 基础上进一步引入更重的多代理编排和协议层。

优点：

- 未来扩展空间最大。

缺点：

- 对当前项目属于明显过度设计。

## 已选方案

采用方案 B：文档树加本地 SQLite 索引。

理由：

- assistant 的真知识需要长期可读、可审、可迁移，文件最适合做知识本体。
- 你要求审批式长期写入和代码升级 proposal，这天然需要状态索引和审计关系。
- 当前项目还没有独立 assistant runtime，直接走重平台化方案收益不高。

## 总体架构

assistant 的总体结构分为两部分：

### 宿主层

由本项目承担，负责：

- 单例 `assistant` bot 的创建、删除、启动、停止
- Telegram/Web 聊天入口
- proposal / upgrade 的审批入口
- 已批准 patch 的验证、应用、回滚入口

宿主层不保存 assistant 的历史和记忆本体。

### assistant 私有数据层

由 assistant 固定工作目录承担，作为唯一真相来源。

建议目录：

```text
<assistant_workdir>/
  .assistant/
    manifest.yaml
    state/
    inbox/
    memory/
    proposals/
    upgrades/
    evals/
    audit/
    indexes/
    prompts/
```

本项目重启后，只通过 `working_dir -> .assistant/manifest.yaml` 恢复 assistant 状态入口，而不是从项目级 `.session_store.json` 恢复 assistant 历史。

## 核心边界

### 身份边界

- 当前电脑上 assistant 是单例长期身份。
- 本项目中最多只允许一个 `assistant` bot。
- 其余托管 bot 仍可继续使用 `cli` 模式。

### 路径边界

- 创建 assistant 时必须提供 `working_dir`。
- assistant 创建后禁止修改真实工作路径。
- Web 文件浏览若保留“浏览目录”能力，也应作为 assistant 私有状态存入 `<assistant_workdir>/.assistant/state/`，而不是项目 session store。
- 变更路径的唯一方式是删除 assistant bot 后重新创建。

### 存储边界

以下内容不得进入本项目 session store：

- 对话历史
- 工作记忆
- 长期知识
- 技能库
- proposal
- upgrade
- assistant 浏览上下文

这些内容全部进入 `<assistant_workdir>/.assistant/`。

## 数据模型

assistant 内部使用以下最小对象集：

- `capture`：原始输入，来自对话、命令结果、报错、人工纠正、成功案例。
- `working_memory`：短期记忆，自动写入，自动过期，不审批。
- `knowledge`：长期知识，审批后生效。
- `skill`：可复用方法，审批后生效。
- `proposal`：候选变更，可指向知识、技能、提示词、配置或代码补丁。
- `upgrade`：进入升级生命周期的 proposal，强调评测、应用和回滚。

推荐落点：

```text
.assistant/
  inbox/captures/
  memory/working/
  memory/knowledge/
  memory/skills/
  proposals/
  upgrades/pending/
  upgrades/approved/
  upgrades/applied/
  evals/runs/
  audit/events.jsonl
  indexes/chunks.sqlite
```

规则：

- Markdown/YAML/目录结构保存知识本体。
- SQLite 只存索引、状态和关系，不存唯一真相。

## 学习写入流

默认流程为：

`capture -> working_memory 或 proposal -> 预检查 -> 人工审批 -> 生效 -> 审计`

具体规则：

- `working_memory` 可自动写入和自动过期。
- `knowledge / skill / prompt / config` 必须审批后才生效。
- `code patch` 只能以 proposal / upgrade 形式存在，不能自动应用。
- 未批准 proposal 默认不参与检索注入。

## 检索与注入

每次对话采用三路召回：

- 工作记忆
- 已批准长期知识
- 已批准技能

检索优先级：

1. 用户当前显式提到的文件、目录、模块、命令
2. 当前会话热上下文
3. 已批准长期知识和决策
4. 已批准技能

未批准 proposal 默认不进入主上下文。

注入方式采用模型无关的“上下文编译器”：

`user_text -> context planner -> retrieval -> prompt compiler -> run_cli_chat`

这样可兼容当前以 CLI 为中心的运行方式，不绑定某个特定模型 SDK。

冲突优先级固定为：

`用户当前要求 > 实时文件/命令结果 > 已批准决策 > 已批准知识 > 工作记忆 > 未批准 proposal`

## 升级路径

### 自我知识升级

升级 `knowledge / skill / prompt / config`：

`capture -> proposal -> 审批 -> 写入 .assistant -> 重建索引 -> 生效`

### 自我代码提案升级

assistant 可生成 patch proposal，但不能自应用：

`capture -> code proposal + patch + eval plan -> 审批 -> 宿主验证/应用 -> 生效或回滚`

### 宿主代码升级

当你更新本项目代码时，由宿主负责兼容 assistant 数据目录：

`启动 -> 读取 .assistant/manifest.yaml -> 检查 schema_version -> 如需迁移则执行 migrator`

assistant 不能自行修改 schema；所有目录结构和元数据迁移都由宿主执行。

建议在 `manifest.yaml` 中保留：

- `assistant_id`
- `schema_version`
- `min_host_version`
- `created_at`

## 管理面约束

本项目对 assistant 只提供以下能力：

- 创建/删除 assistant bot
- 启动/停止入口
- 展示待审批 proposal / upgrade
- 批准/拒绝
- 对已批准 patch 做应用前验证和回滚

不允许的行为：

- 创建第二个 assistant bot
- 修改 assistant 根路径
- 将 assistant 数据写入项目 session store
- 让未审批 proposal 进入默认检索
- 让 assistant 自动应用代码 patch

## 风险

- 若宿主层和 assistant 私有数据层边界不清，会再次把 assistant 记忆写回本项目。
- 若未批准 proposal 被错误注入，会导致 assistant 被候选知识污染。
- 若路径锁定和删除重建规则不清晰，assistant 身份会和数据目录脱节。
- 若宿主升级不管理 schema_version，后续 assistant 数据迁移会失控。

## 非目标

- 不把 assistant 设计成每个项目一个实例。
- 不允许 assistant 自动应用自己的代码补丁。
- 不把 assistant 记忆绑定到当前仓库。
- 不在本次设计中引入重型多代理平台。
