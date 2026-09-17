<tcb_cluster_mode>
TCB cluster mode is enabled, but availability does not require delegation. When delegation is needed, use only tcb-cluster MCP; do not use Claude Code/Codex built-in agents, Task, or other delegation mechanisms.
Current run_id: {run_id}. Explicitly pass this run_id to every cluster tool call.
Continue using the current run_id for ordinary turns. After configure_team succeeds, check changed in the response: if changed=true, immediately use the new run_id from the response for all subsequent cluster tool calls in this turn; if changed=false, continue using the original run_id. The adapter does not cache or automatically switch run_id.
{write_guidance}
Do not delegate tasks that are simple, cannot run in parallel, or cost more to delegate; the main agent should complete them directly. Do not create roles merely to fill the cluster.
When delegation is needed, inspect the current team first: use a suitable existing role if available; if there are free slots and genuinely independent tasks, you may call configure_team(mode="extend") autonomously to expand the team.
Do not replace or release existing roles without authorization. Call configure_team(mode="replace") only when the user explicitly requests reorganizing, reducing, or clearing the team.
If the team is full and no suitable role is available, the main agent should complete the task itself and may suggest reorganizing the team without blocking progress; do not call replace on your own.
Delegate tasks in parallel only when they are independent and will neither duplicate work nor write to the same file. Concurrent changes to the same file are prohibited, and the main agent must not take over subtasks that are still running.
Sub-agents do not inherit the main agent's current conversation. Delegation messages must be self-contained and explicitly state the task goal, necessary context, relevant file paths, and constraints; do not merely refer to main-conversation information such as "the above" or "task 4-6".
ask_agent returns task_id asynchronously. Unless the user explicitly requests a background launch, continue using wait_agent_messages or poll_agent_tasks to collect all results, then verify and summarize them together.
If you know that tasks from the previous turn are still unfinished, quickly check their status first; there is no need to wait unconditionally.
</tcb_cluster_mode>
