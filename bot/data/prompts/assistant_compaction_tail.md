maintenance:
- 后台维护任务：如有必要，请静默更新固定 working 文件：current_goal.md、open_loops.md、user_prefs.md、recent_summary.md。
- working 记忆应以简短 Markdown 列表为主；标题可以存在，但宿主主要读取列表项。
- 不要创建任意新的 working 记忆文件，否则不会进入宿主维护的 prompt。
- 如出现不应自动生效的长期规则或升级建议，请创建 .assistant/proposals/*.json。
- 不要在回复中主动提及这些后台维护动作，除非用户明确询问。
- 当前待压缩 captures: {pending_capture_count}
