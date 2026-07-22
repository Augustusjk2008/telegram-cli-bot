<tcb_cluster_mode>
TCB 集群模式已启用。需要委派时只能使用 tcb-cluster MCP，不要使用 Claude Code/Codex 自带 agent、Task 或其它委派机制。
当前 run_id: {run_id}；显式提及的子 agent: {mentioned_agents}。调用集群工具时传入该 run_id。
只把相互独立、不会重复工作或写同一文件的任务并行委派；主 agent 不要代做仍在运行的子任务。
ask_agent 异步返回 task_id。除非用户明确要求后台启动，否则必须继续用 wait_agent_messages 或 poll_agent_tasks 收齐结果，再统一验证和总结。
如果已知上一轮仍有未完成任务，先快速查询其状态，不必无条件等待。
</tcb_cluster_mode>
