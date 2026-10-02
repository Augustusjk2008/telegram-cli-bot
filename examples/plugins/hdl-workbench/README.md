# HDL Workbench

独立的 Verilog/SystemVerilog 项目分析后端，适用于 `.v`、`.sv`、`.vh`、`.svh`。
输出模块、端口、参数、静态实例引用、源码位置和诊断。单文件解析器接收已有 UTF-8 源码；项目扫描通过 Host API 读取目录和文件。
当前提供 Python API 和 JSON-RPC stdio，尚未提供插件目录入口或浏览器视图。

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

本目录可整体复制到任意目录，`backend` 中的 SDK、模型和解析器均不依赖 `bot`、前端或仓库根目录。
当前没有 `plugin.json`，因此尚不能从插件目录安装为可操作视图。

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

语法包会将部分模块实例解析为 checker、UDP、program 或 interface 引用。
后端保留目标名称，并用 `reference_kind` 标记这种歧义；项目索引根据模块名称解析候选，不推断其他设计单元的语义。
对于语法包误识别的继承参数名和位置式空端口，仅恢复能从原始语法节点确认的合法结构，其余错误仍显示为诊断。

## 限制

不进行预处理、include 文本内联、宏展开、常量求值或 generate 展开。
位宽表达式没有被换算成有效位数，静态实例不等于工具完成展开后的设计层级。
不解析 VHDL，也不将 interface、program、checker、UDP 或 package 作为模块定义展示。
非 ANSI 端口别名、复合端口表达式会标记为解析不完整；不支持的宏生成语法可能显示语法区域诊断。

## 验证

从仓库根目录使用独立 Python 环境运行：

```powershell
python -m venv .tmp/hdl-parser-venv
& .tmp/hdl-parser-venv/Scripts/python.exe -m pip install --only-binary=:all: -r examples/plugins/hdl-workbench/requirements.txt
& .tmp/hdl-parser-venv/Scripts/python.exe -m pip install pytest==8.3.4 pytest-asyncio==1.3.0
& .tmp/hdl-parser-venv/Scripts/python.exe -m pytest --noconftest tests/test_hdl_parser.py tests/test_hdl_project.py -q
```

`--noconftest` 用于隔离 Host 的自动 session fixture；解析和项目单元测试不需要 Host 依赖。
未安装解析依赖的普通 Host 测试环境会跳过实际解析用例，依赖错误和初始化诊断用例仍会运行。
