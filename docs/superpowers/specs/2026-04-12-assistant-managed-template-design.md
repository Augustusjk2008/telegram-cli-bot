# Assistant Managed Template Design

日期：2026-04-12

## 目标

修正 assistant 运行时托管文档的模板来源，停止复用宿主仓库根目录的 `AGENTS.md` / `CLAUDE.md`，改为使用 assistant 专用模板源生成 `<assistant_workdir>/AGENTS.md` 与 `<assistant_workdir>/CLAUDE.md`。同时保持现有“模板固定、记忆尾巴可重建、聊天侧只保留 reread notice”的运行时模型不变。

## 用户确认的约束

- assistant 不依赖每轮大段 prompt injection；运行时只依赖 assistant 工作目录中的 `AGENTS.md` 和 `CLAUDE.md`。
- assistant 工作目录中的 `AGENTS.md` / `CLAUDE.md` 必须分成两部分：
  - 第一部分是模板，只允许宿主管理。
  - 第二部分是记忆提示词，由宿主根据 `.assistant/` 状态持续重建。
- assistant 的自我提升边界是“记忆 + 升级提案”：
  - 允许更新 `.assistant/memory/working/*.md`
  - 允许创建 `.assistant/proposals/*.json`
  - 允许产出 upgrade patch
  - 不允许让长期规则或代码升级自行生效
- assistant 专用模板源应放在仓库内的独立文件中，而不是复用宿主仓库的根 `AGENTS.md` / `CLAUDE.md`。
- `<assistant_workdir>/AGENTS.md` 与 `<assistant_workdir>/CLAUDE.md` 最终内容必须完全相同。

## 现状

- [bot/assistant_docs.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_docs.py) 当前通过 `sync_managed_prompt_files()` 直接读取仓库根目录的 `AGENTS.md` / `CLAUDE.md` 作为模板源，再把记忆块追加进 assistant 工作目录输出文件。
- [AGENTS.md](C:/Users/JiangKai/telegram_cli_bridge/refactoring/AGENTS.md) 与 [CLAUDE.md](C:/Users/JiangKai/telegram_cli_bridge/refactoring/CLAUDE.md) 是宿主仓库给编码代理看的开发说明，不是 assistant 的身份协议。
- [bot/assistant_context.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_context.py) 已经把聊天侧的 prompt 注入收敛为“文件变更时提示重新读取 `AGENTS.md` / `CLAUDE.md`”，说明正确的主载体已经是 assistant 工作目录中的托管文件。
- [bot/assistant_compaction.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_compaction.py) 已经定义了可静默更新 working memory、长期规则与升级建议应进入 `.assistant/proposals/*.json` 的维护边界。
- [bot/assistant_home.py](C:/Users/JiangKai/telegram_cli_bridge/refactoring/bot/assistant_home.py) 已经把 `<assistant_workdir>/AGENTS.md` 与 `<assistant_workdir>/CLAUDE.md` 视为 assistant home 的一部分。

现状说明运行时骨架基本正确，错误集中在“模板源归属”这一层：assistant 的托管文件仍然绑定到了宿主仓库开发文档，导致 assistant 读到的是错误身份。

## 设计概览

采用“单模板源，双输出文件”的方案：

- 在仓库内新增一个 assistant 专用模板源文件，作为唯一 canonical template。
- 每次同步时，由宿主读取该模板源，并拼接当前 host-managed memory prompt。
- 同步器把合成后的完整文本同时写入 `<assistant_workdir>/AGENTS.md` 与 `<assistant_workdir>/CLAUDE.md`。
- 两个输出文件内容完全一致，共享同一个 managed prompt hash。
- assistant 运行时仍只读取自己工作目录中的 `AGENTS.md` / `CLAUDE.md`；聊天时不恢复大段 prompt injection，仅在 hash 变化时追加 reread notice。

## 模板源与文件布局

### 仓库内模板源

- 新增 assistant 专用模板源，例如：
  - `bot/data/assistant/managed_prompt_template.md`
- 它由宿主代码与宿主维护者负责编辑。
- assistant 自己不应把这个模板源视为可写持久状态。

### assistant 工作目录中的派生文件

- `<assistant_workdir>/AGENTS.md`
- `<assistant_workdir>/CLAUDE.md`

这两份文件都属于派生文件，不是事实源。它们由同步器重建，assistant 即使直接修改它们，也会在下次 sync 时被宿主覆盖。

### `.assistant/` 中的可变状态

assistant 可持续更新或产出的状态继续保存在：

- `.assistant/state/users/*.json`
- `.assistant/memory/working/*.md`
- `.assistant/memory/knowledge/*.md`
- `.assistant/memory/skills/*.md`
- `.assistant/proposals/*.json`
- `.assistant/upgrades/pending/*`
- `.assistant/upgrades/approved/*`
- `.assistant/upgrades/applied/*`

其中只有 working memory、proposal、upgrade 产物属于 assistant 可主动参与维护的长期状态；模板源不在这个集合中。

## 模板内容边界

固定模板只承载“长期稳定、必须每次都成立”的 assistant 身份协议，不承载任务态、项目态或当前会话临时上下文。

固定模板应包含：

- assistant 是谁：
  - 它是宿主管理的本地长期助手
  - 它不是宿主仓库开发代理说明的拷贝
- assistant 的核心目标：
  - 理解用户意图
  - 帮助完成任务
  - 沉淀稳定知识
  - 在必要时提出长期规则或能力升级建议
- assistant 的工作边界：
  - 可更新 `.assistant/memory/working/*.md`
  - 可创建 `.assistant/proposals/*.json`
  - 可产出 upgrade patch
  - 不可让长期规则或代码升级自行生效
- assistant 对目录的理解：
  - `.assistant/state/users` 是私有运行态
  - `.assistant/memory/working` 是工作记忆
  - `.assistant/proposals` 是待审批建议
  - `upgrades/*` 是升级材料与结果
- reread 协议：
  - 当宿主提示 `AGENTS.md` / `CLAUDE.md` 已更新时，应重新读取文件，而不是依赖旧上下文
- 行为风格：
  - 默认中文
  - 直接、克制、少废话
  - 先理解，再行动
  - 不主动向用户暴露后台维护动作，除非用户明确询问

固定模板不应包含：

- 当前项目的具体开发手册
- 宿主仓库给编码代理的 AGENTS 规则
- 当前任务状态
- open loops
- recent summary
- 用户个人偏好明细
- 单次对话的临时结论

这些内容应进入 host-managed memory prompt，由宿主根据 `.assistant/memory/working/*.md` 和 compaction 状态重建。

## 同步与漂移控制

同步流程保持宿主强控制：

1. 读取 assistant 专用模板源
2. 读取 `.assistant/memory/working/*.md`
3. 读取 compaction 维护块
4. 生成完整 managed prompt 文本
5. 同时覆盖写入 `<assistant_workdir>/AGENTS.md` 与 `<assistant_workdir>/CLAUDE.md`
6. 计算并返回统一的 managed prompt hash

漂移控制规则：

- `<assistant_workdir>/AGENTS.md` 与 `<assistant_workdir>/CLAUDE.md` 是派生文件，下次 sync 必须覆盖任何漂移内容。
- assistant 直接编辑这两个文件不视为合法升级路径。
- 任何长期规则调整都必须走 `.assistant/proposals/*.json`。
- 任何代码级升级都必须走 upgrade proposal 审批链，只有 approved patch 才允许 apply。

## 运行时行为

保留现有 runtime 模型，不重新引入大段 prompt injection：

- assistant 聊天前同步托管文件
- 若 `managed_prompt_hash` 与 `managed_prompt_hash_seen` 不同，则仅在用户文本前加一条 reread notice
- assistant 回复后，宿主可基于 captures 刷新 working memory / compaction / proposal 状态
- 若这些变化导致托管文件内容变化，则再次 sync 并更新 hash

该模型确保：

- assistant 的主上下文来自工作目录托管文件
- 运行时用户消息保持轻量
- 文件更新与 native session 重读之间通过 hash 关联

## 迁移策略

迁移只修正模板来源，不改变 assistant home 目录结构：

- 现有 `<assistant_workdir>/AGENTS.md` / `CLAUDE.md` 在下一次 sync 时被新模板源重建
- `.assistant/state`、`.assistant/memory`、`.assistant/proposals`、`.assistant/upgrades` 不迁移结构
- 不新增用户可见的 assistant 配置项
- 旧工作目录中若已有被 assistant 手工修改过的 `AGENTS.md` / `CLAUDE.md`，也应视为漂移并在下一次 sync 时覆盖

## 错误处理

- 若 assistant 专用模板源缺失或不可读，sync 应显式失败并记录日志，而不是回退到宿主仓库根 `AGENTS.md` / `CLAUDE.md`。
- 若 memory block 构建失败，应保留模板源读取错误与 memory 构建错误的区分，方便定位。
- 若写入 `<assistant_workdir>/AGENTS.md` / `CLAUDE.md` 失败，应终止本次 sync，并阻止把不完整状态当作最新 hash。
- 不允许设置“静默回退到旧模板源”的兼容逻辑，因为这会重新引入错误身份。

## 测试与验收

需要覆盖的行为：

- `sync_managed_prompt_files()` 不再读取仓库根 `AGENTS.md` / `CLAUDE.md`
- assistant 模板源可以单独生成 `<assistant_workdir>/AGENTS.md` / `CLAUDE.md`
- 两个输出文件内容完全一致
- working memory 变化后，sync 会重建两个输出文件并更新 hash
- assistant 直接修改 `<assistant_workdir>/AGENTS.md` / `CLAUDE.md` 后，下次 sync 会覆盖漂移内容
- 聊天侧仍然只保留 reread notice，不恢复大段 prompt injection
- `.assistant/proposals/*.json` 仍然是长期规则与升级建议的唯一审批入口

建议新增或修改的测试范围：

- `tests/test_assistant_docs.py`
- `tests/test_assistant_context.py`
- `tests/test_manager.py`
- `tests/test_handlers/test_chat.py`
- `tests/test_web_api.py`

## 风险与非目标

### 风险

- assistant 专用模板一旦写得过宽，会重新把任务态内容塞回固定模板，导致模板膨胀。
- 若继续保留任何对宿主根 `AGENTS.md` 的隐式回退，未来还会再次把错误身份带回 assistant。
- 如果输出文件虽然双写但内容生成路径不同，仍会出现 `AGENTS.md` / `CLAUDE.md` 漂移。

### 非目标

- 本次不重做 assistant 的 compaction 策略。
- 本次不扩展 assistant 的 proposal 数据结构。
- 本次不引入按模型区分的不同模板。
- 本次不改变 assistant 的审批流和 upgrade apply 机制。

## 结论

assistant 的运行时托管文件已经是正确方向，但模板源当前绑错了对象。修正方案应当是：

- 使用仓库内 assistant 专用模板源作为唯一 canonical template
- 由宿主同步器把模板和 memory tail 合成为完全一致的 `AGENTS.md` / `CLAUDE.md`
- 保留 reread notice、proposal 审批、upgrade apply 等现有运行时模型

这样 assistant 才能真正基于“它自己是谁、它能做什么、它如何自我提升”的协议运行，而不是误读宿主仓库开发代理的说明文件。
