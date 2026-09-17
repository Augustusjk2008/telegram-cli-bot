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
	const runId = String(inputRunId || "").trim();
	if (!runId) {
		throw new Error("run_id is required");
	}
	return runId;
}

function clusterRuntimeEnabled(): boolean {
	return Boolean(String(process.env.TCB_CLUSTER_MCP_CONFIG || "").trim());
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
			`Use ${name} only inside <tcb_cluster_mode> and always pass the current run_id.`,
		],
		parameters,
		async execute(_toolCallId, params, signal) {
			const runId = clusterRunId(params.run_id);
			const data = await callClusterTool(name, runId, payloadBuilder(params), signal);
			return jsonResult(data);
		},
	});
}

const runIdParam = Type.String({ description: "TCB cluster run id." });
const configureTeamParams = Type.Object({
	run_id: runIdParam,
	mode: Type.String({ enum: ["extend", "replace"] }),
	roles: Type.Array(Type.Object({
		name: Type.String(),
		responsibility: Type.String(),
	})),
});

export default function (pi: ExtensionAPI) {
	if (!clusterRuntimeEnabled()) {
		return;
	}

	pi.registerTool(clusterTool(
		"configure_team",
		"Configure Team",
		"Configure the current main session's team. The main agent may autonomously use extend to add roles in free slots; use replace only when the user explicitly requests regrouping, reducing, or clearing the team. After success, check changed in the response: if changed=true, immediately use the new run_id from the response for all subsequent tool calls in this turn; if changed=false, keep using the original run_id. The Pi adapter does not cache or automatically switch run_id.",
		configureTeamParams,
		(params) => withoutRunId(params),
	));
	pi.registerTool(clusterTool(
		"cluster_status",
		"Cluster Status",
		"Inspect the current team, internal agent IDs for roles, capacity, free slots, and task occupancy.",
		Type.Object({ run_id: runIdParam }),
		(params) => withoutRunId(params),
	));
	pi.registerTool(clusterTool(
		"list_agents",
		"List Agents",
		"List the current team, internal agent IDs for roles, capacity, free slots, and task occupancy.",
		Type.Object({
			run_id: runIdParam,
			include_disabled: Type.Optional(Type.Boolean()),
		}),
		(params) => withoutRunId(params),
	));
	pi.registerTool(clusterTool(
		"new_agent_session",
		"New Agent Session",
		"Start a new session for a child agent whose current session is idle and has no queued/running cluster tasks; previous session history is preserved.",
		Type.Object({
			run_id: runIdParam,
			agent_id: Type.String(),
		}),
		(params) => withoutRunId(params),
	));
	pi.registerTool(clusterTool(
		"ask_agent",
		"Ask Agent",
		"Start an asynchronous TCB child agent task and immediately return task_id; for tasks that are not running in the background, then wait for and summarize the results.",
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
		"Poll asynchronous child agent task status, progress messages, and results in the current TCB cluster.",
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
		"Block until the next unread message from any child agent in the current TCB cluster.",
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
