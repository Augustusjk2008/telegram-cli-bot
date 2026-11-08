<tcb_cluster_mode>
Cluster mode remains enabled; continue following the cluster rules established earlier in this conversation.
Current run_id: {run_id}. Explicitly pass this run_id to every cluster tool call.
Continue using the current run_id for ordinary turns. After configure_team succeeds, check changed in the response: if changed=true, immediately use the new run_id from the response for all subsequent cluster tool calls in this turn; if changed=false, continue using the original run_id. The adapter does not cache or automatically switch run_id.
ask_agent is asynchronous and returns task_id immediately. You may end the current turn while a child agent runs; tell the user it will notify the main session automatically when it ends. When a cluster completion prompt arrives, call poll_agent_tasks for the task details. You do not need to call wait_agent_messages just to wait.
To stop one queued or running child task, call cancel_agent_task with its task_id and the current run_id; it does not stop other child tasks.
</tcb_cluster_mode>
