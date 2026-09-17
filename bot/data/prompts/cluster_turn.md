<tcb_cluster_mode>
Cluster mode remains enabled; continue following the cluster rules established earlier in this conversation.
Current run_id: {run_id}. Explicitly pass this run_id to every cluster tool call.
Continue using the current run_id for ordinary turns. After configure_team succeeds, check changed in the response: if changed=true, immediately use the new run_id from the response for all subsequent cluster tool calls in this turn; if changed=false, continue using the original run_id. The adapter does not cache or automatically switch run_id.
</tcb_cluster_mode>
