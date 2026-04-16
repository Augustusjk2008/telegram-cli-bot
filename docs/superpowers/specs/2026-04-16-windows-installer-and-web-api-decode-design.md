# Windows Installer And Web API Decode Design

## Goal

处理两个独立但同轮提出的问题：

- 修复 `tests/test_web_api.py` 在 Windows 下偶发的后台子进程读取 `UnicodeDecodeError` warning
- 扩展 Windows 安装器，使其可选配置或自动安装 `cloudflared`
- 当本机同时没有 `codex` 和 `claude` 时，可选自动安装 Codex CLI

本次目标是让测试输出干净、Windows 首次安装流程更完整，同时不扩大到无关模块重构。

## Scope

本次改动限定在以下区域：

- `tests/test_web_api.py`
- `install.ps1`
- `tests/test_install_scripts.py`
- 如有必要，补充 `.env` 写入相关测试或脚本辅助函数测试

不改 Linux 安装脚本，不改 Web 设置页 tunnel UI，不重做子进程封装层，不引入新的安装器框架。

## Problem 1: UnicodeDecodeError Warning

### Observed Behavior

`tests/test_web_api.py` 在 Windows 下会出现 `PytestUnhandledThreadExceptionWarning`，堆栈落在 Python 标准库 `subprocess._readerthread`，根因是后台读流线程按 UTF-8 解码时遇到了非 UTF-8 字节。

### Root Cause

仓库业务代码里的多个子进程读取路径已经显式使用 `errors="replace"`，但 `tests/test_web_api.py` 里自建 Git 仓库的辅助调用仍在使用：

- `subprocess.run(..., capture_output=True, text=True)`

这些调用没有显式指定更稳妥的错误处理。在 Windows 上，Git 或其依赖命令输出本地编码字节时，标准库后台线程可能在解码阶段抛出 `UnicodeDecodeError`，即使测试主体逻辑本身仍然通过。

### Chosen Fix

采用精准修复方案，只修改测试里的 Git 子进程读取配置：

- 为 `tests/test_web_api.py` 中相关 `subprocess.run` 补上安全解码参数
- 优先使用与现有仓库测试一致的模式：`encoding="utf-8", errors="replace"`

### Why This Fix

- warning 的触发点已定位到测试自起进程，不需要扩大到生产代码总线级重构
- 与仓库现有脚本测试和业务代码的处理方式保持一致
- 能消除噪声 warning，同时不改变业务行为

### Non-Goals For This Problem

- 不抽象新的全局 subprocess helper
- 不通过 pytest 过滤器掩盖 warning
- 不对 `bot/web/api_service.py` 做无证据的编码策略改写

## Problem 2: Windows 安装器增加 cloudflared 可选安装

### Required Behavior

Windows 安装器需要支持以下交互：

1. 先问是否启用 `cloudflared`
2. 如果启用，再问是否输入已有公网地址
3. 如果用户没有提供地址，再问是否自动安装 `cloudflared`
4. 如果同意安装，则自动下载指定版本到仓库内工具目录
5. `.env` 中写入对应的 tunnel 配置

### Download Source

- `https://github.com/cloudflare/cloudflared/releases/download/2026.3.0/cloudflared-windows-amd64.exe`

### Installation Layout

自动下载的 `cloudflared` 放入仓库内固定目录，例如：

- `tools/cloudflared/cloudflared.exe`

安装器会确保目录存在，并将下载文件统一命名为 `cloudflared.exe`。

### Env Strategy

根据用户选择写入 `.env`：

- 若填写 `WEB_PUBLIC_URL`：
  - `WEB_PUBLIC_URL=<用户输入>`
  - `WEB_TUNNEL_MODE=disabled`
  - `WEB_TUNNEL_CLOUDFLARED_PATH=` 保持空
- 若未填写地址但启用了 quick tunnel：
  - `WEB_PUBLIC_URL=`
  - `WEB_TUNNEL_MODE=cloudflare_quick`
  - 若使用仓库内下载版，则写入 `WEB_TUNNEL_CLOUDFLARED_PATH=<绝对路径>`
  - 若系统 PATH 中已有 `cloudflared`，则可保持为空

### Non-Interactive Default

`-NonInteractive` 模式下保持保守默认值：

- 不启用 `cloudflared`
- 不写入公网地址
- 不触发自动下载安装

这样不会在自动化检查里引入网络下载副作用。

## Problem 3: Windows 安装器增加 Codex 可选安装

### Trigger Condition

只有在同时未检测到 `codex` 和 `claude` 时，安装器才会额外询问是否自动安装 Codex。

### Download Source

- `https://github.com/openai/codex/releases/download/rust-v0.121.0/codex-x86_64-pc-windows-msvc.exe`

### Installation Layout

自动下载的 Codex 放入仓库内固定目录，例如：

- `tools/codex/codex.exe`

下载后统一重命名为 `codex.exe`。

### PATH Strategy

安装器会将 `tools/codex` 追加到当前用户 PATH，并刷新当前 PowerShell 进程内的 PATH，确保同一轮安装流程里就能检测到 `codex`。

为避免“PATH 已写入但当前 shell 尚未继承”带来的不确定性，`.env` 中的 `CLI_PATH` 优先写成该本地 `codex.exe` 的绝对路径。

### User Flow

当本机没有 `codex` / `claude` 时：

1. 输出当前缺失提示
2. 询问是否自动安装 Codex
3. 若用户同意，则下载、落盘、更新用户 PATH、刷新当前进程 PATH
4. 重新检测本地 CLI
5. 后续 `.env` 默认选择 Codex

若下载或 PATH 写入失败，安装器应给出明确错误，且不伪装为“已安装成功”。

## Installer Structure Changes

`install.ps1` 将增加一组小范围辅助函数，保持现有结构不被打散：

- 仓库内工具目录解析
- 可执行文件下载与统一命名
- 用户 PATH 追加
- cloudflared 交互配置收集
- Codex 自动安装流程

现有的 `.env` 生成入口仍保持在 `Configure-EnvFile`，但会接收更多上下文，用于写入 tunnel 与 CLI 路径结果。

## Error Handling

### Decode Warning Fix

- 测试辅助 Git 命令统一使用安全解码
- 不因单个非 UTF-8 字节而让后台线程异常冒泡成 warning

### Installer Downloads

- 下载失败时直接报错并结束安装
- 失败信息中包含当前工具名称和失败步骤
- 不把“用户拒绝安装”与“下载失败”混为一谈

### PATH Update

- 若用户 PATH 更新失败，应明确报错
- 当前进程 PATH 刷新失败也应视为安装未完成

## Testing

### tests/test_web_api.py

- 为测试辅助 Git 子进程读取增加安全解码参数
- 保持现有 Git 场景测试继续通过
- 目标是消除 Windows 下的 `UnicodeDecodeError` warning

### tests/test_install_scripts.py

新增或扩展以下覆盖：

- 当 `cloudflared` 未启用时，非交互模式不会写入 quick tunnel 配置
- 当用户选择启用 quick tunnel 且自动安装时，脚本会使用指定 cloudflared 下载地址、目标文件名和 `.env` 写入
- 当同时缺失 `codex` 与 `claude` 时，脚本会询问 Codex 自动安装，并使用指定 x64 下载地址
- Codex 安装后 `.env` 默认指向本地下载的 `codex.exe`

测试实现会优先通过 mock 脚本函数或无副作用方式验证交互分支，不在测试中真正联网下载。

## Risks And Tradeoffs

- 安装器交互分支变多，测试必须覆盖默认路径与下载路径，避免后续回归
- 将 `CLI_PATH` 写成绝对路径更稳，但会让 `.env` 与仓库位置绑定；这比依赖 PATH 生效时机更可控，属于有意取舍
- `cloudflared` 自动下载只覆盖 Windows 当前指定版本，不扩展为版本检测器

## Non-Goals

- 不为 Linux 增加 cloudflared / Codex 自动安装
- 不把 cloudflared 安装改成系统级服务注册
- 不修改 Web 端 tunnel 管理逻辑
- 不把子进程编码策略重构成全仓统一组件
