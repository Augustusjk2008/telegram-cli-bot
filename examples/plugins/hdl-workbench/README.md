# HDL Workbench

独立的 Verilog/SystemVerilog 项目浏览插件，适用于 `.v`、`.sv`、`.vh`、`.svh`。
提供按需展开的模块/实例树、端口/参数和时钟/复位候选详情表、手动刷新及真实源码导航；项目扫描通过 Host API 读取目录和文件。
也保留单文件解析和项目索引的 Python API、JSON-RPC stdio 接口。

## 依赖与安装

运行依赖仅在本目录的 `requirements.txt` 中固定，不加入 Orbit Host 的全局依赖：

| 包 | 固定版本 | Windows 验证 |
|---|---|---|
| `tree-sitter` | `0.26.0` | CPython 3.13 x64 的 `cp313-cp313-win_amd64` wheel |
| `tree-sitter-verilog` | `1.0.3` | `cp39-abi3-win_amd64` wheel，在 CPython 3.13.5 x64 实测可加载 |

已在独立的 Windows 11 / Python 3.13.5 环境中完成二进制 wheel 安装、ABI 14 语法加载和解析验证，不需要本地编译器。
依赖来源：[Python bindings](https://github.com/tree-sitter/py-tree-sitter)、[Verilog grammar](https://pypi.org/project/tree-sitter-verilog/)。其他 Python 版本和操作系统尚未实测。

在本目录运行：

```powershell
python -m pip install --only-binary=:all: -r requirements.txt
```

部署时需要使用 Host 启动插件的同一个 Python。初始化会检查固定版本、导入语法并建立解析器；
依赖缺失、版本不一致或二进制不兼容时，通过 JSON-RPC 返回错误及包含实际 Python 路径和依赖文件路径的安装命令。
不会自动安装软件。

本目录可整体复制到任意目录，`backend` 中的 SDK、模型、解析器和视图均不依赖 `bot`、前端或仓库根目录。
在 Orbit 的插件目录安装 `HDL Workbench`，或使用本目录的路径安装。schema v2 manifest 仅申请 `workspaceRead`、`workspaceList`。

## 使用

1. 在插件目录点击“选择 HDL 项目”，选择当前工作区内的项目目录。
2. 在“候选顶层”（配置了顶层时为“指定顶层”）或“全部模块”下展开模块和静态实例。
3. 点击模块/已解析实例查看端口、参数、实例参数覆盖及信号候选；详情表支持搜索和分页。“推断依据”列展示事件控制或复位分支证据。
4. 使用“打开定义”“打开实例化位置”或详情行的声明动作，在源码编辑器中打开对应文件和行列。
5. 源码修改后在层级视图点击“刷新项目”，重新展开并打开详情，取得新的索引和位置。

同名定义保留为候选项，循环分支停止展开，缺失引用和诊断保留在树中。
层级搜索返回匹配的模块和实例；条件分支、generate 和实例数组保留静态上下文，不代表展开后的设计。
详情中的位宽、默认值和覆盖值保留源码表达式，不计算有效数值；位置式参数覆盖按可覆盖参数的声明顺序对应。
“静态条件”列保留声明和实例的宏/generate 上下文，实例数组在树中明确标记。

每次打开后端视图生成独立 session ID。由树打开的详情会话共享该树的索引，关闭树后详情仍可使用；
最后一个引用关闭或插件退出时释放索引和节点/行注册表。不同会话不能使用彼此的节点或行 ID。
从树打开新的详情视图时必须使用仍存在的父会话；不把失效会话自动替换为重新扫描的项目。

源码位置由当前索引决定，客户端传入的文件路径和行号不会替代索引位置。
树和表中的位置使用项目相对路径，项目外的共享文件保留绝对路径；导航始终使用索引中的绝对位置。
跳转前通过 Host 核对文件路径、大小、修改时间和内容 SHA-256；文件已变化、无法读取或读取过程中变化时拒绝跳转并提示刷新。
“刷新项目”清理当前树的 Host 缓存和会话，然后重新扫描，包括嵌套目录中的源码修改；树的已展开节点和搜索状态重置。
已有详情标签继续保留原索引，新详情使用新父会话单独打开；旧详情的源码跳转仍会拒绝已变化的文件。
项目摘要集中显示诊断、未解析/歧义引用和分析不完整标记。每个树窗口最多返回 2000 个直接节点，超出时显示截断提示；
搜索仍覆盖整个已扫描索引，默认返回最多 200 个匹配（请求上限 500），便于定位未显示的实例或模块。

## Python API

从本目录执行下列 Python 代码，查看样例结果：

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("backend").resolve()))
from hdl_parser import HdlParser

source = Path("samples/ports.sv")
result = HdlParser().parse(str(source), source.read_bytes())
print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
```

项目路径由调用方提供，解析器保持原样；它不会从路径猜测位置或补读文件。
字节偏移对应原始 UTF-8 内容，起止行号从 1 开始，列号从 1 开始并使用编辑器的 UTF-16 单元，结束位置不包含末尾字符。
保留 CRLF 和中文注释，不替换无法解码的字节；非 UTF-8 内容需要调用方先转换编码。

`samples/ports.sv` 包含两个模块；`top` 在第 2 行，端口 `a`、`b` 分别在第 6、7 行，
`u_named`、`u_second`、`u_positional` 分别在第 14、15、16 行。
`samples/classic.v` 演示非 ANSI 端口：`result` 的方向声明在第 5 行，独立的 `reg [8:0]` 类型在第 6 行。
`samples/signals.sv` 演示异步复位（第 8–9 行）和同步复位（第 22–23 行）的独立候选证据。

## JSON-RPC stdio

运行 `python backend/main.py`，向标准输入逐行发送 JSON，标准输出只返回协议消息：

```json
{"jsonrpc":"2.0","id":1,"method":"plugin.initialize","params":{"context":{}}}
{"jsonrpc":"2.0","id":2,"method":"plugin.parse_source","params":{"path":"rtl/top.sv","content":"module top(input clk); endmodule"}}
{"jsonrpc":"2.0","id":3,"method":"plugin.shutdown"}
```

`plugin.parse_source` 只接受路径和已读取的源码，不接受读取路径的请求。
结果中的 `incomplete` 表示语法错误、无法提取的端口声明或缺少端口方向；模块也分别带有该标记。
`diagnostics` 包含实际源码范围、级别、代码和提示；损坏区域之外仍能识别的模块保留结果。

`plugin.analyze_project` 接受 `{"path":"项目目录"}`，读取初始化时 Host 提供的 `workspaceRoot`、限额和插件配置。
它会发出 `host.workspace.stat`、`host.workspace.list_dir`、`host.workspace.read_range` 请求，需要 Host 在同一 stdio 通道返回响应。
没有 Host 响应器时，不能用一组静态 JSON 输入完成项目扫描；初始化上下文也不能省略工作区路径。
该方法返回项目摘要、文件指纹、模块和引用索引、include 结果、顶层候选和诊断，不展开整棵实例树。

浏览器使用 `plugin.open_view` 打开 `module-tree` 或 `module-details`，返回 session 摘要和初始窗口。
`plugin.get_view_window` 的树请求为 `{"sessionId":"...","op":"children","nodeId":"..."}` 或 `op="search"` 加 `query`；
表请求使用 `offset`、`limit`、`query`，默认每页 50 行，最大 500 行。
树窗口只返回直接子节点，不递归展开；表窗口只返回所请求的行。
`plugin.invoke_action` 根据会话中的 `nodeId`/`rowId` 返回 `open_plugin_view` 或核验后的 `open_file` Host effect；
树的 `refresh-project` 动作返回 `refresh="view"`，由 Host 清理缓存和原会话，再由前端重新打开视图。
`plugin.dispose_view` 关闭指定会话，`plugin.shutdown` 清理所有会话。

## 项目索引与层级

Python 调用方使用 `ProjectScanner(parser, host_call, workspace_root, options).scan(project_path)`。
`host_call(method, params)` 接收与 SDK 相同的参数并返回 JSON-RPC 的 `result` 或 `error` 包装；源码只能通过 Host 读取。
`ProjectIndex.definitions` 保留模块完整数据，`modules_by_name` 保留同名定义的全部 ID，`children(definition_id, ancestors=())` 只返回直接实例。
展开时传入祖先模块 ID；循环分支标记为 `cycle` 并终止，缺失引用保留为不可展开的 `missing` 节点。
同名定义不会被任意合并，实例标记为 `ambiguous`，返回所有候选 ID。

`candidate_top_ids` 是没有被静态实例引用的模块；`selected_top_ids` 来自指定顶层；所有定义始终保留为独立入口。
条件分支和 generate 不求值，因此同名条件定义仍是候选，循环诊断也注明静态推断。
没有候选顶层的循环项目仍可从全部模块入口浏览。

| 配置键 | 默认值 | 行为 |
|---|---|---|
| `topModule` | 空 | 模块名或逗号分隔的模块名；未找到时给出诊断，不自动替换选择 |
| `ignoreDirectories` | 内置忽略目录 | 逗号分隔字符串或字符串列表，设置后替换默认列表；仅影响目录遍历 |
| `includeDirectories` | 空 | 相对于项目目录的搜索目录，也可指定工作区内的绝对路径 |
| `maxFiles` | 1000 | 去重后的 HDL 文件尝试数；包括读取失败或超限文件 |
| `maxFileBytes` | 4194304 | 单文件 4 MiB；实际限制取该值与 Host `readBytes` 的较小值 |
| `maxTotalBytes` | 67108864 | 总源码读取 64 MiB，包括随后被丢弃的已读取内容 |

默认忽略 `.git`、`.hg`、`.svn`、`.tcb`、`.codegraph`、`.tmp`、`.venv`、`venv`、
`__pycache__`、`node_modules`、`vendor`、`site-packages`、`build`、`dist`、`out`、`target`。
字面量 include 按包含文件所在目录、配置的 include 目录顺序查找；明确引用的文件不受遍历忽略目录或扩展名过滤影响。
可读取项目目录外、工作区内的共享头文件，不允许逃出工作区。宏路径保留为未解析项，不根据宏内容猜测文件名。

每个文件最多按 1 MiB 的范围分块读取，核对路径、大小、修改时间、偏移、长度和 EOF，再用最终 stat 验证。
文件变化或短读时丢弃整个文件的解析结果并提示刷新，已完成的其他文件保留。
目录截断、文件或字节限额、读取失败、未解析 include、重复或缺失定义、静态循环都会使项目 `incomplete` 为 true。
达到文件或字节预算但没有遗漏内容时仍可完整；只在实际截断或跳过内容时标记限额诊断。

使用 Host 返回的路径去重目录、文件和 include；同一文件经目录遍历、多个 include 或路径别名访问时只解析一次。
include 循环不会反复读取，也不会将头文件文本内联到包含模块；头文件自身能识别的模块进入跨文件索引。
需要宏或 include 文本展开才能成立的声明仍可能显示语法诊断。

`samples/project` 演示跨文件引用、字面量 include、条件实例和多个候选顶层：`system` 和 `utility` 是顶层候选，
`system` 的 `u_core`、`u_optional` 均引用 `core`；后者保留 `EXTRA_CORE` 的条件上下文。

## 支持的静态结构

- ANSI 端口及继承方向、类型和位宽的多名称声明；非 ANSI 端口及独立的 net/variable 类型声明。
- `input`、`output`、`inout` 等方向、类型文本、packed 位宽表达式、unpacked 维度及声明默认值。
- 模块头和模块体中的 `parameter`、`localparam`，值参数和类型参数；保留默认表达式。
- 命名和位置式端口连接、隐式 `.port`、显式空连接、`.*`、多个实例及实例数组。
- 命名和位置式参数覆盖，保留表达式及位置，不计算数值。
- 宏条件和 generate 中可识别的声明及实例保留 `contexts`，并给出未展开提示。
- 使用真实语法节点定位声明及实例，不把注释里的伪模块或函数、task 的局部声明当作模块接口。
- `always`、`always_ff` 的前导边沿事件控制提取时钟候选；匹配复位分支的事件单独标记为异步复位候选。
- 首优先 `if` 分支的简单信号/位选择、`!`/`~` 或与 0/1 的相等/不等比较，在字面量初始化和 `else` 更新相同目标时提取复位候选。
  同步复位也保留分支证据；同一信号的事件和分支是不同源码出现位置，不合并。
- 候选保留原始表达式、真实行列和宏/generate 上下文。多边沿无法分类时在依据中明确注明不确定。

语法包会将部分模块实例解析为 checker、UDP、program 或 interface 引用。
后端保留目标名称，并用 `reference_kind` 标记这种歧义；项目索引根据模块名称解析候选，不推断其他设计单元的语义。
对于语法包误识别的继承参数名和位置式空端口，仅恢复能从原始语法节点确认的合法结构，其余错误仍显示为诊断。

## 限制

不进行预处理、include 文本内联、宏展开、常量求值或 generate 展开。
位宽表达式没有被换算成有效位数，静态实例不等于工具完成展开后的设计层级。
不解析 VHDL，也不将 interface、program、checker、UDP 或 package 作为模块定义展示。
信号候选是结构推断，不能确认设计意图或替代时序约束。普通使能/数据选择、`always_comb`、`@*`、纯电平事件、
`initial`、函数/task 和嵌套事件不作为时钟/复位推断入口；仅检查进程的前导事件控制。
复位推断不支持复合/层级/宏生成条件、符号或算术/拼接初始化、未知值初始化、低优先级或仅 `else` 的复位分支，
也不支持外层多个执行语句、case/循环/带延迟复位分支。部分 `iff` 形式仍有语法包诊断，事件门控不会被当作复位。
非 ANSI 端口别名、复合端口表达式会标记为解析不完整；不支持的宏生成语法可能显示语法区域诊断。

## 验证

从仓库根目录使用独立 Python 环境运行：

```powershell
python -m venv .tmp/hdl-parser-venv
& .tmp/hdl-parser-venv/Scripts/python.exe -m pip install --only-binary=:all: -r examples/plugins/hdl-workbench/requirements.txt
& .tmp/hdl-parser-venv/Scripts/python.exe -m pip install pytest==8.3.4 pytest-asyncio==1.3.0
& .tmp/hdl-parser-venv/Scripts/python.exe -m pytest --noconftest tests/test_hdl_parser.py tests/test_hdl_project.py tests/test_hdl_views.py -q
```

`--noconftest` 用于隔离 Host 的自动 session fixture；解析和项目单元测试不需要 Host 依赖。
未安装解析依赖的普通 Host 测试环境会跳过实际解析用例，依赖错误和初始化诊断用例仍会运行。

复制目录、真实 Host API 和 runtime 的集成检查可在装有 Host 依赖的环境运行；
如解析依赖位于独立测试环境，显式指定子进程解释器（只影响测试）：

```powershell
$env:HDL_PLUGIN_TEST_PYTHON = (Resolve-Path .tmp/hdl-parser-venv/Scripts/python.exe).Path
python -m pytest tests/test_hdl_plugin_runtime.py tests/test_plugin_runtime.py tests/test_plugin_service_cache.py tests/test_plugins_host_api.py tests/test_bundled_plugins.py -q
```

前端检查使用现有组件和 mock：`npm run test:gate -- src/test/plugin-hdl-view.test.tsx src/test/plugin-table-view.test.tsx src/test/editor-tabs-scope.test.tsx`、`npm run lint`、`npm run build`。
浏览器验收连接人工已启动的应用：设置 `PLAYWRIGHT_BASE_URL` 后运行 `npx playwright test src/test/plugin-hdl-workbench.spec.ts`。
浏览器测试拦截 API，不修改运行中的用户配置或项目；检查窄窗口、刷新后的独立详情和实际编辑器中的源码位置。
