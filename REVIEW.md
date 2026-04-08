# 代码审查记录

更新日期：2026-04-08

本文件记录 2026-04-08 这轮代码审查里发现并已完成修复、验证的问题，避免后续重复排查同一批历史缺陷。

## 本轮已修复并验证

### 1. `collect_cli_output()` 正常退出时偶发返回 `-1`

- 修复位置：`bot/handlers/chat.py`
- 处理方式：为 CLI 进程退出增加显式等待逻辑，在读取线程结束但 `poll()` 尚未回填时，再补一次短暂 `wait()`
- 验证：
  - `tests/test_handlers/test_chat.py`
  - 新增了等待回填 returncode 的定向测试

### 2. Web API `/cd` 没有复用 Telegram `/cd` 的会话清理语义

- 修复位置：`bot/web/api_service.py`
- 处理方式：
  - 切换工作目录后执行 `session.clear_session_ids()`
  - 子 Bot 同步持久化 `working_dir`
  - 同步更新当前 alias 下已存在 session 的目录
- 验证：
  - `tests/test_web_api.py::test_change_working_directory_clears_session_ids`

### 3. Web API CLI 聊天路径没有持久化 session，也没有 Kimi 失效恢复

- 修复位置：`bot/web/api_service.py`
- 处理方式：
  - 增加 `should_reset_kimi_session()` 分支
  - 在 session id 变更时调用 `session.persist()`
  - 保持 Claude / Codex / Kimi 三条分支的行为和 Telegram 路径一致
- 验证：
  - `tests/test_web_api.py::test_run_cli_chat_resets_and_persists_kimi_session`

### 4. 主 bot 网络错误兜底路径会因为缺参数抛 `TypeError`

- 修复位置：`bot/manager.py`
- 处理方式：
  - 从主 bot application 读取真实 `bot_id`
  - 只有拿到有效 `bot_id` 才调用 `is_bot_processing(bot_id)`
  - 取不到 `bot_id` 时记录警告并跳过重启判断
- 验证：
  - `tests/test_manager.py::TestManagerValidation::test_handle_network_error_exhausted_checks_main_bot_id`

### 5. `/kill` 存在处理函数但没有注册命令

- 修复位置：`bot/handlers/__init__.py`
- 处理方式：补充 `CommandHandler("kill", kill_process)`
- 同步修正：
  - `bot/messages.py`
  - `bot/messages.json`
- 验证：
  - `tests/test_assistant.py::TestRegisterHandlers::test_register_cli_handlers`
  - `tests/test_handlers/test_basic.py`

### 6. `webcli` 仍可被创建，但运行时会静默退回 CLI

- 修复位置：`bot/manager.py`
- 处理方式：
  - 新增 bot 时直接拒绝 `webcli`
  - 读取历史配置时将旧 `webcli` profile 明确回退为 `cli` 并记录 warning
- 验证：
  - `tests/test_assistant.py::TestMultiBotManagerWithAssistant::test_load_legacy_webcli_profile_falls_back_to_cli`
  - `tests/test_assistant.py::TestMultiBotManagerWithAssistant::test_add_webcli_bot_is_rejected`

### 7. `network_traffic.ps1` 和对应测试存在编码兼容问题

- 修复位置：
  - `scripts/network_traffic.ps1`
  - `tests/test_network_traffic.py`
  - `pytest.ini`
- 处理方式：
  - 脚本输出改为 ASCII 友好的稳定字段
  - 测试改成按 bytes 读取，再按本机编码/UTF-8/GB18030 回退解码
  - 注册 `smoke` marker，并固定 `pytest-asyncio` loop scope
- 验证：
  - `tests/test_network_traffic.py`

### 8. 主 Bot 切换回调在主会话创建时使用了错误的函数签名

- 修复位置：`bot/handlers/admin.py`
- 处理方式：`bot_goto_callback()` 改为使用 `get_or_create_session(bot_id, alias, user_id, default_working_dir=...)`
- 验证：
  - `tests/test_handlers/test_admin.py::TestBotGotoCallback::test_uses_main_bot_session_signature_correctly`

## 测试结果

本轮实际执行命令：

```bash
python -m pytest tests -q
```

结果：

- `245` 通过
- `0` 失败

附带观察：

- `pytest` 退出时，当前 Windows 环境偶发出现 `pytest-current` 临时目录清理的 `PermissionError`；它发生在 atexit 阶段，不影响本轮测试结果
- 仓库内提交的 `venv/Scripts/python.exe` 依然不能在当前机器上直接用，会报 `failed to locate pyvenv.cfg`

## 本轮同步更新的文档

本轮除代码修复外，还同步修正了以下文档或帮助文本的失真：

- `CLAUDE.md`
- `bot/data/README.md`
- `bot/messages.py`
- `bot/messages.json`

## 后续工作建议

- 如果要继续推进 Web 端，请以 `bot/web/server.py` + `bot/web/api_service.py` 为后端基座，不要继续扩写旧的 `bot/handlers/webcli.py` / `bot/handlers/kimi_web.py` / `bot/handlers/tui_server.py`
- 面向公网访问时，优先做 Web 侧权限收敛、移动端单列 UI、会话级认证，以及 Cloudflared named tunnel + Access 的部署链路
