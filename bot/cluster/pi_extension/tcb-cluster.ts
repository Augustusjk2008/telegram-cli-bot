import { readFileSync } from "node:fs";
import { Type } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";

type BridgeConfig = {
	bridge_url: string;
	token_file: string;
};

function clusterConfigPath(): string {
	const configPath = String(process.env.TCB_CLUSTER_MCP_CONFIG || "").trim();
	if (!configPath) {
		throw new Error("TCB_CLUSTER_MCP_CONFIG is not set");
	}
	return configPath;
}

function clusterRunId(inputRunId?: string): string {
	const runId = String(inputRunId || process.env.TCB_CLUSTER_RUN_ID || "").trim();
	if (!runId) {
		throw new Error("run_id is required");
	}
	return runId;
}

function clusterRuntimeEnabled(): boolean {
	return Boolean(
		String(process.env.TCB_CLUSTER_MCP_CONFIG || "").trim()
		&& String(process.env.TCB_CLUSTER_RUN_ID || "").trim(),
	);
}

function loadBridgeConfig(): { bridgeUrl: string; token: string } {
	const config = JSON.parse(readFileSync(clusterConfigPath(), "utf8")) as BridgeConfig;
	const bridgeUrl = String(config.bridge_url || "").trim().replace(/\/+$/, "");
	const tokenFile = String(config.token_file || "").trim();
	if (!bridgeUrl || !tokenFile) {
		throw new Error("Invalid TCB cluster bridge config");
	}
	const token = readFileSync(tokenFile, "utf8").trim();
	if (!token) {
		throw new Error("TCB cluster token is empty");
	}
	return { bridgeUrl, token };
}

function withoutRunId<T extends { run_id?: string }>(params: T): Omit<T, "run_id"> {
	const { run_id: _runId, ...payload } = params;
	return payload;
}

async function callClusterTool(toolName: string, runId: string, payload: Record<string, unknown>, signal?: AbortSignal) {
	const { bridgeUrl, token } = loadBridgeConfig();
	const response = await fetch(`${bridgeUrl}/api/internal/cluster/mcp/tools/${toolName}`, {
		method: "POST",
		headers: {
			Authorization: `Bearer ${token}`,
			"Content-Type": "application/json",
			"X-TCB-Cluster-Run-Id": runId,
		},
		body: JSON.stringify(payload),
		signal,
	});
	const text = await response.text();
	let data: unknown = text;
	try {
		data = text ? JSON.parse(text) : {};
	} catch {
		// Keep raw text for diagnostics.
	}
	if (!response.ok) {
		throw new Error(typeof data === "string" ? data : JSON.stringify(data));
	}
	return data;
}

function jsonResult(data: unknown) {
	return {
		content: [{ type: "text" as const, text: JSON.stringify(data) }],
		details: { data },
	};
}

function clusterTool(
	name: string,
	label: string,
	description: string,
	parameters: any,
	payloadBuilder: (params: any) => Record<string, unknown>,
) {
	return defineTool({
		name,
		label,
		description,
		promptSnippet: description,
		promptGuidelines: [
			`Use ${name} only inside <tcb_cluster_mode> and pass the current run_id when it is available.`,
		],
		parameters,
		async execute(_toolCallId, params, signal) {
			const runId = clusterRunId(params.run_id);
			const data = await callClusterTool(name, runId, payloadBuilder(params), signal);
			return jsonResult(data);
		},
	});
}

const runIdParam = Type.Optional(Type.String({ description: "TCB cluster run id; defaults to TCB_CLUSTER_RUN_ID." }));

export default function (pi: ExtensionAPI) {
	if (!clusterRuntimeEnabled()) {
		return;
	}

	pi.registerTool(clusterTool(
		"cluster_status",
		"Cluster Status",
		"查看当前 TCB 集群运行状态和可用子 agent。",
		Type.Object({ run_id: runIdParam }),
		(params) => withoutRunId(params),
	));
	pi.registerTool(clusterTool(
		"list_agents",
		"List Agents",
		"列出当前 TCB 集群可调用子 agent。",
		Type.Object({
			run_id: runIdParam,
			include_disabled: Type.Optional(Type.Boolean()),
		}),
		(params) => withoutRunId(params),
	));
	pi.registerTool(clusterTool(
		"ask_agent",
		"Ask Agent",
		"异步启动 TCB 子 agent 任务并立即返回 task_id；非后台任务随后应等待结果并汇总。",
		Type.Object({
			run_id: runIdParam,
			agent_id: Type.String(),
			message: Type.String(),
			model_tier: Type.Optional(Type.String()),
			timeout_seconds: Type.Optional(Type.Integer({ description: "Soft deadline; timeout reports status but does not kill the agent." })),
			allow_write: Type.Optional(Type.Boolean()),
		}),
		(params) => withoutRunId(params),
	));
	pi.registerTool(clusterTool(
		"poll_agent_tasks",
		"Poll Agent Tasks",
		"轮询当前 TCB 集群子 agent 异步任务状态、过程消息和结果。",
		Type.Object({
			run_id: runIdParam,
			task_ids: Type.Optional(Type.Array(Type.String())),
			include_output: Type.Optional(Type.Boolean()),
			include_messages: Type.Optional(Type.Boolean()),
			message_limit: Type.Optional(Type.Integer()),
			wait_seconds: Type.Optional(Type.Number({ description: "Maximum time to wait for updated task state." })),
		}),
		(params) => withoutRunId(params),
	));
	pi.registerTool(clusterTool(
		"wait_agent_messages",
		"Wait Agent Messages",
		"阻塞等待当前 TCB 集群任意子 agent 的下一条未读回告。",
		Type.Object({
			run_id: runIdParam,
			after_sequence: Type.Optional(Type.Integer()),
			wait_seconds: Type.Optional(Type.Number({ description: "Maximum blocking wait for the next unread message." })),
			include_progress: Type.Optional(Type.Boolean()),
			include_final: Type.Optional(Type.Boolean()),
			message_limit: Type.Optional(Type.Integer()),
		}),
		(params) => withoutRunId(params),
	));
}
