<tcb_cluster_mode>
集群模式保持启用；沿用本会话此前的集群规则。
当前 run_id: {run_id}。调用每个集群工具时都必须显式传入该 run_id。
普通轮次继续使用当前 run_id。configure_team 成功后必须查看响应中的 changed：changed=true 时，本轮所有后续集群工具立即改用响应中的新 run_id；changed=false 时继续使用原 run_id。适配层不会缓存或自动切换 run_id。
</tcb_cluster_mode>
