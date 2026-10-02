# HDL Workbench

独立的 Verilog/SystemVerilog 单文件解析后端，适用于 `.v`、`.sv`、`.vh`、`.svh`。
接收调用方或 Host 提供的 UTF-8 源码，输出模块、端口、参数、静态实例引用、源码位置和诊断；解析器不读取项目文件。
当前提供 Python API 和 JSON-RPC stdio，尚未提供目录扫描、插件目录入口或浏览器视图。

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

## 支持的静态结构

- ANSI 端口及继承方向、类型和位宽的多名称声明；非 ANSI 端口及独立的 net/variable 类型声明。
- `input`、`output`、`inout` 等方向、类型文本、packed 位宽表达式、unpacked 维度及声明默认值。
- 模块头和模块体中的 `parameter`、`localparam`，值参数和类型参数；保留默认表达式。
- 命名和位置式端口连接、隐式 `.port`、显式空连接、`.*`、多个实例及实例数组。
- 命名和位置式参数覆盖，保留表达式及位置，不计算数值。
- 宏条件和 generate 中可识别的声明及实例保留 `contexts`，并给出未展开提示。
- 使用真实语法节点定位声明及实例，不把注释里的伪模块或函数、task 的局部声明当作模块接口。

语法包会将部分模块实例解析为 checker、UDP、program 或 interface 引用。
后端保留目标名称，并用 `reference_kind` 标记这种歧义；单文件阶段不推断目标定义的种类。
对于语法包误识别的继承参数名和位置式空端口，仅恢复能从原始语法节点确认的合法结构，其余错误仍显示为诊断。

## 限制

不进行预处理、include 文件读取、宏展开、常量求值、generate 展开或跨文件引用解析。
位宽表达式没有被换算成有效位数，静态实例不等于工具完成展开后的设计层级。
不解析 VHDL，也不将 interface、program、checker、UDP 或 package 作为模块定义展示。
非 ANSI 端口别名、复合端口表达式会标记为解析不完整；不支持的宏生成语法可能显示语法区域诊断。

## 验证

从仓库根目录使用独立 Python 环境运行：

```powershell
python -m venv .tmp/hdl-parser-venv
& .tmp/hdl-parser-venv/Scripts/python.exe -m pip install --only-binary=:all: -r examples/plugins/hdl-workbench/requirements.txt
& .tmp/hdl-parser-venv/Scripts/python.exe -m pip install pytest==8.3.4 pytest-asyncio==1.3.0
& .tmp/hdl-parser-venv/Scripts/python.exe -m pytest --noconftest tests/test_hdl_parser.py -q
```

`--noconftest` 用于隔离 Host 的自动 session fixture；解析测试不需要 Host 依赖。
未安装解析依赖的普通 Host 测试环境会跳过实际解析用例，依赖错误和初始化诊断用例仍会运行。
