# Codex server 语音交互路线图

日期：2026-10-06。状态：M0、P0 已通过；M1 待浏览器验收。

当前已确认文字工具基线、实验 schema 字段、探测器的单 reader、鉴权、日志脱敏和停止操作契约，以及目标浏览器中的真实麦克风、WebRTC 媒体、语音字幕、语音工具任务、历史读取和中断结果。产品侧 codex_server 已有 realtime 接入，功能开关默认关闭；M1–M4 仍待逐项真实验收。

## 1. 目标和范围

目标是在现有 codex_server 聊天中提供持续语音交流。语音输入、Codex 执行、语音反馈和文字历史属于同一会话。执行期间可以补充要求、追问、停止播报或停止任务。

首版只覆盖 codex_server，保留 execution_mode=cli、现有权限和普通文字聊天。不扩展其他 CLI，不新增独立语音助手会话，不引入通用语音供应商框架，不持久化原始音频。

浏览器负责麦克风、播放、字幕、控制条和设备释放。TCB 负责权限、会话归属、连接协商、单 reader 事件分发和状态同步。Codex runtime 负责普通任务与语音事件的统一分发。M2 以后才把语音任务写入现有 ChatStore 历史链路。

## 2. 当前事实

- 本机 Codex CLI 为 0.160.0，realtime_conversation 已启用。
- 本机实验 schema 可见 thread/realtime/start、appendAudio、appendText、appendSpeech、stop、listVoices、字幕和音频事件。schema 存在不等于账号、额度、媒体或部署可用。
- CodexServerClient.start() 的 experimental_api 默认关闭。产品语音入口显式开启实验 API，runtime 由唯一 reader 分发普通 turn 和语音事件；功能开关 TCB_CODEX_SERVER_VOICE_ENABLED 默认关闭。
- 探测器显式开启实验 API，使用独立 app-server、单一 client.events() reader、loopback 一次性 token、HttpOnly cookie 和脱敏 JSONL 日志。
- 已验证的文字基线：--check-text 读取固定只读 fixture，工具结果和回答均包含 ORBIT-417。
- 当前探测器使用 read-only sandbox、never approval、无网络和关闭的已配置 MCP server。它不能证明目标聊天的写操作权限、真实语音额度或生产部署可用。
- 当前 M0 已完成隔离探测器的真实浏览器和语音工具任务验证；生产接入、补充/插话、历史恢复、额度和计费仍未验证。

## 3. 必须保持的契约

- 会话按 (bot_id, shared_user_id, agent_id) 隔离，Web 用户 ID 继续通过 chat_session_user_id() 归一化。语音连接还必须绑定 conversation、Codex thread 和发起连接的客户端。
- 同一会话首版只允许一个活跃语音连接。其他标签页显示占用状态，不自动抢占。关闭连接只能影响自己的语音连接。
- 同一 Codex runtime 只能有一个 protocol reader。语音连接不能调用 client.events() 建立第二个 reader。
- 语音连接生命周期和任务 turn 生命周期分离。没有普通文本 turn 时，runtime 仍必须分发语音事件和语音触发任务。
- meta/status/trace/done、status.preview_text、顶层 turn_id 和 assistant_message_id 保持现有普通 CLI SSE 契约。CLI trace 继续进入 NativeAgentTranscript，使用 mode="cli"。
- 同一段语音只能有一条任务提交路径。原生链路已经提交后，字幕只记录和展示，不能再次作为普通文本发送。
- 去重必须使用协议事件标识和生命周期。不能只按转写文本去重。
- “结束语音”只关闭语音连接和媒体设备；“停止任务”才请求 turn/interrupt。runtime 关闭只能用于真正关闭 runtime，不能作为结束语音的快捷实现。

## 4. 证据分层

每项能力必须标注证据层级：

| 层级 | 可以证明 | 不能证明 |
| --- | --- | --- |
| 代码/单测 | reader 唯一性、事件路由、边界状态、去重和停止操作请求 | 真实账号权限、浏览器媒体和上游服务行为 |
| schema/协议 | 方法名、字段、请求响应形状和版本约束 | 真实媒体协商、音频到达、语音模型额度和工具执行 |
| 真实浏览器证据 | 麦克风、SDP/ICE、远端音轨、播放、字幕、任务和关闭事件 | 未覆盖的浏览器、网络拓扑和账号情形 |

schema 或 mock 通过时，不能把真实语音标记为通过。M0 的真实语音通过必须有目标浏览器的事件日志和实际媒体证据。

## 5. P0 设计闸门

P0 设计已于 2026-10-06 经用户确认通过。以下契约作为后续实现和验收依据；设计通过不等于 M1–M4 实测通过。

- TCB 端点、请求体、事件 envelope、版本协商和错误码。端点必须复用现有 Bot 权限、CAP_CHAT_SEND、会话用户归一化、Bot 访问检查和 WebSocket Origin/CSRF 边界。
- 会话租约的键、获取、续租、释放和过期行为。必须覆盖单连接、跨 conversation 隔离、跨标签页占用和客户端断线。
- 浏览器控制通道、WebSocket、WebRTC data channel、SDP offer/answer、ICE candidate 的关系。明确全量 ICE 或 trickle ICE，以及 /node/<node ID>/ 转发下的行为。
- 一个 protocol reader 到 runtime、任务和浏览器订阅者的事件路由。定义有界队列、事件优先级、慢客户端和未知结果处理。
- 语音状态机和 runtime 状态机。至少区分 idle、starting、active、stopping、closed、error、unknown；明确结束语音、停止播报、停止任务、runtime close 的状态转换。
- 重连规则。重连先恢复已有状态，不自动重发已接收指令；请求结果未知时不重试。
- M2 持久化字段和幂等键。至少覆盖本地 turn_id、Codex turn ID、realtime_session_id、item ID、协议事件序号、转写定稿状态和任务提交键。
- M1 交付前建立配置级功能开关，默认关闭。关闭后普通文字聊天必须继续可用。

### 5.1 M1 固定协议契约

本轮实现固定以下边界，作为代码和回归测试的共同依据：

- 控制协议版本为 `1`。WebSocket 完成鉴权和会话校验后发送 `voice.state`，其中 `state=idle` 表示连接已建立；后续消息统一使用带 `type`、单调 `seq` 和连接 `connection_id` 的 envelope。语音错误使用 `voice.error`，至少保留 `code`、`message` 和当前 `state`。
- 客户端连接参数必须包含 `agent_id`、`conversation_id`、`session_epoch`、`protocol_version` 和 `execution_mode=cli`。服务端只接受与当前 `(bot_id, chat_session_user_id(user_id), agent_id)`、活动 conversation、session epoch、工作目录和实验 API 完全一致的绑定；会话切换、目录变化或 agent 变化按 `voice_session_changed` 收敛。
- 租约键固定为 `(bot_id, shared_user_id, agent_id, conversation_id)`。租约连接状态和语音任务状态分别记录；获取、心跳/续租、客户端断线释放、TTL 清理和未知结果都必须可重复执行。未知 RPC 不自动重试，后续事件、终态或 TTL 必须提供回收路径；没有活动语音任务的未知连接不能永久占用文字聊天。
- 连接状态按 `idle → starting/negotiating → active → stopping → closed/error/unknown` 收敛。结束语音只停止 realtime 媒体，不发送 `turn/interrupt`；活动语音任务在浏览器连接结束后继续由 runtime 观察，runtime 真正关闭时发布 `runtime/closed` 或 `unknown`。
- 当前采用全量 ICE，客户端使用固定 `iceServers` 配置；`/node/<node ID>/` 只改变 HTTP/WebSocket 转发前缀，不改变消息 envelope、鉴权和租约键。
- `client.events()` 只能由 runtime 的单一 reader 消费。该 reader 同时向普通 turn 流和语音订阅者分发事件；语音连接、浏览器 data channel 和控制 WebSocket 不得建立第二个 reader。

## 6. M0：隔离探测器可行性验证

M0 只验证隔离探测器中的原生协议、真实媒体和真实语音工具任务。M0 不接入生产 Web API，不修改生产 runtime，不写入 TCB ChatStore。

### 6.1 当前检查项

代码/单测：

- [x] 已运行探测器、client、runtime、事件 mapper 和配置测试：77 passed。
- [x] 单 reader、事件关联字段、脱敏日志、字幕不重复提交、thread/realtime/stop 与 turn/interrupt 分离已有单测覆盖。
- [x] 已记录 thread/read 历史读取的兼容性；当前 includeTurns=true 已出现分页历史弃用提示，不能把该提示忽略为成功。

schema/协议：

- [x] 已确认 0.160.0 的 realtime 方法、WebRTC transport、远端 SDP 事件和停止请求形状；WebRTC 启动请求显式使用 `version=v3`，以匹配 AVAS 所需的 `quicksilver=v2`。
- [x] 已确认 account 类型为 chatgpt、功能已启用，真实服务链路已通过 M0；语音额度和计费尚未确认。
- [x] 已在同一测试 thread 确认语音可附着已有 thread，以及语音任务 turn 的创建和完成路径。
- [ ] 普通任务执行期间的补充和插话行为仍待后续阶段验证。

真实浏览器证据：

- [x] 麦克风授权成功，建立 WebRTC offer/answer 和 ICE。
- [x] 收到远端音轨并实际播放。
- [x] 收到用户和助手定稿转写。
- [x] 完成一次真实语音工具任务，观察工具执行、助手语音反馈和 thread 历史。
- [x] 已分别验证结束语音和停止任务的真实结果；停止播报的本地播放控制留作后续专项检查。

### 6.2 手工验收步骤

这些步骤需要用户手工启动探测器和目标浏览器。本路线图不启动服务或真实语音会话。

1. 先运行代码/单测命令，确认单测通过。
2. 运行 python -m scripts.codex_voice_probe --check-text，确认文字基线读取 fixture 并返回 ORBIT-417。
3. 用户运行 python -m scripts.codex_voice_probe --host 127.0.0.1 --port 0，只使用打印的一次性 loopback URL，在目标浏览器 claim 一次并连接事件通道。
4. 授权麦克风，点击“开始语音”。保存探测器 JSONL 和浏览器事件时间线；联调期间可点击“读取 M0 证据”，退出探测器时也会打印 m0_validation 摘要。
5. 说出一个固定的只读任务，例如读取 fixture 的 section two verification_code。等待任务完成和语音回答。
6. 检查事件顺序和关联字段。至少必须能观察到下列证据：

   | 机器证据 | 来源或含义 |
   | --- | --- |
   | realtime_started | 收到 thread/realtime/started 和 realtime session ID |
   | remote_sdp | 收到并应用远端 SDP |
   | microphone_acquired | 浏览器获得音频轨道 |
   | remote_track | 浏览器收到远端音轨 |
   | audio_playing | audio 元素触发播放，且有实际 RTP/听感证据 |
   | user_transcript / assistant_transcript | 用户和助手转写，含 item 或 response ID |
   | turn_started | 任务 turn 开始，含 thread/turn ID |
   | tool_execution | 工具开始和完成，含 call/item ID |
   | turn_completed | 任务达到真实终态 |
   | realtime_closed | 收到 realtime 关闭事件并释放本地媒体 |
   | stop_voice_requested / stop_voice_accepted | 分别确认结束语音请求已发出且 RPC 被接受 |
   | interrupt_requested / interrupt_accepted | 分别确认停止任务请求已发出且 RPC 被接受 |
   | history_read | 语音任务结束后按 thread/read 读取到包含 turns 的历史 |

7. 在一个慢任务期间先调用 stop_voice，确认只发生 thread/realtime/stop，任务不被自动取消。再单独调用 interrupt，确认只发生 turn/interrupt，等待 turn_completed 的真实状态。
8. 检查同一语音段只有一条任务提交路径。字幕事件不能再次产生 turn/start 或普通文本提交。
9. 调用 thread/read，按 thread ID、turn ID、item ID 对照工具和助手历史。记录分页弃用提示；在历史读取协议未完成迁移前，不把它当作长期兼容方案。

### 6.3 M0 通过标准

M0 必须同时满足三层证据：代码/单测通过；schema/协议字段与真实请求一致；目标浏览器完成一次真实媒体和真实语音工具任务。必须有上述机器事件、音频播放证据、历史关联和停止语义证据。

当前状态为 **已通过**。2026-10-06 的隔离探测器运行完成了真实媒体、连续语音字幕、语音工具任务、历史读取、结束语音和任务中断验证。生产接入以及停止播报的专项行为仍不属于已交付范围。

## 7. M1：产品连接、控制和 runtime 分发

M1 只做当前聊天中的语音连接、控制条和 runtime 事件分发。M1 不做 TCB 任务持久化、统一历史或语音/文字混合输入。

- [x] M0 通过。
- [x] P0 设计闸门已评审，进入 M1 产品浏览器验收。
- [ ] 按已确认协议接入 TCB 端点，保持版本兼容检查和功能开关。
- [ ] runtime 在没有普通 turn 时仍由唯一 reader 分发语音连接、字幕、连接状态和控制事件。
- [ ] 前端实现麦克风、播放、字幕、静音、停止播报、结束语音和设备释放。
- [ ] 处理权限拒绝、无麦克风、SDP/ICE 失败、上游错误、主动结束和未知状态。失败后文字聊天继续可用。
- [ ] 实现同一会话单连接、跨会话隔离和标签页占用提示。

通过标准：功能开关开启时，当前聊天可以建立和关闭语音连接；没有普通 turn 时事件仍可达；结束语音释放设备且不取消独立任务；功能开关关闭时普通文字聊天行为不变。

## 8. M2：TCB 任务持久化、统一历史和混合输入

- [ ] 语音触发的 turn 进入现有消息创建、流式持久化、trace、完成和失败链路。
- [ ] 持久化语音转写、协议 turn/item、TCB 消息和提交幂等键的映射。
- [ ] 语音和文字沿用同一 conversation 上下文。补充要求只走已确认的单一路由。
- [ ] 处理补充与完成、取消与完成的竞争，给出真实接收或拒绝状态。
- [ ] 刷新或重进聊天后恢复定稿转写、任务结果和执行状态。
- [ ] 模型生成播报不等于用户已听完；详细结果继续留在文字聊天。

通过标准：语音启动一个任务，中途语音补充，随后文字追问；每个任务只执行一次，内容归属正确，刷新后记录完整。

## 9. M3：插话、停止和断线

- [ ] 插话让出播放，清理或隔离旧音频，避免旧播报在新一轮后继续播放。
- [ ] 停止播报只影响本地/当前播放；停止任务等待真实终态。
- [ ] 结束语音只关闭对应连接，执行中的任务继续通过文字聊天展示。
- [ ] 断线后先展示未知或真实状态；重连恢复状态，不重发已接收指令。
- [ ] 验证跨会话、跨标签页、连接释放和租约过期。

通过标准：执行期间依次验证插话、补充、停止播报、结束语音、停止任务和断线重连；没有重复执行、串会话或错误完成提示。

## 10. M4：浏览器矩阵、公网入口和开放

- [ ] 验收完整流程：开始语音、发起任务、插话补充、追问进度、听取结果、结束语音、文字继续。
- [ ] 在实际支持的桌面和手机浏览器检查麦克风授权、自动播放、音频设备切换、字幕布局、后台切换和页面离开。
- [ ] 验证 HTTPS 或 localhost、/node/<node ID>/ 前缀、反向代理 WebSocket、SDP/ICE 交换和公网 NAT 场景。
- [ ] 明确 STUN/TURN、浏览器版本、网络限制、单连接限制、配额错误和不支持场景。
- [ ] 只有通过浏览器矩阵、核心契约和失败恢复检查的能力进入开放范围。功能开关关闭时普通文字聊天继续可用。

通过标准：支持范围、连接限制、错误反馈和公网部署条件可复现、可观察、可说明。

## 11. 最小充分验证和当前命令

自动化测试只覆盖稳定契约和真实风险。mock 或 schema 检查不能替代真实浏览器语音。

当前记录的 backend 验证命令：

~~~text
python -m pytest tests/test_codex_server_client.py tests/test_codex_voice_probe.py tests/test_codex_server_runtime.py tests/test_codex_server_events.py tests/test_codex_server_config.py -q
~~~

当前记录的文字基线命令：

~~~text
python -m scripts.codex_voice_probe --check-text
~~~

真实 voice 仍需用户手工启动探测器：

~~~text
python -m scripts.codex_voice_probe --host 127.0.0.1 --port 0
~~~

完整链路变更后，再运行前端 npm run test:gate、npm run build、npm run lint，并做浏览器级媒体检查。本文档更新本身不启动服务、不启动探测器、不产生新的语音结果。

## 12. 原生链路不可用时的备选

若 M0 因账号权限、协议行为或部署限制不能满足目标，停止原生路线后续实现，先记录受阻范围，再选择一个备选：

| 备选 | 适用目标 | 主要代价 |
| --- | --- | --- |
| 语音识别 → 当前 Codex server → 语音合成 | 先交付语音输入和结果播报 | 连续对话、插话、断句和播放队列由应用处理 |
| 独立实时语音接口连接当前 Codex server | 持续对话是硬性要求 | 额外管理语音上下文、任务交接、凭据和费用 |

涉及额外语音服务时必须明确配置和计费，不静默切换。唤醒词、长期后台监听、多方通话、原始录音回放和跨供应商统一接口不属于首版。

## 13. 参考

- Codex App Server：https://learn.chatgpt.com/docs/app-server
- Voice agents：https://developers.openai.com/api/docs/guides/voice-agents
- Getting started with GPT-Live：https://developers.openai.com/api/docs/guides/live

原生 thread/realtime/* 接口存在性的依据是本机 Codex 0.160.0 生成的实验 schema。公共文档不构成当前账号语音权限或原生链路可用性的证明。
