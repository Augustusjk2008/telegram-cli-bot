# 集群模板和配置 bundle

默认模板来自 `bot/cluster/templates.default.json`。如需本地覆盖，在仓库根目录创建 `cluster_templates.json`。后端优先读取环境变量 `TCB_CLUSTER_TEMPLATES_FILE` 指向文件，其次读取仓库根目录 `cluster_templates.json`，最后读取默认模板文件。

## 模板接口

- `GET /api/admin/bots/{alias}/cluster/templates`
- `POST /api/admin/bots/{alias}/cluster/templates/preview`
- `POST /api/admin/bots/{alias}/cluster/templates/apply`

`apply` 请求必须带：

```json
{
  "template_id": "full_test",
  "confirm_overwrite_agents": true
}
```

## 自定义 bundle 接口

- `GET /api/admin/bots/{alias}/cluster/schema`
- `POST /api/admin/bots/{alias}/cluster/config-bundle/preview`
- `POST /api/admin/bots/{alias}/cluster/config-bundle/apply`

`preview` 和 `apply` 都接收 JSON bundle。`apply` 也必须带 `confirm_overwrite_agents=true`。

## 覆盖语义

模板和 bundle 应用都是破坏性操作：

- 覆盖当前 Bot 全部子 agent 配置
- 更新当前 Bot 的 cluster 配置
- 不创建 `main` agent

## LLM 生成约束

`GET /cluster/schema` 返回：

- `version`
- `schema`
- `instructions`

约束重点：

- 只输出 JSON bundle
- 默认 agent 只读
- 只有用户明确要求并行写代码，才设置 `cluster.allow_write=true`
- `agent.id` 必须小写英文开头，且不能为 `main`

## 前端行为

集群配置页提供两种入口：

- 预设模板一键预览和覆盖应用
- 粘贴 JSON bundle 预览和覆盖应用

应用前会二次确认，因为会覆盖原有子 agent 配置。
