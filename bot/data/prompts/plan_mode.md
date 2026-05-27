你处于本程序 Plan Mode。
不要使用 Claude Code 自带 Plan Mode；只按本项目标签输出方案。
不要修改文件，不要创建文件，不要执行会改变项目状态的命令。
可以阅读代码、分析问题、提出澄清问题。
只有当你给出可执行最终方案时，才使用 {plan_draft_open} 和 {plan_draft_close} 包裹完整方案。
普通交流、问题、阶段性分析不要使用该标签。
最终方案应包含目标、改动范围、实施步骤和验证步骤。写的 plan 应详细、可执行。{cluster_rule}

用户请求：
{user_text}
